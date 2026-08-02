/**
  ******************************************************************************
  * @file    imu_icm42688.c
  * @brief   ICM-42688-P driver: configuration, 16-bit registers, hi-res FIFO.
  ******************************************************************************
  */

#include "imu_icm42688.h"
#include "bus.h"
#include "console.h"
#include "timebase.h"
#include "sheppard_config.h"

#include <stdlib.h>
#include <string.h>

#include "main.h"

/* AAF values now live in imu_icm42688.h, sourced from the DS Rev 1.6
   section 5.3 bandwidth table. TN-16 open item 1 is closed: 1/1/15 does give
   42 Hz. TN-16 section 5.1's "default ~258 Hz" is wrong; it is 585 Hz. */

/* Scratch for register transfers. .bss, hence SRAM1, hence DMA-reachable. */
static uint8_t s_tx[8];
static uint8_t s_rx[8];

/* ==========================================================================
 * Primitive register access
 *
 * ICM SPI convention (TN-16 section 4.1): read = reg|0x80 then one dummy byte
 * clocks the data out; write = reg&0x7F then the value. Same protocol as the
 * ISM330DHCX, different from the BMI323, which is why all three live in
 * separate drivers.
 * ========================================================================== */

int icm_read8(bus_slot_t slot, uint8_t reg, uint8_t *val)
{
  s_tx[0] = (uint8_t)(reg | 0x80U);
  s_tx[1] = 0x00U;

  int rc = bus_xfer(slot, s_tx, s_rx, 2U, 50U);
  if (rc != BUS_OK)
  {
    return rc;
  }
  *val = s_rx[1];
  return BUS_OK;
}

int icm_write8(bus_slot_t slot, uint8_t reg, uint8_t val)
{
  s_tx[0] = (uint8_t)(reg & 0x7FU);
  s_tx[1] = val;
  return bus_xfer(slot, s_tx, NULL, 2U, 50U);
}

int icm_write8_verify(bus_slot_t slot, uint8_t reg, uint8_t val)
{
  if (icm_write8(slot, reg, val) != BUS_OK)
  {
    console_printf("icm%d: write 0x%02X failed\r\n", (int)slot + 1, reg);
    return -1;
  }

  uint8_t got = 0U;
  if (icm_read8(slot, reg, &got) != BUS_OK)
  {
    console_printf("icm%d: readback 0x%02X failed\r\n", (int)slot + 1, reg);
    return -1;
  }

  if (got != val)
  {
    console_printf("icm%d: 0x%02X wrote 0x%02X read 0x%02X\r\n",
                   (int)slot + 1, reg, val, got);
    return -1;
  }
  return 0;
}

static int icm_bank(bus_slot_t slot, uint8_t bank)
{
  return icm_write8(slot, ICM_REG_BANK_SEL, (uint8_t)(bank & 0x07U));
}

/* ==========================================================================
 * OFFSET_USER -- the digital phase ladder (TN-13 section 4.3)
 * ========================================================================== */

static int icm_rmw(bus_slot_t slot, uint8_t reg, uint8_t mask, uint8_t val);

/* REMOVED 30 July 2026. This computed a step count for a REQUESTED phase, on
   the premise that one OFFSET_USER step is 0.512 = 64/125 of a 16-bit LSB.
   That premise is wrong: TN-21 measured 0.4995 and excluded 0.512 at 338
   sigma. Anything calling it got a phase it had not asked for.

   It is deleted rather than corrected, because with the measured step size the
   whole idea is unsound and not merely mis-parameterised:

     - s is within 0.1% of one half, so the inverse-mod-125 construction has no
       analogue. Even step counts land near phase 0 and odd ones near 0.5; the
       sweep comes from the MISS from one half, eps = s - 1/2, precessing by
       eps per step.
     - eps is known to about 4%, and to 15% at the time the ladder was
       designed, so a k solved for a target phase carries that error straight
       into the design. sigma_phi = k * SE(s) reaches 0.13 Delta by k = 1800.
     - eps is ODR-DEPENDENT (TN-24 section 6, 15 sigma), so there is no single
       k-to-phase map to invert in the first place.
     - and it is unnecessary. The register's job is to MOVE the phase, not to
       place it: eta is always evaluated at the phi MEASURED from that record.
       Plans therefore step uniformly in k, which a wrong eps can stretch or
       compress but cannot cluster.

   Use explicit step counts in plan files. See plan_phase.txt and
   plan_night3.txt, whose headers carry the same argument. */

