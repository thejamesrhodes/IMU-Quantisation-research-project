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
static uint8_t  s_cnt_tx[4];
static uint8_t  s_cnt[4];

static volatile uint64_t s_t_pending;       /* TIM2 at the triggering IRQ   */
static volatile uint64_t s_last_int_us;
static volatile uint8_t  s_chain;           /* a drain chain is in flight   */
static volatile uint16_t s_avail;           /* FIFO bytes at the count read */
static volatile uint32_t s_pending_pkts;

/* Deferred chain step, executed in PendSV. */
#define STEP_NONE   0U
#define STEP_COUNT  1U
#define STEP_DATA   2U
static volatile uint8_t   s_step;
static uint8_t  *volatile s_step_dst;
static volatile uint16_t  s_step_len;

static volatile uint64_t  s_chain_start_us;  /* liveness timeout reference  */
static volatile uint8_t   s_retries;         /* consecutive chain retries   */

#define SAMPLER_MAX_RETRIES 3U

/* The ICM FIFO is 2048 bytes; in 20-byte packet mode it holds 102 packets, so
   2040 B is full. A count read returning at or near that means the FIFO
   wrapped and samples were overwritten before we fetched them. */
#define ICM_FIFO_BYTES        2048U
#define ICM_FIFO_FULL_MARK    2000U

static uint32_t          s_watchdog_us;
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

/* --------------------------------------------------------------------------
 * The drain chain, entirely in interrupt context
 *
 *   EXTI  -> DMA read FIFO_COUNT (3 B)
 *         -> DMA read exactly that many whole packets
 *         -> copy into the ring, commit, and if the FIFO is still above the
 *            watermark, go round again
 *
 * Nothing here blocks and nothing needs the main loop. That is the point: at
 * ODR 8000 a worst-case SD write blocks the main loop for 33 ms, during which
 * 5.3 KB arrives into a 2 KiB FIFO. Any service path that waits for the main
 * loop loses data no matter how it is tuned. This one keeps draining while
 * f_write is stalled, because DMA and the main loop are independent.
 *
 * Reading FIFO_COUNT first, rather than assuming the watermark, is what makes
 * the drain complete: a fixed-size read can leave the FIFO above threshold,
 * and since the interrupt is PULSED there is then no further transition and
 * the stream latches. Draining to empty guarantees the next arrival crosses
 * the threshold from below.
 * -------------------------------------------------------------------------- */

/* Hand the next step to PendSV. Never start a transfer directly from a bus
   completion callback -- see the note at the top of sampler.h. */
static inline void pend_step(uint8_t step)
{
  s_step = step;
  __DSB();
  SCB->ICSR = SCB_ICSR_PENDSVSET_Msk;
  __DSB();
}

/* Accounts for a start that never reached the hardware. When the bus layer
   returns BUS_E_FAULT it has already run the completion callback with a fault
   status, which does its own accounting -- adding it again here is what turned
   one lost read into the phantom "20 packets" in the 28 July regression. */
/* Ends a chain that could not complete.
 *
 * A fault leaves the FIFO above the watermark, and because INT1 is pulsed no
 * further pulse will come -- the stream is latched from that moment. At ODR
 * 8000 the FIFO overflows 6.5 ms later, which is shorter than any watchdog
 * period that does not also false-trigger on the 6.25 ms normal interval. The
 * two requirements are irreconcilable in a time-based watchdog, so recovery is
 * event-driven instead: retry immediately from PendSV. The retry budget is
 * bounded so a hard fault degrades to the watchdog rather than spinning. */
static void chain_abort(void)
{
  if (s_retries < SAMPLER_MAX_RETRIES)
  {
    s_retries++;
    s_st.retries++;
    pend_step(STEP_COUNT);
    return;
  }
  s_chain = 0U;
}

