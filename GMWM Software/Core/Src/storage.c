/**
  ******************************************************************************
  * @file    storage.c
  * @brief   Ring buffer and SD writer for .sdat records.
  ******************************************************************************
  */

#include "storage.h"
#include "record.h"
#include "arena.h"
#include "console.h"
#include "timebase.h"
#include "sampler.h"
#include "sheppard_config.h"

#include <stdio.h>
#include <string.h>

#include "main.h"
#include "fatfs.h"

static const char *const ARENA_OWNER = "storage";

/* ==========================================================================
 * Ring of whole 4 KiB blocks
 *
 * Whole blocks rather than a byte ring: the unit written to the card is a
 * block, the unit CRC'd is a block, and a byte ring would mean assembling one
 * on every write. Producer is the DMA completion ISR, consumer is the main
 * loop, one each -- so head and tail need no locking beyond being volatile.
 * ========================================================================== */

#define RING_BLOCKS   (ARENA_SIZE / SDAT_BLOCK_BYTES)   /* 32 */

static uint8_t *s_ring;                 /* RING_BLOCKS x SDAT_BLOCK_BYTES    */
static volatile uint32_t s_head;        /* block being filled (producer)     */
static volatile uint32_t s_tail;        /* next to write     (consumer)      */
static volatile uint16_t s_fill;        /* payload bytes in the head block   */
static volatile uint32_t s_seq;
static volatile uint32_t s_samples;

static FIL      s_fil;
static uint8_t  s_open;
static uint8_t  s_mounted;
static FATFS    s_fs;
static char     s_path[64];
static char     s_runid[24];
static record_cfg_t s_cfg;
static uint32_t s_last_sync_ms;
static uint64_t s_ts_first;
static uint64_t s_ts_last;      /* trigger instant of the most recent read  */
static uint32_t s_first_pkts;   /* packets delivered by the FIRST read      */
static storage_stats_t s_st;

/* One header scratch, shared by open and close. They were separate 4 KiB
   statics, which is 4 KiB of a 192 KiB region spent on a buffer used twice
   per record and never concurrently. */
static uint8_t  s_hdr[SDAT_HEADER_BYTES];

static inline uint8_t *blk(uint32_t i) { return s_ring + (i % RING_BLOCKS) * SDAT_BLOCK_BYTES; }
static inline uint32_t ring_used(void) { return s_head - s_tail; }

/* ==========================================================================
 * Producer -- interrupt context
 * ========================================================================== */

#define PAYLOAD_BYTES (SDAT_MAX_PACKETS * ICM_PACKET4_LEN)

/* Commit the block currently being filled and move to the next. Shared by the
   normal full-block path and the early rotation below. ISR context. */
static void commit_head(uint16_t extra_flags)
{
  uint8_t *b = blk(s_head);
  sdat_block_hdr_t *h = (sdat_block_hdr_t *)b;

  h->n_packets = (uint16_t)(s_fill / ICM_PACKET4_LEN);
  h->flags    |= extra_flags;
  if (s_fill < PAYLOAD_BYTES) { h->flags |= SDAT_F_PARTIAL; }

  /* Zero the unused tail BEFORE the CRC. The CRC covers the whole 4000-byte
     payload, so computing it first and clearing afterwards stores a checksum
     over bytes the file does not contain -- every partial block would fail
     verification, and there is one at the end of every record. */
  memset(b + SDAT_BLKHDR_BYTES + s_fill, 0,
         SDAT_BLOCK_BYTES - SDAT_BLKHDR_BYTES - s_fill);

  h->crc32 = record_crc32(b + SDAT_BLKHDR_BYTES, PAYLOAD_BYTES);

  s_fill = 0U;
  s_seq++;
  s_head++;                                /* publish last */
}

uint8_t *storage_fill_ptr(uint16_t need)
{
  if (!s_open || need == 0U || need > PAYLOAD_BYTES) { return NULL; }

  /* Not enough room left in this block: close it early rather than discard
     the read. A short block is a bookkeeping detail; a dropped read is a hole
     in a uniformly-sampled series. */
  if ((uint32_t)s_fill + need > PAYLOAD_BYTES)
  {
    if (ring_used() >= (RING_BLOCKS - 1U)) { s_st.blocks_dropped++; return NULL; }
    commit_head(0U);
  }

  /* Head must stay at least one block ahead of tail, or the consumer would be
     reading the block the producer is filling. */
  if (ring_used() >= (RING_BLOCKS - 1U))
  {
    s_st.blocks_dropped++;
    return NULL;
  }

  return blk(s_head) + SDAT_BLKHDR_BYTES + s_fill;
}

