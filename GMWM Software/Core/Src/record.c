/**
  ******************************************************************************
  * @file    record.c
  * @brief   The .sdat on-disk format.
  ******************************************************************************
  */

#include "record.h"
#include "sheppard_config.h"
#include "imu_icm42688.h"
#include "console.h"

#include <stdio.h>
#include <string.h>
#include "main.h"

extern RTC_HandleTypeDef hrtc;

/* ==========================================================================
 * CRC-32, zlib / IEEE 802.3: reflected, poly 0xEDB88320, init and final XOR
 * 0xFFFFFFFF. Chosen so the host reader is one call to zlib.crc32 -- and
 * deliberately NOT the STM32 hardware CRC unit, which computes the
 * non-reflected MPEG-2 variant and would not match.
 * ========================================================================== */

static const uint32_t s_crc_nib[16] = {
  0x00000000UL, 0x1DB71064UL, 0x3B6E20C8UL, 0x26D930ACUL,
  0x76DC4190UL, 0x6B6B51F4UL, 0x4DB26158UL, 0x5005713CUL,
  0xEDB88320UL, 0xF00F9344UL, 0xD6D6A3E8UL, 0xCB61B38CUL,
  0x9B64C2B0UL, 0x86D3D2D4UL, 0xA00AE278UL, 0xBDBDF21CUL
};

uint32_t record_crc32(const uint8_t *p, uint32_t n)
{
  uint32_t crc = 0xFFFFFFFFUL;
  while (n--)
  {
    crc ^= *p++;
    crc = (crc >> 4) ^ s_crc_nib[crc & 0x0FU];
    crc = (crc >> 4) ^ s_crc_nib[crc & 0x0FU];
  }
  return ~crc;
}

/* ==========================================================================
 * Register read-back
 *
 * The header records what the sensor ACTUALLY has, read back after
 * configuration, not what we intended to write. TN-16 section 5.4 asks for
 * the AAF triple and GYRO_ACCEL_CONFIG0 in every header; this generalises it.
 * ========================================================================== */

typedef struct {
  uint8_t pwr, gyro_cfg0, gyro_accel_cfg0, gyro_cfg1;
  uint8_t fifo_cfg, fifo_cfg1, fifo_wm_l, fifo_wm_h;
  uint8_t intf_cfg0, int_src0, tmst_cfg;
  uint8_t aaf_delt, aaf_dsq_l, aaf_dsq_h_bs;   /* bank 1 */
} readback_t;

static void read_all(bus_slot_t slot, readback_t *r)
{
  memset(r, 0, sizeof *r);
  (void)icm_read8(slot, ICM_PWR_MGMT0,          &r->pwr);
  (void)icm_read8(slot, ICM_GYRO_CONFIG0,       &r->gyro_cfg0);
  (void)icm_read8(slot, ICM_GYRO_ACCEL_CONFIG0, &r->gyro_accel_cfg0);
  (void)icm_read8(slot, ICM_GYRO_CONFIG1,       &r->gyro_cfg1);
  (void)icm_read8(slot, ICM_FIFO_CONFIG,        &r->fifo_cfg);
  (void)icm_read8(slot, ICM_FIFO_CONFIG1,       &r->fifo_cfg1);
  (void)icm_read8(slot, ICM_FIFO_CONFIG2,       &r->fifo_wm_l);
  (void)icm_read8(slot, ICM_FIFO_CONFIG3,       &r->fifo_wm_h);
  (void)icm_read8(slot, ICM_INTF_CONFIG0,       &r->intf_cfg0);
  (void)icm_read8(slot, ICM_INT_SOURCE0,        &r->int_src0);
  (void)icm_read8(slot, ICM_TMST_CONFIG,        &r->tmst_cfg);

  (void)icm_write8(slot, ICM_REG_BANK_SEL, 1U);
  (void)icm_read8(slot, ICM_GYRO_CFG_STATIC3, &r->aaf_delt);
  (void)icm_read8(slot, ICM_GYRO_CFG_STATIC4, &r->aaf_dsq_l);
  (void)icm_read8(slot, ICM_GYRO_CFG_STATIC5, &r->aaf_dsq_h_bs);
  (void)icm_write8(slot, ICM_REG_BANK_SEL, 0U);   /* MUST return to bank 0 */
}

/* ==========================================================================
 * Header
 * ========================================================================== */

static int rtc_iso(char *buf, size_t n)
{
  RTC_TimeTypeDef t; RTC_DateTypeDef d;
  if (HAL_RTC_GetTime(&hrtc, &t, RTC_FORMAT_BIN) != HAL_OK) { return -1; }
  /* GetDate after GetTime is not optional -- the F7 RTC locks its shadow
     registers until the date is read (TN-16 section 8.3). */
  if (HAL_RTC_GetDate(&hrtc, &d, RTC_FORMAT_BIN) != HAL_OK) { return -1; }
  return snprintf(buf, n, "20%02u-%02u-%02uT%02u:%02u:%02u",
                  d.Year, d.Month, d.Date, t.Hours, t.Minutes, t.Seconds);
}