static void account_start_failure(int rc, uint32_t pkts_lost)
{
  if (rc == BUS_E_BUSY)
  {
    /* Someone else owns the bus, which during a record can only be a transfer
       belonging to the chain that is already running. Do NOT clear s_chain
       here: that transfer's completion callback owns it, and stealing the flag
       lets a second chain start concurrently and overwrite s_pending_pkts and
       s_avail underneath the first one's data read -- silent corruption of the
       byte count copied into the ring. The liveness timeout in sampler_poll()
       is the backstop against a chain that never finishes. */
    s_st.bus_busy++;
    return;
  }

  s_st.start_err++;

  /* On BUS_E_FAULT the bus layer already ran the completion callback with a
     fault status, which does its own accounting and clears the chain. */
  if (rc != BUS_E_FAULT)
  {
    s_lost_packets += pkts_lost;
    chain_abort();
  }
}

static void on_data(bus_slot_t slot, int status, void *ctx)
{
  uint8_t *dst = (uint8_t *)ctx;
  (void)slot;

  if (status != BUS_OK)
  {
    s_st.faults++;
    s_lost_packets += s_pending_pkts;
    /* A faulted transfer's contents are undefined and must not enter the
       archive. Recorded as a gap, which is the honest representation of a
       sample the hardware could not fetch. */
    chain_abort();
    return;
  }

  uint16_t n = (uint16_t)(s_pending_pkts * ICM_PACKET4_LEN);
  memcpy(dst, &s_scratch[1], n);
  s_st.reads_done++;
  s_retries = 0U;                       /* progress: reset the retry budget */

  storage_advance(n, s_t_pending, s_avail, 0U);

  /* Always go round and re-read FIFO_COUNT. The chain terminates in on_count()
     when the FIFO is found below the watermark, because only then is a pulse
     guaranteed to arrive -- the interrupt fires on the upward crossing, so
     stopping while still above the threshold means no further transition, no
     further interrupt, and a stream that dies silently.
     The previous condition, `s_avail > n + s_wm`, could never be true: n is
     s_avail rounded down to a packet boundary, so it asked whether
     s_avail > s_avail + watermark. That is why `chained drains` read 0 at every
     ODR, and why ODR 8000 ran at half rate on watchdog kicks alone. */
  s_st.chained++;
  pend_step(STEP_COUNT);
}

static void on_count(bus_slot_t slot, int status, void *ctx)
{
  (void)slot; (void)ctx;

  if (status != BUS_OK) { s_st.faults++; chain_abort(); return; }

  s_avail = (uint16_t)(((uint16_t)s_cnt[1] << 8) | s_cnt[2]);
  if (s_avail > s_st.fifo_peak) { s_st.fifo_peak = s_avail; }

  /* At capacity the FIFO has wrapped and samples were overwritten before we
     fetched them. FIFO_COUNT saturates, so the firmware cannot say how many --
     the run is flagged rather than silently patched, and the packet timestamps
     let the reader locate each discontinuity exactly. A record with a non-zero
     overflow count is not admissible under R1. */
  if (s_avail >= ICM_FIFO_FULL_MARK) { s_st.overflows++; }

  /* Below the watermark the level will cross it from below as new samples
     arrive, so a pulse IS coming and the chain can stop here. At or above it,
     no transition occurs and no pulse will come, so the chain must continue or
     the stream latches. This test is the one that keeps the drain alive. */
  if (s_avail < s_wm) { s_retries = 0U; s_chain = 0U; return; }

  uint32_t pkts = s_avail / ICM_PACKET4_LEN;
  if (pkts == 0U) { s_retries = 0U; s_chain = 0U; return; }

  /* Cap by the transfer ceiling and by what fits in one ring block. */
  const uint32_t max_by_xfer = (BUS_MAX_XFER - 1U) / ICM_PACKET4_LEN;
  if (pkts > max_by_xfer) { pkts = max_by_xfer; }

  uint16_t need = (uint16_t)(pkts * ICM_PACKET4_LEN);
  uint8_t *dst = storage_fill_ptr(need);
  if (dst == NULL)
  {
    s_st.ring_full++;
    s_lost_packets += pkts;
    s_chain = 0U;
    return;
  }

  s_pending_pkts = pkts;
  s_scratch[0] = (uint8_t)(ICM_FIFO_DATA | 0x80U);
  memset(&s_scratch[1], 0, need);

  s_step_dst = dst;
  s_step_len = (uint16_t)(need + 1U);
  pend_step(STEP_DATA);
}