void storage_advance(uint16_t bytes, uint64_t t_us, uint16_t fifo_bytes,
                     uint16_t flags)
{
  if (!s_open || bytes == 0U) { return; }

  /* Rate reference. Read i is triggered at t_i and delivers the k_i packets
     that accumulated over (t_{i-1}, t_i], so the samples falling strictly
     inside the window (t_1, t_M] number N - k_1 and

         f = (N - k_1) / (t_M - t_1)

     is unbiased. Deriving f from the `rec` loop bounds instead is not: the
     residual FIFO contents are discarded at stop, so the count is always a
     whole number of watermark reads and f is biased low by up to one watermark
     over the run. That is 0.5% over a 20 s run at ODR 100 but 0.01% at ODR
     8000, which is exactly the spread seen on 28 July (+0.920% vs +1.070%) and
     would otherwise have been read as an ODR-dependent oscillator effect. */
  if (s_ts_first == 0U)
  {
    s_ts_first   = t_us;
    s_first_pkts = (uint32_t)(bytes / ICM_PACKET4_LEN);
  }
  s_ts_last = t_us;

  uint8_t *b = blk(s_head);
  sdat_block_hdr_t *h = (sdat_block_hdr_t *)b;

  if (s_fill == 0U)                       /* first data in this block */
  {
    memset(h, 0, SDAT_BLKHDR_BYTES);
    h->magic = SDAT_BLOCK_MAGIC;
    h->seq   = s_seq;
    h->t_us  = t_us;
    /* Die temperature straight from the first packet's bytes 0x0D/0x0E --
       big-endian, guaranteed by INTF_CONFIG0 == 0x30. Puts the R2 gate value
       in the block header so a reader can check it without decoding. */
    const uint8_t *p0 = b + SDAT_BLKHDR_BYTES;
    h->temp_raw = (uint16_t)(((uint16_t)p0[0x0D] << 8) | p0[0x0E]);
  }

  h->flags     |= flags;
  h->fifo_bytes = fifo_bytes;

  s_fill    = (uint16_t)(s_fill + bytes);
  s_samples += (uint32_t)(bytes / ICM_PACKET4_LEN);

  if (s_fill >= PAYLOAD_BYTES)
  {
    commit_head(0U);
  }
}

uint32_t storage_sample_count(void) { return s_samples; }

/* ==========================================================================
 * Consumer -- main loop
 * ========================================================================== */

int storage_task(void)
{
  if (!s_open) { return 0; }

  int written = 0;

  while (ring_used() > 0U)
  {
    uint8_t *b = blk(s_tail);
    UINT bw = 0;

    uint64_t t0 = timebase_now_us();
    FRESULT fr = f_write(&s_fil, b, SDAT_BLOCK_BYTES, &bw);
    uint32_t dt = (uint32_t)(timebase_now_us() - t0);

    if (fr != FR_OK || bw != SDAT_BLOCK_BYTES)
    {
      console_printf("storage: f_write -> %d (%u/%u B)\r\n",
                     fr, (unsigned)bw, SDAT_BLOCK_BYTES);
      return -1;
    }

    s_st.write_last_us = dt;
    if (dt > s_st.write_max_us) { s_st.write_max_us = dt; }
    s_st.write_total_us += dt;
    s_st.blocks_written++;
    s_st.bytes_written += SDAT_BLOCK_BYTES;

    uint32_t used = ring_used();
    if (used > s_st.ring_peak) { s_st.ring_peak = used; }

    s_tail++;
    written++;
  }

  /* Sync on a timer, not per block -- see SHEPPARD_SD_SYNC_MS. Timed
     separately because f_sync is the FAT update and is the operation most
     likely to produce a long stall. */
  uint32_t now = HAL_GetTick();
  if ((now - s_last_sync_ms) >= SHEPPARD_SD_SYNC_MS)
  {
    s_last_sync_ms = now;
    uint64_t t0 = timebase_now_us();
    (void)f_sync(&s_fil);
    uint32_t dt = (uint32_t)(timebase_now_us() - t0);
    if (dt > s_st.sync_max_us) { s_st.sync_max_us = dt; }
    s_st.syncs++;
  }

  return written;
}

