/**
  ******************************************************************************
  * @file    record.h
  * @brief   The .sdat on-disk format.
  *
  * LAYOUT
  *   offset 0        4096 B   UTF-8 JSON header, space-padded
  *   offset 4096     N x 4096 fixed 4 KiB blocks
  *
  *   Every block:  32 B block header + up to 200 raw FIFO packets + padding
  *
  * WHY 4 KiB BLOCKS
  *   SD writes are 512 B sectors inside 128 KiB clusters here. Writing whole
  *   4 KiB units on 4 KiB boundaries avoids a read-modify-write on every
  *   write, which is the difference between the 544-570 KiB/s measured in
  *   TN-16 section 6.3 and something much worse. The header is padded to 4 KiB
  *   for the same reason -- it puts the first data block on a boundary.
  *
  * WHY THE PACKET IS STORED VERBATIM
  *   TN-06 v1.2 calls raw integer codes "the single most important firmware
  *   constraint in the project". Storing the vendor's own 20-byte packet
  *   byte-for-byte is the strongest form of that: no scaling, no repacking,
  *   nothing to get wrong, and a reviewer can re-derive every published number
  *   from the instrument's own output.
  *
  *   Accel comes free. DS section 6.4: with FIFO_HIRES_EN = 1 the packet is
  *   20 bytes regardless of the accel and gyro enables, so disabling accel
  *   would save nothing and would discard the bench-motion witness that
  *   TN-14 section 4.1 needs in order to verify rather than assume the
  *   in-band disturbance budget.
  *
  * TIMING, TWO INDEPENDENT CLOCKS
  *   Each packet carries the sensor's own 16-bit TMST at bytes 0x0F/0x10 --
  *   stamped at the sample instant, so free of the FIFO queue lag that
  *   corrupted the 8 kHz V0.4 comparison. Each block header carries a 64-bit
  *   TIM2 value from the board. Their ratio is the sensor oscillator against
  *   the board oscillator, which is TN-16 section 10.1's +1.10%/+1.50%
  *   measurement made per record instead of once.
  *
  *   TMST_RES is set per ODR and recorded in the header: 1 us above 200 Hz,
  *   16 us at or below 100 Hz. At 1 us the field wraps every 65.5 ms, and at
  *   ODR 25 a single dropped sample spans 80 ms, which would make the unwrap
  *   ambiguous. 16 us wraps at 1.05 s, giving 26 samples of margin.
  ******************************************************************************
  */

#ifndef RECORD_H
#define RECORD_H

#include <stdint.h>
#include "imu_icm42688.h"

#ifdef __cplusplus
extern "C" {
#endif

#define SDAT_MAGIC          0x54414453UL   /* 'SDAT' little-endian */
#define SDAT_BLOCK_MAGIC    0x4B4C4253UL   /* 'SBLK'               */
#define SDAT_FORMAT_VERSION 1U

#define SDAT_HEADER_BYTES   4096U
#define SDAT_BLOCK_BYTES    4096U
#define SDAT_BLKHDR_BYTES   32U
#define SDAT_MAX_PACKETS    200U           /* 200 x 20 = 4000 B payload */

/* Block flags */
#define SDAT_F_FIFO_OVERFLOW  (1U << 0)   /* FIFO was near full when read     */
#define SDAT_F_RING_OVERFLOW  (1U << 1)   /* sampler outran the SD writer     */
#define SDAT_F_BUS_FAULT      (1U << 2)   /* an SPI/DMA error in this block   */
#define SDAT_F_PARTIAL        (1U << 3)   /* fewer than SDAT_MAX_PACKETS      */
#define SDAT_F_THERMAL_GATE   (1U << 4)   /* R2 gate exceeded during block    */

/* 32 bytes, packed, little-endian -- the host reader assumes both. */
typedef struct __attribute__((packed)) {
  uint32_t magic;        /* SDAT_BLOCK_MAGIC; lets a reader resync on a
                            truncated or corrupted file rather than give up  */
  uint32_t seq;          /* 0-based. A gap here is a lost block, full stop.  */
  uint64_t t_us;         /* TIM2 at the read that produced this block        */
  uint16_t n_packets;
  uint16_t fifo_bytes;   /* FIFO occupancy seen at that read -- the headroom
                            telemetry that says whether we are keeping up    */
  uint16_t flags;
  uint16_t temp_raw;     /* first packet's 16-bit die temperature, for the
                            R2 thermal gate without decoding the payload     */
  uint16_t overruns;     /* cumulative, saturating                           */
  uint16_t faults;
  uint32_t crc32;        /* over the payload only, zlib/IEEE polynomial      */
} sdat_block_hdr_t;

typedef struct {
  const char *label;         /* run-step label, e.g. "odr25"                 */
  bus_slot_t  slot;
  long        odr_hz;
  uint16_t    fsr_dps;
  uint8_t     ui_filt_bw;
  uint8_t     aaf_floor;     /* 1 = 42 Hz, 0 = 585 Hz default                */
  uint8_t     tmst_res_us;   /* 1 or 16                                      */
  uint16_t    watermark;     /* FIFO watermark in bytes (rule R8)            */
  int16_t     offset_user;   /* OFFSET_USER steps applied (rule Z.4)         */
  uint32_t    gate_mk;       /* R2 thermal gate for this ODR, 0 = inactive   */
  uint8_t     on_battery;
  uint8_t     usb_connected;
} record_cfg_t;

/**
  * @brief  Build the 4 KiB JSON header. Fills `dst` completely, space-padded.
  *         Register values are READ BACK from the sensor, not taken from the
  *         config -- TN-16 section 5.4 asks for exactly this, and a write that
  *         silently failed is otherwise invisible in the archive.
  * @retval bytes of JSON written (before padding), or -1.
  */
int record_build_header(uint8_t *dst, const record_cfg_t *cfg,
                        const char *run_id);

/**
  * @brief  Rewrite the header's mutable fields at record close: f_measured,
  *         sample and gap counts, first/last timestamps, thermal summary.
  *         TN-16 section 10.5 lists these; the gap count is the one it calls
  *         "the field you will wish you had recorded".
  */
int record_finalise_header(uint8_t *dst, const record_cfg_t *cfg,
                           const char *run_id,
                           uint32_t n_samples, uint32_t n_gaps,
                           uint64_t ts_first_us, uint64_t ts_last_us,
                           uint32_t f_measured_milli,
                           int32_t t_start_mc, int32_t t_end_mc,
                           uint32_t blocks, uint32_t overruns, uint32_t faults);

/** zlib/IEEE CRC-32. Shared so the host reader and the firmware agree. */
uint32_t record_crc32(const uint8_t *p, uint32_t n);

#ifdef __cplusplus
}
#endif

#endif /* RECORD_H */