static void start_count_read(uint64_t t)
{
  s_t_pending      = t;
  s_chain_start_us = timebase_now_us();
  s_cnt_tx[0] = (uint8_t)(ICM_FIFO_COUNTH | 0x80U);
  s_cnt_tx[1] = 0U;
  s_cnt_tx[2] = 0U;

  int rc = bus_xfer_async(s_slot, s_cnt_tx, s_cnt, 3U, on_count, NULL);
  if (rc != BUS_OK) { account_start_failure(rc, 0U); }
}

/* --------------------------------------------------------------------------
 * PendSV -- the only place a chain step is started
 * -------------------------------------------------------------------------- */

void sampler_pendsv(void)
{
  uint8_t step = s_step;
  s_step = STEP_NONE;

  /* Every legitimate pend happens with the chain flag set. If it has since been
     cleared -- by sampler_stop, or by a start that was refused with the bus
     busy -- the step is stale and running it would put a second chain on the
     same slot. */
  if (!s_running || !s_chain) { return; }

  if (step == STEP_DATA)
  {
    int rc = bus_xfer_async(s_slot, s_scratch, s_scratch, s_step_len,
                            on_data, s_step_dst);
    if (rc == BUS_OK) { s_st.reads_started++; }
    else              { account_start_failure(rc, s_pending_pkts); }
  }
  else if (step == STEP_COUNT)
  {
    /* A continuation has no interrupt instant of its own, so it is anchored to
       the moment the read is initiated. The rule across both cases is the same:
       the block timestamp is when the read that filled it STARTED, never when
       the transfer completed. Per-sample timing comes from the packet TMST
       field; the block timestamp exists to anchor that 16-bit counter against
       TIM2, so reusing the original interrupt time here would place a block of
       later-fetched samples at an anchor several milliseconds in its past. */
    start_count_read(timebase_now_us());
  }
}

/* ==========================================================================
 * Watermark interrupt
 * ========================================================================== */

void sampler_on_int(uint16_t gpio_pin)
{
  if (!s_running || gpio_pin != s_int_pin[(int)s_slot]) { return; }

  /* First thing, before any SPI: the timestamp must refer to the sample
     instant, not to whenever the transfer happened to complete. */
  uint64_t t = timebase_now_us();
  s_st.interrupts++;
  s_last_int_us = t;

  /* A chain already running will drain whatever this interrupt was about, so
     stacking another would only fight it for the bus. */
  if (s_chain) { return; }

  s_chain = 1U;
  start_count_read(t);
}

/* --------------------------------------------------------------------------
 * Watchdog -- main loop
 *
 * INT1 is configured PULSED, so the threshold interrupt fires on the
 * TRANSITION across the watermark. If a single service is missed the FIFO
 * keeps filling, reaches 2 KiB, and in stream mode sits permanently above the
 * threshold -- there is no further transition, so there are no further
 * pulses, and the stream is dead until the record ends.
 *
 * That is exactly what killed the first ODR 8000 attempt: five interrupts in
 * sixty seconds, one ring-full, then silence. At 100 Hz and 1 kHz a service
 * was never missed, so it never showed.
 *
 * The watchdog makes a missed service survivable rather than terminal: if no
 * interrupt has arrived for several expected intervals, poll FIFO_COUNT and
 * restart the stream by hand. Latched-full is detected and reported as the
 * gap it is, rather than as a mysteriously short record.
 * -------------------------------------------------------------------------- */

