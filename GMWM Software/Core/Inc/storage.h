/**
  ******************************************************************************
  * @file    storage.h
  * @brief   Ring buffer and SD writer for .sdat records.
  *
  * PRODUCER / CONSUMER
  *   The FIFO sampler runs in interrupt context: it claims a block, has DMA
  *   fill it, and commits it. The main loop consumes committed blocks and
  *   writes them to the card. They must be decoupled, because an SD write
  *   stalls for "tens to hundreds of ms" (TN-16 section 6.4) while the ICM
  *   FIFO holds only 2 KiB -- 12.8 ms at ODR 8000. A polled design cannot
  *   drain the FIFO during a write and would lose samples at the top of the
  *   ODR axis.
  *
  * RING SIZING
  *   The ring lives in the shared arena: 128 KiB / 4 KiB = 32 blocks. At
  *   ODR 8000 one block is 200 packets = 25 ms, so the ring absorbs 800 ms of
  *   stall. TN-16 open item 7 asks for the worst-case single-write latency to
  *   size exactly this; storage_stats() measures it, so the number that sizes
  *   the buffer comes from the buffer's own instrumentation.
  *
  * WHAT IS AND IS NOT PROTECTED
  *   f_sync every SHEPPARD_SD_SYNC_MS bounds how much of an interrupted
  *   record is recoverable. It does not make a truncated record scientifically
  *   usable -- R2's thermal gate and the uniform-sampling assumption behind
  *   Allan variance both fail on a partial capture. Its value is diagnostic:
  *   block sequence numbers and timestamps say when and why a run died.
  ******************************************************************************
  */

#ifndef STORAGE_H
#define STORAGE_H

#include <stdint.h>
#include "record.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  uint32_t blocks_written;
  uint32_t blocks_dropped;      /* ring full: the sampler outran the writer  */
  uint32_t bytes_written;
  uint32_t write_max_us;        /* worst single f_write -- TN-16 open item 7 */
  uint32_t write_last_us;
  uint64_t write_total_us;
  uint32_t sync_max_us;         /* worst f_sync, measured separately         */
  uint32_t syncs;
  uint32_t ring_peak;           /* deepest the ring ever got, in blocks      */
} storage_stats_t;

/** Mount the card. Safe to call repeatedly. */
int storage_mount(void);
int storage_unmount(void);

/**
  * @brief  Open a record. Claims the arena, writes the 4 KiB header, and arms
  *         the ring. Fails if the arena is held (i.e. a firmware update is in
  *         progress) or a record is already open.
  * @param  run_id  short identifier shared by every record in a run
  */
int storage_open(const record_cfg_t *cfg, const char *run_id);

/**
  * @brief  Main-loop step. Writes any committed blocks and services the sync
  *         timer. Call every iteration while a record is open.
  * @retval number of blocks written this call, or negative on error.
  */
int storage_task(void);

/**
  * @brief  Flush, rewrite the header with the final timing and integrity
  *         fields, close, and release the arena.
  */
int storage_close(uint32_t n_gaps, uint64_t ts_first_us, uint64_t ts_last_us,
                  int32_t t_start_mc, int32_t t_end_mc);

int  storage_is_open(void);
void storage_get_stats(storage_stats_t *out);
const char *storage_filename(void);

/* ---- producer side, called from interrupt context ----------------------- */

/**
  * @brief  Claim the block currently being filled, and tell the caller how
  *         much room is left in its payload.
  * @retval pointer to the next free byte of payload, or NULL if the ring is
  *         full (which increments blocks_dropped and is recorded as a gap).
  */
uint8_t *storage_fill_ptr(uint16_t *space_bytes);

/**
  * @brief  Advance the current block by `bytes` of payload just written.
  *         Commits and rotates the block when it is full. ISR-safe.
  * @param  t_us        TIM2 at the read that produced these bytes
  * @param  fifo_bytes  FIFO occupancy at that read, for headroom telemetry
  * @param  flags       SDAT_F_* to OR into the block
  */
void storage_advance(uint16_t bytes, uint64_t t_us, uint16_t fifo_bytes,
                     uint16_t flags);

/** Samples committed so far this record. */
uint32_t storage_sample_count(void);

/** Register the `sd`, `rec` and `sdbench` console commands. */
void storage_console_init(void);

#ifdef __cplusplus
}
#endif

#endif /* STORAGE_H */