int icm_set_gyro_offset(bus_slot_t slot, int16_t steps)
{
  if ((steps > 2047) || (steps < -2048)) { return -1; }

  uint16_t v = (uint16_t)((uint16_t)steps & 0x0FFFU);   /* 12-bit two's cpl */
  uint8_t lo = (uint8_t)(v & 0xFFU);
  uint8_t hi = (uint8_t)((v >> 8) & 0x0FU);

  if (icm_bank(slot, 4U) != 0) { return -1; }

  int rc = 0;
  /* X low, then the shared nibble register carrying X[11:8] and Y[11:8],
     then Y low, Z low, and finally Z[11:8] in the low nibble of USER4 --
     whose high nibble belongs to ACCEL_X and must not be disturbed. */
  rc |= icm_write8_verify(slot, ICM_OFFSET_USER0, lo);
  rc |= icm_write8_verify(slot, ICM_OFFSET_USER1,
                          (uint8_t)((hi << 4) | hi));
  rc |= icm_write8_verify(slot, ICM_OFFSET_USER2, lo);
  rc |= icm_write8_verify(slot, ICM_OFFSET_USER3, lo);
  rc |= icm_rmw(slot, ICM_OFFSET_USER4, 0x0FU, hi);

  (void)icm_bank(slot, 0U);
  return (rc == 0) ? 0 : -1;
}

/* Read-modify-write. Several fields in 0x51/0x53 carry required non-zero
   values, so a blind full-register write clobbers them (TN-16 section 5.3). */
static int icm_rmw(bus_slot_t slot, uint8_t reg, uint8_t mask, uint8_t val)
{
  uint8_t v = 0U;
  if (icm_read8(slot, reg, &v) != BUS_OK)
  {
    return -1;
  }
  return icm_write8(slot, reg, (uint8_t)((v & (uint8_t)~mask) | (val & mask)));
}

/* ==========================================================================
 * Identification and reset
 * ========================================================================== */

int icm_probe(bus_slot_t slot)
{
  uint8_t id = 0U;
  if (icm_read8(slot, ICM_WHO_AM_I, &id) != BUS_OK)
  {
    return -1;
  }

  /* A constant 0x00 or 0xFF across the whole address space is a chip-select
     fault, not a sensor fault -- TN-16 section 1.2, the highest-cost error of
     that session. Worth naming here so the next person does not repeat it. */
  if (id != ICM_WHO_AM_I_VALUE)
  {
    console_printf("icm%d: WHO_AM_I 0x%02X, expected 0x47%s\r\n",
                   (int)slot + 1, id,
                   (id == 0x00U || id == 0xFFU)
                     ? "  (constant value = check the bus/CS pairing)" : "");
    return -1;
  }
  return 0;
}

int icm_soft_reset(bus_slot_t slot)
{
  if (icm_write8(slot, ICM_DEVICE_CONFIG, 0x01U) != BUS_OK)
  {
    return -1;
  }
  HAL_Delay(2);                                /* DS: 1 ms to reset          */
  (void)icm_read8(slot, ICM_INT_STATUS, &(uint8_t){0});   /* clear RESET_DONE */
  return 0;
}

/* INTF_CONFIG0 reset value is 0x30 (DS Rev 1.6 section 14.34): FIFO count in
   bytes, count big-endian, sensor data big-endian. We deliberately do not
   write this register -- asserting the reset value is safer than writing bit
   positions transcribed from a table whose cells the PDF extraction mangled,
   and 0x30 is exactly the configuration the decoders below assume. */