void sampler_poll(void)
{
  if (!s_running) { return; }

  uint64_t now;
  uint8_t  claim = 0U;
  uint8_t  stuck = 0U;

  /* The whole decision is taken with interrupts off. Read `now` and
     `s_last_int_us` separately and an interrupt landing between them makes
     `last` LATER than `now`; the unsigned subtraction then underflows to
     roughly 2^64 and the watchdog fires spuriously. That is the entire source
     of the "busy 20 / wdog 20" and "busy 117 / wdog 117" in the 28 July runs --
     the counts matched exactly because each bogus kick was refused by the bus
     that the interrupt had just claimed. A 64-bit read is also two loads on
     Cortex-M and so not atomic against the ISR that writes it. */
  uint32_t primask = __get_PRIMASK();
  __disable_irq();

  now = timebase_now_us();

  if (s_chain)
  {
    /* Liveness backstop. A chain that has not completed in several watchdog
       periods has lost its completion callback somewhere; abandon it so the
       stream can be revived. This replaces the old behaviour of clearing
       s_chain whenever a start was refused, which cleared it while a transfer
       was genuinely in flight. */
    if ((now > s_chain_start_us) &&
        ((now - s_chain_start_us) > (uint64_t)s_watchdog_us * 4ULL))
    {
      s_chain = 0U;
      s_step  = STEP_NONE;
      stuck   = 1U;
    }
  }
  else if ((now > s_last_int_us) &&
           ((now - s_last_int_us) >= (uint64_t)s_watchdog_us))
  {
    /* No interrupt for several expected intervals and no chain running: either
       a pulse was missed and the level has latched, or the sensor has stopped.
       Start a drain chain. It reads FIFO_COUNT itself, so it costs one 3-byte
       transfer if the FIFO is genuinely quiet and recovers the stream if it is
       not. No blocking SPI here -- the earlier version called icm_fifo_count()
       synchronously and stole the bus from the interrupt path. */
    s_last_int_us = now;
    s_chain       = 1U;
    claim         = 1U;
  }

  if (primask == 0U) { __enable_irq(); }

  if (stuck)
  {
    s_st.chain_stuck++;
    return;
  }
  if (!claim) { return; }

  s_st.watchdog_kicks++;
  start_count_read(now);
}

/* ==========================================================================
 * Arm / disarm
 * ========================================================================== */

int sampler_start(bus_slot_t slot, uint16_t watermark_bytes, long odr_hz)
{
  if (odr_hz <= 0) { return -1; }
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
  s_chain          = 0U;
  s_step           = STEP_NONE;
  s_retries        = 0U;
  s_last_int_us    = timebase_now_us();
  s_chain_start_us = s_last_int_us;

  /* PendSV at the lowest priority. It must tail-chain only once every pending
     interrupt has been serviced -- that is the entire reason the chain lives
     here rather than in the DMA completion callback -- but it is still an
     exception, so it preempts thread mode and keeps draining the FIFO while
     the main loop is stalled inside f_write. */
  HAL_NVIC_SetPriority(PendSV_IRQn, 15, 0);

  /* Expected interval between watermark interrupts, from the ODR:
        packets_per_read / ODR
     The previous version tried to derive this from the watermark alone, which
     cannot work -- the watermark is CAPPED at SHEPPARD_WM_MAX_BYTES, so above
     about 500 Hz it no longer encodes the ODR at all. It returned ~400 ms at
     every rate. At ODR 8000 the true interval is 6.25 ms, so a latched stream
     went unnoticed for 64 expected intervals and roughly 3200 samples. That
     was the bulk of the 2% gap rate in the first 8 kHz run. */
  {
    uint32_t pkts = (uint32_t)watermark_bytes / ICM_PACKET4_LEN;
    if (pkts == 0U) { pkts = 1U; }
    uint32_t interval_us = (uint32_t)((pkts * 1000000ULL) / (uint32_t)odr_hz);

    /* Deliberately generous, because recovery no longer depends on it: a chain
       that aborts retries itself from PendSV within microseconds (chain_abort
       below), so the watchdog is a second-line backstop rather than the primary
       revival path.

       The previous clamp tied the period to half the FIFO fill time, which at
       ODR 8000 gave 6.4 ms against a 6.25 ms interrupt interval -- a margin of
       2%. Any jitter tripped it, and a slow patch on the SD card produced 3157
       kicks in 60 s. They cost no data, but each is an unscheduled 3-byte SPI
       transaction whose rate tracked the card's mood, and rule R8 exists
       precisely to keep bus activity from varying with anything other than the
       experimental condition. At ODR 8000 this is now 25 ms against a 6.6 ms
       worst observed interval. */
    s_watchdog_us = 4U * interval_us;
    if (s_watchdog_us < 5000U)    { s_watchdog_us = 5000U; }     /* 5 ms   */
    if (s_watchdog_us > 2000000U) { s_watchdog_us = 2000000U; }  /* 2 s    */
  }

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
  s_step    = STEP_NONE;
  s_chain   = 0U;

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