/* nano.specs printf has no %llu (TN-16 section 6.2), and a timestamp in
   microseconds exceeds 32 bits after 71 minutes -- which every long
   bias-instability record does. Format it by hand and emit with %s. */
static const char *u64dec(uint64_t v, char *buf, size_t n)
{
  char tmp[24];
  int  i = 0;
  if (v == 0U) { tmp[i++] = '0'; }
  while (v > 0U && i < (int)sizeof tmp) { tmp[i++] = (char)('0' + (v % 10U)); v /= 10U; }
  int j = 0;
  while (i > 0 && j < (int)n - 1) { buf[j++] = tmp[--i]; }
  buf[j] = '\0';
  return buf;
}

static uint32_t board_uid_word(int i)
{
  const uint32_t *uid = (const uint32_t *)UID_BASE;   /* 96-bit device ID */
  return uid[i];
}

/* Common body, used for both the initial write and the finalising rewrite.
   Keeping one generator means the two can never disagree about field names. */
static int build(uint8_t *dst, const record_cfg_t *c, const char *run_id,
                 int final,
                 uint32_t n_samples, uint32_t n_gaps,
                 uint64_t ts_first, uint64_t ts_last,
                 uint32_t f_milli, int32_t t0_mc, int32_t t1_mc,
                 uint32_t blocks, uint32_t overruns, uint32_t faults)
{
  readback_t rb;
  read_all(c->slot, &rb);

  char when[32] = "unset";
  (void)rtc_iso(when, sizeof when);

  char *p = (char *)dst;
  int   n = 0;
  const int cap = (int)SDAT_HEADER_BYTES;
  char tsbuf_a[24], tsbuf_b[24];

  n += snprintf(p + n, (size_t)(cap - n),
    "{\n"
    "\"format\":\"sdat/%u\",\"magic\":\"SDAT\",\n"
    "\"run_id\":\"%s\",\"label\":\"%s\",\"rtc_start\":\"%s\",\n"
    "\"board\":{\"uid\":\"%08lX%08lX%08lX\",\"mcu\":\"STM32F723ZET6\"},\n"
    "\"fw\":{\"name\":\"%s\",\"version\":\"%s\",\"tag\":\"%s\","
      "\"built\":\"%s %s\",\"opt\":\"-O0\"},\n"
    "\"clock\":{\"sysclk_hz\":%lu,\"hse\":\"24MHz bypass\","
      "\"tim2_hz\":1000000},\n",
    SDAT_FORMAT_VERSION, run_id, c->label ? c->label : "", when,
    (unsigned long)board_uid_word(0), (unsigned long)board_uid_word(1),
    (unsigned long)board_uid_word(2),
    SHEPPARD_FW_NAME, SHEPPARD_FW_VERSION_STR, SHEPPARD_BUILD_TAG,
    __DATE__, __TIME__,
    (unsigned long)HAL_RCC_GetSysClockFreq());

  n += snprintf(p + n, (size_t)(cap - n),
    "\"sensor\":{\"part\":\"ICM-42688-P\",\"slot\":%d,"
      "\"gyro_lsb_per_dps\":16.4,\"hires_lsb_per_dps\":131.0,"
      "\"delta_mdps\":61.035},\n"
    "\"config\":{\"odr_nominal_hz\":%ld,\"fsr_dps\":%u,\"word_bits\":20,"
      "\"ui_filt_bw\":%u,\"aaf\":\"%s\",\"tmst_res_us\":%u,"
      "\"fifo_watermark_bytes\":%u,\"offset_user_steps\":%d},\n",
    (int)c->slot + 1, c->odr_hz, c->fsr_dps, c->ui_filt_bw,
    c->aaf_floor ? "42Hz_floor" : "585Hz_default",
    c->tmst_res_us, c->watermark, c->offset_user);

  /* Read-back, not intent. */
  n += snprintf(p + n, (size_t)(cap - n),
    "\"registers_readback\":{"
      "\"PWR_MGMT0_4E\":\"0x%02X\",\"GYRO_CONFIG0_4F\":\"0x%02X\","
      "\"GYRO_ACCEL_CONFIG0_52\":\"0x%02X\",\"GYRO_CONFIG1_51\":\"0x%02X\","
      "\"FIFO_CONFIG_16\":\"0x%02X\",\"FIFO_CONFIG1_5F\":\"0x%02X\","
      "\"FIFO_WM\":%u,\"INTF_CONFIG0_4C\":\"0x%02X\","
      "\"INT_SOURCE0_65\":\"0x%02X\",\"TMST_CONFIG_54\":\"0x%02X\","
      "\"B1_GYRO_AAF_DELT\":%u,\"B1_AAF_DELTSQR\":%u,\"B1_AAF_BITSHIFT\":%u},\n",
    rb.pwr, rb.gyro_cfg0, rb.gyro_accel_cfg0, rb.gyro_cfg1,
    rb.fifo_cfg, rb.fifo_cfg1,
    (unsigned)(((unsigned)(rb.fifo_wm_h & 0x0FU) << 8) | rb.fifo_wm_l),
    rb.intf_cfg0, rb.int_src0, rb.tmst_cfg,
    (unsigned)(rb.aaf_delt & 0x3FU),
    (unsigned)(((unsigned)(rb.aaf_dsq_h_bs & 0x0FU) << 8) | rb.aaf_dsq_l),
    (unsigned)(rb.aaf_dsq_h_bs >> 4));

  n += snprintf(p + n, (size_t)(cap - n),
    "\"layout\":{\"header_bytes\":%u,\"block_bytes\":%u,"
      "\"block_header_bytes\":%u,\"packet_bytes\":%u,"
      "\"max_packets_per_block\":%u,\"endian\":\"little\","
      "\"packet\":\"ICM-42688-P FIFO Packet 4, verbatim, "
      "DS-000347 Rev1.6 6.1\"},\n"
    "\"power\":{\"battery\":%u,\"usb_connected\":%u},\n"
    "\"gate\":{\"thermal_mk\":%lu,\"rule\":\"TN-14 R2\"},\n",
    SDAT_HEADER_BYTES, SDAT_BLOCK_BYTES, SDAT_BLKHDR_BYTES,
    ICM_PACKET4_LEN, SDAT_MAX_PACKETS,
    c->on_battery, c->usb_connected, (unsigned long)c->gate_mk);

  /* Mutable block. Written as nulls up front so the file is valid even if
     power is lost mid-record, then rewritten at close. TN-16 section 10.5. */
  if (final)
  {
    n += snprintf(p + n, (size_t)(cap - n),
      "\"timing\":{\"n_samples\":%lu,\"n_gaps\":%lu,"
        "\"ts_first_us\":%s,\"ts_last_us\":%s,"
        "\"f_measured_mhz\":%lu,\"f_measure_method\":\"tim2_vs_sample_count\"},\n"
      "\"thermal\":{\"t_start_mc\":%ld,\"t_end_mc\":%ld,\"drift_mk\":%ld},\n"
      "\"integrity\":{\"blocks\":%lu,\"bus_overruns\":%lu,\"bus_faults\":%lu,"
        "\"closed\":true}\n}\n",
      (unsigned long)n_samples, (unsigned long)n_gaps,
      u64dec(ts_first, tsbuf_a, sizeof tsbuf_a),
      u64dec(ts_last,  tsbuf_b, sizeof tsbuf_b),
      (unsigned long)f_milli, (long)t0_mc, (long)t1_mc,
      (long)(t1_mc - t0_mc),
      (unsigned long)blocks, (unsigned long)overruns, (unsigned long)faults);
  }
  else
  {
    n += snprintf(p + n, (size_t)(cap - n),
      "\"timing\":{\"n_samples\":null,\"n_gaps\":null,"
        "\"ts_first_us\":null,\"ts_last_us\":null,"
        "\"f_measured_mhz\":null,\"f_measure_method\":\"tim2_vs_sample_count\"},\n"
      "\"thermal\":{\"t_start_mc\":null,\"t_end_mc\":null,\"drift_mk\":null},\n"
      "\"integrity\":{\"blocks\":null,\"bus_overruns\":null,\"bus_faults\":null,"
        "\"closed\":false}\n}\n");
  }

  if (n < 0 || n >= cap)
  {
    console_printf("record: header overflowed %u bytes (%d)\r\n",
                   SDAT_HEADER_BYTES, n);
    return -1;
  }

  /* Space-pad to the full 4 KiB so the first data block starts on a
     4 KiB boundary. */
  memset(p + n, ' ', (size_t)(cap - n));
  return n;
}

int record_build_header(uint8_t *dst, const record_cfg_t *cfg,
                        const char *run_id)
{
  return build(dst, cfg, run_id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
}

int record_finalise_header(uint8_t *dst, const record_cfg_t *cfg,
                           const char *run_id,
                           uint32_t n_samples, uint32_t n_gaps,
                           uint64_t ts_first_us, uint64_t ts_last_us,
                           uint32_t f_measured_milli,
                           int32_t t_start_mc, int32_t t_end_mc,
                           uint32_t blocks, uint32_t overruns, uint32_t faults)
{
  return build(dst, cfg, run_id, 1, n_samples, n_gaps, ts_first_us,
               ts_last_us, f_measured_milli, t_start_mc, t_end_mc,
               blocks, overruns, faults);
}