int icm_check_endian(bus_slot_t slot)
{
  uint8_t v = 0U;
  if (icm_read8(slot, ICM_INTF_CONFIG0, &v) != BUS_OK)
  {
    return -1;
  }
  if (v != 0x30U)
  {
    console_printf("icm%d: INTF_CONFIG0 = 0x%02X, expected 0x30 "
                   "(big-endian data + byte-mode FIFO count). "
                   "Decoders below assume 0x30.\r\n", (int)slot + 1, v);
    return -1;
  }
  return 0;
}

/* ==========================================================================
 * Configuration
 *
 * Sequencing is mandatory and is TN-16 section 5.3 verbatim:
 *   1. sensors OFF before any bank-1/2 static write
 *   2. bank 1 gyro AAF
 *   3. bank 2 accel AAF
 *   4. return to bank 0            <- forgetting this points every later
 *                                     access at the wrong bank
 *   5. sensors ON
 *   6. ODR/FSR last
 *   7. interrupts last of all
 * Writing static registers while running is a documented cause of broadband
 * noise corruption, which on this project would be indistinguishable from the
 * effect under study.
 * ========================================================================== */

int icm_configure(bus_slot_t slot, const icm_config_t *cfg)
{
  int err = 0;

  if (cfg == NULL)
  {
    return -1;
  }

  /* 1. sensors off */
  err |= icm_write8(slot, ICM_PWR_MGMT0, 0x00U);
  HAL_Delay(1);

  /* AAF is ALWAYS written, in both modes. Leaving it untouched for "native"
     inherits whatever the previous configuration left behind -- which on this
     board is the 42 Hz floor set at boot by the legacy icm_configure_matched()
     in main.c, making the two modes silently identical. That cost one M1 run
     to discover. */
  {
    const uint32_t delt     = (cfg->aaf == ICM_AAF_FLOOR)
                                ? ICM_AAF_FLOOR_DELT : ICM_AAF_DEFAULT_DELT;
    const uint32_t deltsqr  = (cfg->aaf == ICM_AAF_FLOOR)
                                ? ICM_AAF_FLOOR_DELTSQR : ICM_AAF_DEFAULT_DELTSQR;
    const uint32_t bitshift = (cfg->aaf == ICM_AAF_FLOOR)
                                ? ICM_AAF_FLOOR_BITSHIFT : ICM_AAF_DEFAULT_BITSHIFT;

    /* 2. gyro AAF, bank 1 */
    err |= icm_bank(slot, 1U);
    err |= icm_write8(slot, ICM_GYRO_CFG_STATIC3, (uint8_t)(delt & 0x3FU));
    err |= icm_write8(slot, ICM_GYRO_CFG_STATIC4, (uint8_t)(deltsqr & 0xFFU));
    err |= icm_write8(slot, ICM_GYRO_CFG_STATIC5,
                      (uint8_t)(((bitshift & 0x0FU) << 4)
                                | ((deltsqr >> 8) & 0x0FU)));

    /* 3. accel AAF, bank 2. DELT occupies [6:1]; bit0 is AAF_DIS = 0.
          [verify] the [6:1] placement -- TN-16 open item 4. The accel AAF has
          its own bandwidth table, so applying the gyro's DELT here does not
          give the accel the same cutoff. Harmless for M1, which is a gyro
          measurement, but do not read the accel bandwidth off the gyro table. */
    err |= icm_bank(slot, 2U);
    err |= icm_write8(slot, ICM_ACCEL_CFG_STATIC2,
                      (uint8_t)((delt & 0x3FU) << 1));
    err |= icm_write8(slot, ICM_ACCEL_CFG_STATIC3,
                      (uint8_t)(deltsqr & 0xFFU));
    err |= icm_write8(slot, ICM_ACCEL_CFG_STATIC4,
                      (uint8_t)(((bitshift & 0x0FU) << 4)
                                | ((deltsqr >> 8) & 0x0FU)));
  }

  /* 4. back to bank 0 -- unconditional, even if the AAF block was skipped */
  err |= icm_bank(slot, 0U);

  /* UI filter bandwidth. 0 is the only setting whose noise bandwidth tracks
     ODR (TN-13 Appendix Z.1); every other value plateaus below 200 Hz and
     there is no rho sweep at all. Both nibbles set the same way. */
  uint8_t uibw = (uint8_t)((cfg->ui_filt_bw & 0x0FU) * 0x11U);
  err |= icm_write8_verify(slot, ICM_GYRO_ACCEL_CONFIG0, uibw);

  err |= icm_rmw(slot, ICM_GYRO_CONFIG1,  0x0CU, 0x00U);   /* 1st order */
  err |= icm_rmw(slot, ICM_ACCEL_CONFIG1, 0x18U, 0x00U);

  /* 5. sensors on: gyro + accel, low-noise mode. [verify] the 0x0F encoding,
        TN-16 open item 3. */
  err |= icm_write8(slot, ICM_PWR_MGMT0, 0x0FU);
  HAL_Delay(1);

  /* 6. ODR and FSR last */
  uint8_t gcfg = (uint8_t)(((cfg->fs_sel & 0x07U) << 5) | (cfg->odr_code & 0x0FU));
  err |= icm_write8_verify(slot, ICM_GYRO_CONFIG0,  gcfg);
  err |= icm_write8_verify(slot, ICM_ACCEL_CONFIG0, gcfg);

  /* Gyro needs >=50 ms after PWR_MGMT0 before its output is real. TN-16
     section 4.6: at 1 ms all three axes read -32768, which is a not-ready
     sentinel and not data. */
  HAL_Delay(60);

  return (err == 0) ? 0 : -1;
}