/* ==========================================================================
 * Open / close
 * ========================================================================== */

int storage_mount(void)
{
  if (s_mounted) { return 0; }

  uint8_t bsp = BSP_SD_Init();
  if (bsp != 0U)
  {
    console_printf("storage: BSP_SD_Init -> %u "
                   "(0=OK 1=ERR 2=BUSY 3=TMO 4=NOT_PRESENT)\r\n", bsp);
    return -1;
  }

  FRESULT fr = f_mount(&s_fs, SDPath, 1);
  if (fr != FR_OK)
  {
    console_printf("storage: f_mount -> %d "
                   "(1=DISK_ERR 3=NOT_READY 13=NO_FILESYSTEM)\r\n", fr);
    return -1;
  }

  s_mounted = 1U;
  console_printf("storage: mounted, fs_type=%d csize=%u sect\r\n",
                 (int)s_fs.fs_type, (unsigned)s_fs.csize);
  return 0;
}

int storage_unmount(void)
{
  if (!s_mounted) { return 0; }
  f_mount(NULL, SDPath, 0);
  s_mounted = 0U;
  return 0;
}

int storage_open(const record_cfg_t *cfg, const char *run_id)
{
  if (s_open)      { console_printf("storage: already recording\r\n"); return -1; }
  if (cfg == NULL) { return -1; }
  if (storage_mount() != 0) { return -1; }

  s_ring = arena_claim(ARENA_OWNER);
  if (s_ring == NULL) { return -1; }        /* arena_claim explains why */

  s_cfg = *cfg;
  snprintf(s_runid, sizeof s_runid, "%s", run_id ? run_id : "run");

  /* Flat directory, sortable, descriptive. exFAT with LFN is already
     confirmed working (TN-16 section 6.3), so long names are free. */
  (void)f_mkdir("SHEPPARD");
  snprintf(s_path, sizeof s_path, "SHEPPARD/%s_%s_%ldHz.sdat",
           s_runid, cfg->label ? cfg->label : "rec", cfg->odr_hz);

  FRESULT fr = f_open(&s_fil, s_path, FA_CREATE_ALWAYS | FA_WRITE);
  if (fr != FR_OK)
  {
    console_printf("storage: f_open(%s) -> %d\r\n", s_path, fr);
    arena_release(ARENA_OWNER);
    return -1;
  }

  /* Header written with the mutable fields null and closed:false, so a file
     interrupted by power loss is still valid JSON and self-evidently
     incomplete rather than looking finished. Rewritten by storage_close(). */
  if (record_build_header(s_hdr, cfg, s_runid) < 0)
  {
    f_close(&s_fil);
    arena_release(ARENA_OWNER);
    return -1;
  }

  UINT bw = 0;
  fr = f_write(&s_fil, s_hdr, SDAT_HEADER_BYTES, &bw);
  if (fr != FR_OK || bw != SDAT_HEADER_BYTES)
  {
    console_printf("storage: header write -> %d\r\n", fr);
    f_close(&s_fil);
    arena_release(ARENA_OWNER);
    return -1;
  }

  s_head = s_tail = s_fill = s_seq = s_samples = 0;
  s_ts_first   = 0;
  s_ts_last    = 0;
  s_first_pkts = 0;
  memset(&s_st, 0, sizeof s_st);
  s_last_sync_ms = HAL_GetTick();
  s_open = 1U;                              /* arms the producer, last */

  console_printf("storage: recording to %s\r\n", s_path);
  return 0;
}

