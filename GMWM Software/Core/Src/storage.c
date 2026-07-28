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
static storage_stats_t s_st;

static inline uint8_t *blk(uint32_t i) { return s_ring + (i % RING_BLOCKS) * SDAT_BLOCK_BYTES; }
static inline uint32_t ring_used(void) { return s_head - s_tail; }

/* ==========================================================================
 * Producer -- interrupt context
 * ========================================================================== */

uint8_t *storage_fill_ptr(uint16_t *space_bytes)
{
  if (!s_open) { return NULL; }

  /* Head must stay at least one block ahead of tail, otherwise the consumer
     would be reading the block the producer is filling. */
  if (ring_used() >= (RING_BLOCKS - 1U))
  {
    s_st.blocks_dropped++;
    return NULL;
  }

  uint16_t used = s_fill;
  *space_bytes = (uint16_t)(SDAT_MAX_PACKETS * ICM_PACKET4_LEN - used);
  return blk(s_head) + SDAT_BLKHDR_BYTES + used;
}

void storage_advance(uint16_t bytes, uint64_t t_us, uint16_t fifo_bytes,
                     uint16_t flags)
{
  if (!s_open || bytes == 0U) { return; }

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
    if (s_ts_first == 0U) { s_ts_first = t_us; }
  }

  h->flags     |= flags;
  h->fifo_bytes = fifo_bytes;

  s_fill    = (uint16_t)(s_fill + bytes);
  s_samples += (uint32_t)(bytes / ICM_PACKET4_LEN);

  if (s_fill >= (SDAT_MAX_PACKETS * ICM_PACKET4_LEN))
  {
    h->n_packets = (uint16_t)(s_fill / ICM_PACKET4_LEN);
    h->crc32     = record_crc32(b + SDAT_BLKHDR_BYTES,
                                (uint32_t)SDAT_MAX_PACKETS * ICM_PACKET4_LEN);
    /* Zero the tail padding so the file is deterministic and compresses. */
    memset(b + SDAT_BLKHDR_BYTES + s_fill, 0,
           SDAT_BLOCK_BYTES - SDAT_BLKHDR_BYTES - s_fill);
    s_fill = 0U;
    s_seq++;
    s_head++;                              /* publish last */
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
  static uint8_t hdr[SDAT_HEADER_BYTES];
  if (record_build_header(hdr, cfg, s_runid) < 0)
  {
    f_close(&s_fil);
    arena_release(ARENA_OWNER);
    return -1;
  }

  UINT bw = 0;
  fr = f_write(&s_fil, hdr, SDAT_HEADER_BYTES, &bw);
  if (fr != FR_OK || bw != SDAT_HEADER_BYTES)
  {
    console_printf("storage: header write -> %d\r\n", fr);
    f_close(&s_fil);
    arena_release(ARENA_OWNER);
    return -1;
  }

  s_head = s_tail = s_fill = s_seq = s_samples = 0;
  s_ts_first = 0;
  memset(&s_st, 0, sizeof s_st);
  s_last_sync_ms = HAL_GetTick();
  s_open = 1U;                              /* arms the producer, last */

  console_printf("storage: recording to %s\r\n", s_path);
  return 0;
}

int storage_close(uint32_t n_gaps, uint64_t ts_first_us, uint64_t ts_last_us,
                  int32_t t_start_mc, int32_t t_end_mc)
{
  if (!s_open) { return -1; }

  s_open = 0U;                              /* stop the producer first */

  /* Flush a partial block so the tail of the record is not lost. */
  if (s_fill > 0U)
  {
    uint8_t *b = blk(s_head);
    sdat_block_hdr_t *h = (sdat_block_hdr_t *)b;
    h->n_packets = (uint16_t)(s_fill / ICM_PACKET4_LEN);
    h->flags    |= SDAT_F_PARTIAL;
    h->crc32     = record_crc32(b + SDAT_BLKHDR_BYTES,
                                (uint32_t)SDAT_MAX_PACKETS * ICM_PACKET4_LEN);
    memset(b + SDAT_BLKHDR_BYTES + s_fill, 0,
           SDAT_BLOCK_BYTES - SDAT_BLKHDR_BYTES - s_fill);
    s_fill = 0U;
    s_seq++;
    s_head++;
  }

  s_open = 1U;  (void)storage_task();  s_open = 0U;   /* drain */

  /* f_measured, in milli-Hz, from the board clock against the sample count.
     Two independent clocks: TIM2 here, and the sensor's own TMST inside every
     packet. Their disagreement is TN-16 section 10.1's sensor-oscillator
     figure, recoverable per record in analysis. */
  uint32_t f_milli = 0;
  if (ts_last_us > ts_first_us && s_samples > 1U)
  {
    f_milli = (uint32_t)(((uint64_t)(s_samples - 1U) * 1000000000ULL)
                         / (ts_last_us - ts_first_us));
  }

  static uint8_t hdr[SDAT_HEADER_BYTES];
  if (record_finalise_header(hdr, &s_cfg, s_runid, s_samples, n_gaps,
                             ts_first_us, ts_last_us, f_milli,
                             t_start_mc, t_end_mc,
                             s_st.blocks_written, 0, 0) >= 0)
  {
    if (f_lseek(&s_fil, 0) == FR_OK)
    {
      UINT bw = 0;
      (void)f_write(&s_fil, hdr, SDAT_HEADER_BYTES, &bw);
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