/* ==========================================================================
 * FIFO
 * ========================================================================== */

int icm_fifo_flush(bus_slot_t slot)
{
  return icm_write8(slot, ICM_SIGNAL_PATH_RESET, ICM_FIFO_FLUSH);
}

int icm_fifo_count(bus_slot_t slot, uint16_t *bytes)
{
  /* Reading FIFO_COUNTH latches both bytes (DS section 14.22), so a single
     two-byte burst from 0x2E is atomic. Count is big-endian and expressed in
     bytes, both guaranteed by INTF_CONFIG0 == 0x30. */
  s_tx[0] = (uint8_t)(ICM_FIFO_COUNTH | 0x80U);
  s_tx[1] = 0x00U;
  s_tx[2] = 0x00U;

  int rc = bus_xfer(slot, s_tx, s_rx, 3U, 50U);
  if (rc != BUS_OK)
  {
    return rc;
  }

  *bytes = (uint16_t)(((uint16_t)s_rx[1] << 8) | s_rx[2]);
  return BUS_OK;
}

int icm_fifo_read(bus_slot_t slot, uint8_t *dst, uint16_t bytes)
{
  if ((dst == NULL) || (bytes == 0U) || ((uint32_t)bytes + 1U > BUS_MAX_XFER))
  {
    return BUS_E_ARG;
  }

  /* FIFO_DATA streams: the address does not auto-increment, successive clocks
     return successive FIFO bytes. So one address byte then `bytes` reads.

     These scratch buffers are deliberately smaller than BUS_MAX_XFER. This
     is the blocking, main-loop read used by `fifo` and `m1`; only the
     interrupt-driven sampler needs to drain the whole FIFO at once, and
     giving this path 2 KiB as well would cost 2 KiB of a 192 KiB region for
     nothing. */
  #define ICM_BLOCKING_READ_MAX  1040U
  if ((uint32_t)bytes + 1U > ICM_BLOCKING_READ_MAX) { return BUS_E_ARG; }

  static uint8_t tx[ICM_BLOCKING_READ_MAX];
  static uint8_t rx[ICM_BLOCKING_READ_MAX];

  tx[0] = (uint8_t)(ICM_FIFO_DATA | 0x80U);
  memset(&tx[1], 0, bytes);

  int rc = bus_xfer(slot, tx, rx, (uint16_t)(bytes + 1U), 100U);
  if (rc != BUS_OK)
  {
    return rc;
  }

  memcpy(dst, &rx[1], bytes);
  return BUS_OK;
}