int storage_close(uint32_t n_gaps, uint64_t ts_first_us, uint64_t ts_last_us,
                  int32_t t_start_mc, int32_t t_end_mc)
{
  (void)ts_first_us; (void)ts_last_us;   /* superseded by the tracked reads */

  if (!s_open) { return -1; }

  s_open = 0U;                              /* stop the producer first */

  /* Flush a partial block so the tail of the record is not lost. */
  if (s_fill > 0U)
  {
    uint8_t *b = blk(s_head);
    sdat_block_hdr_t *h = (sdat_block_hdr_t *)b;
    h->n_packets = (uint16_t)(s_fill / ICM_PACKET4_LEN);
    h->flags    |= SDAT_F_PARTIAL;
    memset(b + SDAT_BLKHDR_BYTES + s_fill, 0,           /* zero, then CRC */
           SDAT_BLOCK_BYTES - SDAT_BLKHDR_BYTES - s_fill);
    h->crc32     = record_crc32(b + SDAT_BLKHDR_BYTES,
                                (uint32_t)SDAT_MAX_PACKETS * ICM_PACKET4_LEN);
    s_fill = 0U;
    s_seq++;
    s_head++;
  }

  s_open = 1U;  (void)storage_task();  s_open = 0U;   /* drain */

  /* f_measured, in milli-Hz, from the board clock against the sample count.
     Two independent clocks: TIM2 here, and the sensor's own TMST inside every
     packet. Their disagreement is TN-16 section 10.1's sensor-oscillator
     figure, recoverable per record in analysis.

     Taken between the FIRST and LAST read triggers, not the caller's window --
     see the note in storage_advance(). The caller's ts_first_us/ts_last_us are
     kept as the run's wall-clock bounds, which is what they honestly are, but
     they are not a rate reference. */
  uint32_t f_milli = 0;
  if ((s_ts_last > s_ts_first) && (s_samples > s_first_pkts))
  {
    f_milli = (uint32_t)(((uint64_t)(s_samples - s_first_pkts) * 1000000000ULL)
                         / (s_ts_last - s_ts_first));
  }

  /* Integrity fields come from the sampler rather than being hard-coded to
     zero, which is what they were: a record could not previously distinguish
     a clean run from one that had been dropping transfers throughout. */
  sampler_stats_t sst; sampler_get_stats(&sst);

  /* ts_first_us/ts_last_us in the header are the first and last READ TRIGGERS,
     which is what the field names claim and what the reader needs to anchor
     the packet TMST counter. The caller's loop bounds are wall-clock overhead
     and would misrepresent the sampling window. */
  if (record_finalise_header(s_hdr, &s_cfg, s_runid, s_samples, n_gaps,
                             s_ts_first, s_ts_last, f_milli,
                             t_start_mc, t_end_mc,
                             s_st.blocks_written, sst.bus_busy,
                             sst.faults + sst.start_err, sst.overflows) >= 0)
  {
    if (f_lseek(&s_fil, 0) == FR_OK)
    {
      UINT bw = 0;
      (void)f_write(&s_fil, s_hdr, SDAT_HEADER_BYTES, &bw);
    }
  }

  (void)f_sync(&s_fil);
  FRESULT fr = f_close(&s_fil);
  arena_release(ARENA_OWNER);

  console_printf("storage: closed %s\r\n", s_path);
  console_printf("  %lu samples, %lu blocks, %lu dropped, %lu B\r\n",
                 (unsigned long)s_samples, (unsigned long)s_st.blocks_written,
                 (unsigned long)s_st.blocks_dropped,
                 (unsigned long)s_st.bytes_written);
  console_printf("  f_write max %lu us, mean %lu us | f_sync max %lu us "
                 "(%lu syncs) | ring peak %lu/%u\r\n",
                 (unsigned long)s_st.write_max_us,
                 (unsigned long)(s_st.blocks_written
                                 ? s_st.write_total_us / s_st.blocks_written : 0),
                 (unsigned long)s_st.sync_max_us, (unsigned long)s_st.syncs,
                 (unsigned long)s_st.ring_peak, RING_BLOCKS);
  console_printf("  f_measured %lu.%03lu Hz\r\n",
                 (unsigned long)(f_milli / 1000U),
                 (unsigned long)(f_milli % 1000U));

  return (fr == FR_OK) ? 0 : -1;
}

int  storage_is_open(void) { return (int)s_open; }
const char *storage_filename(void) { return s_path; }

void storage_get_stats(storage_stats_t *out)
{
  if (out != NULL) { *out = s_st; }
}

/* ==========================================================================
 * Console
 * ========================================================================== */

#include <stdlib.h>

static void cmd_mount(int argc, char **argv)
{
  (void)argc; (void)argv;
  if (storage_mount() != 0) { return; }

  DWORD fre_clust; FATFS *fsp;
  if (f_getfree(SDPath, &fre_clust, &fsp) == FR_OK)
  {
    console_printf("  free %lu MiB\r\n",
                   (unsigned long)(((uint32_t)fre_clust * fsp->csize) / 2048UL));
  }
  console_printf("  arena: %s\r\n",
                 arena_owner() ? arena_owner() : "free");
}

