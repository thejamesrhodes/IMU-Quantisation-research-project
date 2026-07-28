/**
  ******************************************************************************
  * @file    sampler.c
  * @brief   FIFO watermark interrupt -> DMA -> ring.
  ******************************************************************************
  */

#include "sampler.h"
#include "imu_icm42688.h"
#include "storage.h"
#include "record.h"
#include "timebase.h"
#include "console.h"
#include "sheppard_config.h"

#include <string.h>
#include "main.h"

/* Chip-select / interrupt pin per slot, mirroring bus.c's table. The INT pin
   labels are INT<slot>_1, i.e. slot N's INT1 -- the number is the physical
   slot, not the peripheral (TN-16 section 1.2). */
static const uint16_t s_int_pin[BUS_SLOT_COUNT] = {
  INT1_1_Pin,   /* slot 1  ICM */
  INT2_1_Pin,   /* slot 2  ICM */
  INT3_1_Pin,   /* slot 3  ISM */
  INT4_1_Pin,   /* slot 4  BMI */
};

/* One transfer in flight per slot, so one scratch. The DMA cannot write
   straight into the ring because the transfer includes a leading address
   byte, and writing that byte into the ring would clobber the last byte of
   the previous packet. So: DMA here, then copy. ~1000 B at 32 MHz is ~30 us,
   which at 8 kHz is 0.5% of the interrupt budget. */
static uint8_t  s_scratch[BUS_MAX_XFER] __attribute__((aligned(4)));

static volatile uint8_t  s_running;
static bus_slot_t        s_slot;
static uint16_t          s_wm;              /* bytes per read               */
static volatile uint64_t s_t_pending;       /* TIM2 at the triggering IRQ   */
static volatile uint32_t s_lost_packets;
static sampler_stats_t   s_st;

/* ==========================================================================
 * Watermark policy
 * ========================================================================== */

uint16_t sampler_watermark_for(long odr_hz)
{
  if (odr_hz <= 0) { return ICM_PACKET4_LEN; }

  /* ~SHEPPARD_WM_TARGET_MS of samples... */
  long pkts = (odr_hz * (long)SHEPPARD_WM_TARGET_MS) / 1000L;
  if (pkts < 1) { pkts = 1; }

  /* ...capped, so the interrupt rate stays bounded at high ODR and the
     watermark stays well inside the 2 KiB FIFO. */
  long bytes = pkts * (long)ICM_PACKET4_LEN;
  if (bytes > (long)SHEPPARD_WM_MAX_BYTES)
  {
    pkts  = (long)SHEPPARD_WM_MAX_BYTES / (long)ICM_PACKET4_LEN;
    bytes = pkts * (long)ICM_PACKET4_LEN;
  }
  return (uint16_t)bytes;
}

/* ==========================================================================
 * DMA completion -- interrupt context
 * ========================================================================== */

static void on_dma_done(bus_slot_t slot, int status, void *ctx)
{
  uint8_t *dst = (uint8_t *)ctx;
  (void)slot;

  if (status != BUS_OK)
  {
    s_st.faults++;
    s_lost_packets += (uint32_t)(s_wm / ICM_PACKET4_LEN);
    /* Still advance nothing: a faulted transfer's contents are undefined and
       must not enter the archive. It is recorded as a gap instead, which is
       the honest representation of a sample the hardware could not fetch. */
    return;
  }

  memcpy(dst, &s_scratch[1], s_wm);
  s_st.reads_done++;

  storage_advance(s_wm, s_t_pending, 0U,
                  (uint16_t)((s_st.faults != 0U) ? SDAT_F_BUS_FAULT : 0U));
}

/* ==========================================================================
 * Watermark interrupt
 * ========================================================================== */

void sampler_on_int(uint16_t gpio_pin)
{
  if (!s_running || gpio_pin != s_int_pin[s_slot]) { return; }

  /* First thing, before any SPI: the timestamp must refer to the sample
     instant, not to whenever the transfer happened to complete. */
  uint64_t t = timebase_now_us();
  s_st.interrupts++;

  uint16_t space = 0;
  uint8_t *dst = storage_fill_ptr(&space);
  if (dst == NULL || space < s_wm)
  {
    /* Ring full, or not enough room in the current block. Either way the
       sensor produced samples we cannot take -- a gap, counted, not hidden. */
    s_st.ring_full++;
    s_lost_packets += (uint32_t)(s_wm / ICM_PACKET4_LEN);
    return;
  }

  s_scratch[0] = (uint8_t)(ICM_FIFO_DATA | 0x80U);
  memset(&s_scratch[1], 0, s_wm);
  s_t_pending = t;

  int rc = bus_xfer_async(s_slot, s_scratch, s_scratch,
                          (uint16_t)(s_wm + 1U), on_dma_done, dst);
  if (rc == BUS_OK) { s_st.reads_started++; }
  else
  {
    s_st.bus_busy++;
    s_lost_packets += (uint32_t)(s_wm / ICM_PACKET4_LEN);
  }
}

/* ==========================================================================
 * Arm / disarm
 * ========================================================================== */

int sampler_start(bus_slot_t slot, uint16_t watermark_bytes)
{
  if (s_running) { return -1; }
  if (!storage_is_open())
  {
    console_printf("sampler: no record open\r\n");
    return -1;
  }
  if (watermark_bytes == 0U || watermark_bytes > (BUS_MAX_XFER - 1U))
  {
    return -1;
  }

  s_slot = slot;
  s_wm   = watermark_bytes;
  memset(&s_st, 0, sizeof s_st);
  s_lost_packets = 0U;

  /* Watermark, in bytes -- INTF_CONFIG0 == 0x30 puts FIFO_COUNT in bytes, and
     the threshold uses the same unit. */
  if (icm_write8_verify(slot, ICM_FIFO_CONFIG2,
                        (uint8_t)(watermark_bytes & 0xFFU)) != 0) { return -1; }
  if (icm_write8_verify(slot, ICM_FIFO_CONFIG3,
                        (uint8_t)((watermark_bytes >> 8) & 0x0FU)) != 0) { return -1; }

  /* INT1 push-pull, active high, pulsed. Same as TN-16 section 9.2's
     data-ready configuration -- only the source differs. */
  (void)icm_write8(slot, ICM_INT_CONFIG, 0x03U);

  /* Route the FIFO threshold to INT1, and ONLY that. Data-ready on the same
     pin would be indistinguishable without reading INT_STATUS, which is an
     SPI transaction and forbidden in the ISR. */
  if (icm_write8_verify(slot, ICM_INT_SOURCE0, ICM_FIFO_THS_INT1_EN) != 0)
  {
    return -1;
  }

  /* Start from empty so the first read is not a backlog from before arming. */
  (void)icm_fifo_flush(slot);

  s_running = 1U;
  return 0;
}

void sampler_stop(void)
{
  if (!s_running) { return; }
  s_running = 0U;

  /* Stop the source before anything else, then let any transfer already in
     flight complete on its own -- aborting it mid-DMA would leave the bus
     layer's busy flag set. */
  (void)icm_write8(s_slot, ICM_INT_SOURCE0, 0x00U);

  uint64_t t0 = timebase_now_us();
  while (bus_busy(s_slot) && (timebase_now_us() - t0) < 50000ULL) { }
}

int sampler_running(void) { return (int)s_running; }

void sampler_get_stats(sampler_stats_t *out)
{
  if (out != NULL) { *out = s_st; }
}

uint32_t sampler_lost_packets(void) { return s_lost_packets; }