/* ==========================================================================
 * Packet 4 decode  (DS Rev 1.6 section 6.1)
 *
 *   0x00 header
 *   0x01..0x06  accel X/Y/Z, [19:12] then [11:4]
 *   0x07..0x0C  gyro  X/Y/Z, [19:12] then [11:4]
 *   0x0D..0x0E  temperature, 16-bit
 *   0x0F..0x10  timestamp
 *   0x11..0x13  low nibbles: accel[3:0] in the high nibble, gyro[3:0] in the
 *               low nibble, one byte per axis
 *
 * gyro_hi16 is bytes 0x07/0x08 concatenated, which is bits [19:4] of the fine
 * word. Hi-res sensitivity is 131 LSB/dps = 8 x 16.4 and the 20-bit LSB is
 * always zero, so the significant word is 19 bits and the 16-bit register
 * ought to equal exactly this if it is a truncation. That comparison is V0.4.
 * ========================================================================== */

static inline int32_t sext20(uint32_t v)
{
  return (int32_t)(v << 12) >> 12;
}

int icm_packet4_decode(const uint8_t *p, icm_packet_t *out)
{
  if ((p == NULL) || (out == NULL))
  {
    return -1;
  }

  out->header = p[0];
  if ((p[0] & ICM_HDR_MSG) != 0U)
  {
    return -1;                                   /* FIFO empty marker */
  }

  for (int a = 0; a < 3; a++)
  {
    uint8_t hi = p[1 + 2 * a];
    uint8_t md = p[2 + 2 * a];
    uint8_t lo = (uint8_t)((p[0x11 + a] >> 4) & 0x0FU);
    out->accel[a] = sext20(((uint32_t)hi << 12) | ((uint32_t)md << 4) | lo);
  }

  for (int a = 0; a < 3; a++)
  {
    uint8_t hi = p[7 + 2 * a];
    uint8_t md = p[8 + 2 * a];
    uint8_t lo = (uint8_t)(p[0x11 + a] & 0x0FU);
    out->gyro[a]      = sext20(((uint32_t)hi << 12) | ((uint32_t)md << 4) | lo);
    out->gyro_hi16[a] = (int16_t)(((uint16_t)hi << 8) | md);
  }

  out->temp = (int16_t)(((uint16_t)p[0x0D] << 8) | p[0x0E]);
  out->tmst = (uint16_t)(((uint16_t)p[0x0F] << 8) | p[0x10]);
  return 0;
}

/* ==========================================================================
 * 16-bit register path
 * ========================================================================== */

int icm_read_regs(bus_slot_t slot, int16_t *temp,
                  int16_t accel[3], int16_t gyro[3])
{
  static uint8_t tx[16];
  static uint8_t rx[16];

  tx[0] = (uint8_t)(ICM_TEMP_DATA1 | 0x80U);
  memset(&tx[1], 0, 14);

  int rc = bus_xfer(slot, tx, rx, 15U, 50U);
  if (rc != BUS_OK)
  {
    return rc;
  }

  /* Big-endian throughout, guaranteed by INTF_CONFIG0 == 0x30. */
  const uint8_t *d = &rx[1];
  if (temp != NULL)  { *temp = (int16_t)(((uint16_t)d[0] << 8) | d[1]); }
  for (int a = 0; a < 3; a++)
  {
    if (accel != NULL) { accel[a] = (int16_t)(((uint16_t)d[2 + 2*a] << 8) | d[3 + 2*a]); }
    if (gyro  != NULL) { gyro[a]  = (int16_t)(((uint16_t)d[8 + 2*a] << 8) | d[9 + 2*a]); }
  }
  return BUS_OK;
}

/* ==========================================================================
 * Console
 * ========================================================================== */

static bus_slot_t s_slot = BUS_SLOT_1;