/* rec <label> <seconds> [odr] [slot]
 *
 * Blocks for the duration, calling storage_task() so blocks reach the card.
 * Nothing else needs the main loop during a record, and the sampler runs in
 * interrupt context regardless -- which is the whole point of the design. */
static void cmd_rec(int argc, char **argv)
{
  if (argc < 3)
  {
    console_printf("usage: rec <label> <seconds> [odr] [slot]\r\n");
    return;
  }

  const char *label = argv[1];
  long secs = strtol(argv[2], NULL, 10);
  long hz   = (argc >= 4) ? strtol(argv[3], NULL, 10) : 100;
  long sl   = (argc >= 5) ? strtol(argv[4], NULL, 10) : 1;

  if (secs < 1 || secs > 43200L || sl < 1 || sl > 4 ||
      icm_odr_code(hz) == 0xFFU)
  {
    console_printf("usage: rec <label> <1..43200 s> "
                   "[25|50|100|200|500|1000|8000] [1..4]\r\n");
    return;
  }

  bus_slot_t slot = (bus_slot_t)(sl - 1);
  if (icm_probe(slot) != 0) { return; }

  /* Thermal gate per ODR, TN-14 section 2.2 verbatim. Inactive at ODR >= 500
     because eta is phase-flat there. */
  uint32_t gate = 0;
  if      (hz <= 25)  { gate = 260; }
  else if (hz <= 50)  { gate = 361; }
  else if (hz <= 100) { gate = 388; }
  else if (hz <= 200) { gate = 389; }

  /* TMST resolution: 1 us wraps every 65.5 ms, and at ODR 25 a single dropped
     sample spans 80 ms, which makes the unwrap ambiguous. 16 us wraps at
     1.05 s. Recorded in the header either way. */
  uint8_t tmst_res = (hz >= 200) ? 1U : 16U;

  icm_config_t icfg = {
    .odr_code   = icm_odr_code(hz),
    .fs_sel     = 0U,
    .ui_filt_bw = 0U,
    .aaf        = ICM_AAF_DEFAULT,
    .hires      = 1U,
    .watermark  = sampler_watermark_for(hz),
  };

  if (icm_configure(slot, &icfg) != 0)
  {
    console_printf("rec: configure failed\r\n");
    return;
  }

  /* TMST_RES lives in bit 3; read-modify-write, because TMST_EN in bit 0 is
     already set by the reset value 0x23 and must stay set. */
  uint8_t tc = 0;
  (void)icm_read8(slot, ICM_TMST_CONFIG, &tc);
  tc = (uint8_t)((tmst_res == 1U) ? (tc & ~0x08U) : (tc | 0x08U));
  (void)icm_write8_verify(slot, ICM_TMST_CONFIG, tc);

  /* FIFO: hi-res, gyro + accel + temp. Accel is free -- DS section 6.4, the
     packet is 20 B whatever the enables say once HIRES is set. */
  (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_BYPASS);
  (void)icm_write8_verify(slot, ICM_FIFO_CONFIG1,
                          ICM_FIFO_HIRES_EN | ICM_FIFO_TEMP_EN
                          | ICM_FIFO_GYRO_EN | ICM_FIFO_ACCEL_EN);
  (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_STREAM);

  record_cfg_t rcfg = {
    .label = label, .slot = slot, .odr_hz = hz, .fsr_dps = 2000,
    .ui_filt_bw = 0U, .aaf_floor = 0U, .tmst_res_us = tmst_res,
    .watermark = icfg.watermark, .offset_user = 0,
    .gate_mk = gate, .on_battery = 0U,
    .usb_connected = (uint8_t)(console_cdc_ready() ? 1 : 0),
  };

  char runid[20];
  snprintf(runid, sizeof runid, "r%lu", (unsigned long)HAL_GetTick());

  if (storage_open(&rcfg, runid) != 0) { return; }
  if (sampler_start(slot, icfg.watermark, hz) != 0)
  {
    (void)storage_close(0, 0, 0, 0, 0);
    return;
  }

  console_printf("rec: %ld s at %ld Hz, watermark %u B, gate %lu mK\r\n",
                 secs, hz, icfg.watermark, (unsigned long)gate);

  uint64_t t0 = timebase_now_us();
  uint64_t end = t0 + (uint64_t)secs * 1000000ULL;
  uint32_t next_report = 10;

  while (timebase_now_us() < end)
  {
    if (storage_task() < 0) { break; }
    sampler_poll();                 /* revive a latched pulsed interrupt */

    uint32_t el = (uint32_t)((timebase_now_us() - t0) / 1000000ULL);
    if (el >= next_report)
    {
      next_report = el + 10U;
      sampler_stats_t ss; sampler_get_stats(&ss);
      console_printf("  %5lus %8lu samples  ring pk %lu  drop %lu  "
                     "wmax %lu us\r\n",
                     (unsigned long)el, (unsigned long)storage_sample_count(),
                     (unsigned long)s_st.ring_peak,
                     (unsigned long)(ss.ring_full + ss.bus_busy
                                     + ss.start_err + ss.faults),
                     (unsigned long)s_st.write_max_us);
    }
  }

  sampler_stop();
  (void)storage_task();

  uint64_t t1 = timebase_now_us();
  uint32_t gaps = sampler_lost_packets();

  sampler_stats_t ss; sampler_get_stats(&ss);
  console_printf("rec: irq %lu, reads %lu/%lu, ring-full %lu, busy %lu, "
                 "faults %lu, wdog %lu\r\n",
                 (unsigned long)ss.interrupts, (unsigned long)ss.reads_done,
                 (unsigned long)ss.reads_started, (unsigned long)ss.ring_full,
                 (unsigned long)ss.bus_busy, (unsigned long)ss.faults,
                 (unsigned long)ss.watchdog_kicks);
  console_printf("  chained drains %lu, start-err %lu, chain-stuck %lu\r\n",
                 (unsigned long)ss.chained, (unsigned long)ss.start_err,
                 (unsigned long)ss.chain_stuck);
  console_printf("  fifo peak %u B, overflows %lu\r\n",
                 (unsigned)ss.fifo_peak, (unsigned long)ss.overflows);
  uint32_t got      = storage_sample_count();
  uint32_t expected = (uint32_t)secs * (uint32_t)hz;

  console_printf("  gaps %lu packets (%lu%% of expected)\r\n",
                 (unsigned long)gaps,
                 (unsigned long)((gaps * 100UL)
                                 / ((expected != 0U) ? expected : 1U)));

  /* Yield check. The 28 July ODR 8000 run returned "0 dropped, gaps 0" while
     delivering 235733 of 480000 samples: the FIFO had been silently
     overwriting itself, so nothing the firmware counts as a drop had occurred.
     A record can only be trusted if the sample COUNT is right, so compare
     against the nominal rate directly and say so in the clear. The threshold
     is 2%, comfortably outside the ~1% oscillator offset measured in TN-16
     section 10.1 but far inside any real loss. */
  {
    if (expected != 0U)
    {
      if ((got + (expected / 50U)) < expected)
      {
        console_printf("rec: *** DATA LOSS: %lu of %lu samples (%lu%%). "
                       "RECORD NOT ADMISSIBLE ***\r\n",
                       (unsigned long)got, (unsigned long)expected,
                       (unsigned long)((got * 100UL) / expected));
      }
      else if (ss.overflows != 0U)
      {
        console_printf("rec: *** FIFO OVERFLOW x%lu: sample count is right "
                       "but continuity is not guaranteed ***\r\n",
                       (unsigned long)ss.overflows);
      }
      else
      {
        console_printf("rec: yield OK, %lu of %lu nominal\r\n",
                       (unsigned long)got, (unsigned long)expected);
      }
    }
  }

  /* n_gaps stays in packets. The overflow count is a different quantity with
     different units -- an unknown number of packets lost per event -- so
     storage_close() reads it from the sampler and writes it to the header as
     its own field. A reader must be able to reject a record from the file
     alone, without reference to the session log. */
  (void)storage_close(gaps, t0, t1, 0, 0);
}

static const console_cmd_t s_sto_cmds[] = {
  { "mount", "mount the SD card and report free space",           cmd_mount },
  { "rec",   "rec <label> <secs> [odr] [slot] - log a .sdat record", cmd_rec },
};

void storage_console_init(void)
{
  (void)console_register(s_sto_cmds,
                         (uint8_t)(sizeof s_sto_cmds / sizeof s_sto_cmds[0]));
}