static void cmd_icm(int argc, char **argv)
{
  if (argc >= 2)
  {
    long s = strtol(argv[1], NULL, 10);
    if (s >= 1 && s <= 4) { s_slot = (bus_slot_t)(s - 1); }
    else { console_printf("usage: icm [slot 1..4]\r\n"); return; }
  }

  console_printf("icm: slot %d, DMA %s\r\n",
                 (int)s_slot + 1, bus_has_dma(s_slot) ? "yes" : "no");

  if (icm_probe(s_slot) != 0) { return; }
  console_printf("  WHO_AM_I 0x47 ok\r\n");
  (void)icm_check_endian(s_slot);

  uint8_t v;
  static const struct { uint8_t reg; const char *name; } regs[] = {
    { ICM_PWR_MGMT0,        "PWR_MGMT0       " },
    { ICM_GYRO_CONFIG0,     "GYRO_CONFIG0    " },
    { ICM_GYRO_ACCEL_CONFIG0,"GYRO_ACCEL_CFG0 " },
    { ICM_FIFO_CONFIG,      "FIFO_CONFIG     " },
    { ICM_FIFO_CONFIG1,     "FIFO_CONFIG1    " },
    { ICM_INT_SOURCE0,      "INT_SOURCE0     " },
    { ICM_INTF_CONFIG0,     "INTF_CONFIG0    " },
  };
  for (unsigned i = 0; i < sizeof regs / sizeof regs[0]; i++)
  {
    if (icm_read8(s_slot, regs[i].reg, &v) == BUS_OK)
      console_printf("  %s 0x%02X = 0x%02X\r\n", regs[i].name, regs[i].reg, v);
  }

  console_printf("  bus: %lu done, %lu overrun, %lu fault\r\n",
                 (unsigned long)bus_completions(s_slot),
                 (unsigned long)bus_overruns(s_slot),
                 (unsigned long)bus_faults(s_slot));
}

/* Configures hi-res FIFO, collects n packets, and prints each alongside a
   16-bit register read. The rightmost column is V0.4: hi16 is bits [19:4] of
   the fine word, reg is what the 16-bit register reports, d is the difference.
     all d = 0      -> the register truncates the fine word
     d in {0, 1}    -> it rounds; correlate d against the discarded nibble
     anything else  -> neither, and the five-way score matters             */
uint8_t icm_odr_code(long hz)
{
  switch (hz) {
    case 25:   return ICM_ODR_25HZ;
    case 50:   return ICM_ODR_50HZ;
    case 100:  return ICM_ODR_100HZ;
    case 200:  return ICM_ODR_200HZ;
    case 500:  return ICM_ODR_500HZ;
    case 1000: return ICM_ODR_1KHZ;
    case 8000: return ICM_ODR_8KHZ;
    default:   return 0xFFU;
  }
}

static void cmd_fifo(int argc, char **argv)
{
  uint32_t want = 8;
  long     hz   = 100;

  if (argc >= 2)
  {
    long n = strtol(argv[1], NULL, 10);
    if (n >= 1 && n <= 500L) { want = (uint32_t)n; }
  }
  if (argc >= 3)
  {
    hz = strtol(argv[2], NULL, 10);
    if (icm_odr_code(hz) == 0xFFU)
    {
      console_printf("usage: fifo [n] [odr 25|50|100|200|500|1000|8000]\r\n");
      return;
    }
  }

  icm_config_t cfg = {
    .odr_code   = icm_odr_code(hz),
    .fs_sel     = 0U,                 /* +-2000 dps; hi-res forces this anyway */
    .ui_filt_bw = 0U,                 /* the only setting that tracks ODR      */
    .aaf        = ICM_AAF_DEFAULT,
    .hires      = 1U,
    .watermark  = ICM_PACKET4_LEN,    /* one packet -> one interrupt           */
  };

  if (icm_probe(s_slot) != 0) { return; }
  if (icm_configure(s_slot, &cfg) != 0)
  {
    console_printf("fifo: configure failed\r\n");
    return;
  }

  /* FIFO: gyro + accel + temp, hi-res, stream mode. Order matters -- set the
     contents and watermark while bypassed, then switch the mode on. */
  (void)icm_write8(s_slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_BYPASS);
  (void)icm_write8_verify(s_slot, ICM_FIFO_CONFIG1,
                          ICM_FIFO_HIRES_EN | ICM_FIFO_TEMP_EN
                          | ICM_FIFO_GYRO_EN | ICM_FIFO_ACCEL_EN);
  (void)icm_write8_verify(s_slot, ICM_FIFO_CONFIG2,
                          (uint8_t)(cfg.watermark & 0xFFU));
  (void)icm_write8_verify(s_slot, ICM_FIFO_CONFIG3,
                          (uint8_t)((cfg.watermark >> 8) & 0x0FU));
  (void)icm_fifo_flush(s_slot);
  (void)icm_write8_verify(s_slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_STREAM);

  console_printf("fifo: ODR %ld Hz, hi-res, watermark %u B\r\n",
                 hz, (unsigned)cfg.watermark);

  /* The FIFO is a QUEUE and the register holds the NEWEST sample. Reading a
     backlogged FIFO compares an old packet against a fresh register, which
     looks exactly like a quantiser disagreement. So: flush, wait for exactly
     one packet to appear, read it, read the register immediately. Nothing is
     printed inside the loop -- a 55-character line over UART at 115200 is
     ~4.8 ms, which at 1 kHz alone builds four samples of lag per iteration.

     Residual skew is the gap between the two SPI transfers, ~30 us. Against
     the sample period that is 0.08% at 25 Hz, 3% at 1 kHz and 24% at 8 kHz --
     so a clean result is expected up to 1 kHz and NOT at 8 kHz. Settling
     8 kHz would need hardware-synchronised capture, and does not need
     settling at all if the register turns out to be derivable. */
  const uint32_t period_us = (uint32_t)(1000000L / hz);
  console_printf("  period %lu us, read gap ~30 us (%lu%% of a period)\r\n",
                 (unsigned long)period_us,
                 (unsigned long)(3000UL / (period_us ? period_us : 1)));

  uint8_t pkt[ICM_PACKET4_LEN];
  icm_packet_t s = {0};
  uint32_t got = 0, empty = 0, odd20 = 0, rderr = 0, stale = 0;
  uint32_t axes = 0, discrim = 0, hit_floor = 0, hit_round = 0, hit_neither = 0;

  /* first rows saved and printed after the loop, not during it */
  #define FIFO_SHOW 12U
  int32_t show_g[FIFO_SHOW][3];
  int16_t show_r[FIFO_SHOW][3];

  bus_clear_stats(s_slot);
  uint64_t t0 = timebase_now_us();

  while (got < want && (timebase_now_us() - t0) < 10000000ULL)
  {
    /* Empty the queue so the next packet to appear is unambiguously the
       newest sample. */
    if (icm_fifo_flush(s_slot) != BUS_OK) { rderr++; break; }

    uint16_t avail = 0;
    uint64_t tw = timebase_now_us();
    do {
      if (icm_fifo_count(s_slot, &avail) != BUS_OK) { rderr++; avail = 0; break; }
      if (timebase_now_us() - tw > 200000ULL) { break; }   /* 200 ms */
    } while (avail < ICM_PACKET4_LEN);

    if (avail < ICM_PACKET4_LEN) { stale++; continue; }
    if (avail > ICM_PACKET4_LEN) { stale++; }   /* more than one arrived */

    if (icm_fifo_read(s_slot, pkt, ICM_PACKET4_LEN) != BUS_OK) { rderr++; break; }
    if (icm_packet4_decode(pkt, &s) != 0) { empty++; continue; }

    int16_t reg_g[3];
    if (icm_read_regs(s_slot, NULL, NULL, reg_g) != BUS_OK) { rderr++; break; }

    for (int a = 0; a < 3; a++)
    {
      if ((s.gyro[a] & 1) != 0) { odd20++; }

      /* floor: arithmetic shift, i.e. the register is literally bits [19:4].
         round: nearest, ties up. They differ only when the discarded low
         nibble is >= 8, which is the only case that can tell them apart. */
      int32_t f = s.gyro[a] >> 4;
      int32_t r = (s.gyro[a] + 8) >> 4;

      axes++;
      if (f != r)
      {
        discrim++;
        if      (reg_g[a] == (int16_t)f) { hit_floor++; }
        else if (reg_g[a] == (int16_t)r) { hit_round++; }
        else                             { hit_neither++; }
      }
      else if (reg_g[a] != (int16_t)f)   { hit_neither++; }
    }

    if (got < FIFO_SHOW)
    {
      for (int a = 0; a < 3; a++) { show_g[got][a] = s.gyro[a]; show_r[got][a] = reg_g[a]; }
    }
    got++;
  }

  for (uint32_t i = 0; i < got && i < FIFO_SHOW; i++)
  {
    console_printf("  [%6ld %6ld %6ld] -> [%6d %6d %6d]\r\n",
                   (long)show_g[i][0], (long)show_g[i][1], (long)show_g[i][2],
                   show_r[i][0], show_r[i][1], show_r[i][2]);
  }

  console_printf("fifo: %lu packets, %lu empty, %lu rd-err, %lu backlog, "
                 "hdr=0x%02X, odd20=%lu\r\n",
                 (unsigned long)got, (unsigned long)empty,
                 (unsigned long)rderr, (unsigned long)stale,
                 s.header, (unsigned long)odd20);
  console_printf("  bus: %lu done, %lu overrun, %lu fault\r\n",
                 (unsigned long)bus_completions(s_slot),
                 (unsigned long)bus_overruns(s_slot),
                 (unsigned long)bus_faults(s_slot));

  if (got == 0)
  {
    console_printf("  nothing arrived: check the FIFO_CONFIG readback above, "
                   "and that PWR_MGMT0 is 0x0F\r\n");
    return;
  }

  console_printf("V0.4: %lu axis-samples, %lu discriminating "
                 "(low nibble >= 8)\r\n",
                 (unsigned long)axes, (unsigned long)discrim);
  console_printf("  floor(bits[19:4]) %lu   round %lu   neither %lu\r\n",
                 (unsigned long)hit_floor, (unsigned long)hit_round,
                 (unsigned long)hit_neither);

  if (discrim == 0)
    console_printf("  inconclusive: no sample had a low nibble >= 8. "
                   "Run longer, or at a higher ODR.\r\n");
  else if (hit_neither == 0 && hit_round == 0)
    console_printf("  => TRUNCATION. The register is bits [19:4] of the fine "
                   "word, so the 16-bit stream is derivable in software.\r\n");
  else if (hit_neither == 0 && hit_floor == 0)
    console_printf("  => ROUNDING. The register is a mid-tread rounder of the "
                   "fine word.\r\n");
  else if (period_us < 500U)
    console_printf("  => mixed, but at %lu us the ~30 us read gap is %lu%% of "
                   "a period. Expected. Trust the low-ODR runs.\r\n",
                   (unsigned long)period_us,
                   (unsigned long)(3000UL / (period_us ? period_us : 1)));
  else
    console_printf("  => NEITHER cleanly, and NOT explicable as read skew at "
                   "this ODR. Score against RPDF/TPDF; this is the outcome "
                   "TN-13 Z.4 warns about.\r\n");
}

static const console_cmd_t s_icm_cmds[] = {
  { "icm",  "icm [slot] - probe and dump ICM configuration registers", cmd_icm },
  { "fifo", "fifo [n] [odr] - hi-res FIFO vs 16-bit registers, scores V0.4", cmd_fifo },
};

void icm_console_init(void)
{
  (void)console_register(s_icm_cmds,
                         (uint8_t)(sizeof s_icm_cmds / sizeof s_icm_cmds[0]));
}
