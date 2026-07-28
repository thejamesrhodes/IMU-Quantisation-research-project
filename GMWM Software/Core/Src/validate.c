/**
  ******************************************************************************
  * @file    validate.c
  * @brief   Validation Zero harness -- Test M1.
  ******************************************************************************
  */

#include "validate.h"
#include "imu_icm42688.h"
#include "bus.h"
#include "console.h"
#include "timebase.h"

#include <stdlib.h>
#include <string.h>
#include "main.h"

/* ==========================================================================
 * Statistics
 *
 * Accumulated in int64 against a shifted origin. The 20-bit field can reach
 * 2^19; squared that is 2^38, and 30 000 of them is 2^53 -- inside int64 but
 * uncomfortably close, and the whole sum would be dominated by the mean.
 * Subtracting the first sample keeps the accumulators small and removes the
 * catastrophic cancellation that a naive sum-of-squares suffers when the mean
 * is large relative to the spread. Here the mean is ~100 LSB and sigma is a
 * few LSB, so this matters.
 * ========================================================================== */

typedef struct {
  uint32_t n;
  int32_t  origin;          /* first sample, subtracted from everything      */
  int64_t  sum;             /* sum of (x - origin)                           */
  int64_t  sumsq;           /* sum of (x - origin)^2                         */
  int16_t  c_min, c_max;    /* derived 16-bit code range                     */
  uint32_t codes;           /* distinct 16-bit codes seen                    */
  uint32_t code_out;        /* codes outside the +-128 window                */
  uint8_t  seen[256];       /* occupancy bitmap around the first code        */
  int16_t  c_origin;
} axis_stat_t;

static axis_stat_t s_ax[3];

/* Die temperature, accumulated alongside. Packet 4 carries a 16-bit field, so
   the register scaling applies: 132.48 LSB/degC, i.e. 7.55 mK per LSB. The
   datasheet's "FIFO temperature is 8-bit, 2.07 LSB/degC" describes packets
   1-3; 132.48 / 64 = 2.07 exactly, so the 8-bit form is the 16-bit one
   shifted down six places. The ODR 25 thermal gate of 260 mK is 34 LSB, so
   rule R2 is satisfiable directly from the packet. */
static int64_t  s_temp_sum;
static uint32_t s_temp_n;

/* milli-degC from a raw 16-bit field: (raw / 132.48 + 25) * 1000 */
static int32_t temp_milli_c(int32_t raw_milli_lsb)
{
  return (int32_t)((raw_milli_lsb * 1000LL) / 132480LL) + 25000;
}

static void stat_reset(void)
{
  memset(s_ax, 0, sizeof s_ax);
  s_temp_sum = 0;
  s_temp_n   = 0;
}

static void stat_push(int a, int32_t v20)
{
  axis_stat_t *st = &s_ax[a];
  int16_t code = (int16_t)(v20 >> 4);            /* V0.4: register == this  */

  if (st->n == 0U)
  {
    st->origin   = v20;
    st->c_origin = code;
    st->c_min = st->c_max = code;
  }

  int64_t d = (int64_t)v20 - (int64_t)st->origin;
  st->sum   += d;
  st->sumsq += d * d;
  st->n++;

  if (code < st->c_min) { st->c_min = code; }
  if (code > st->c_max) { st->c_max = code; }

  int idx = (int)code - (int)st->c_origin + 128;
  if (idx >= 0 && idx < 256)
  {
    if (!st->seen[idx]) { st->seen[idx] = 1U; st->codes++; }
  }
  else
  {
    st->code_out++;
  }
}

/* Sample standard deviation, in milli-LSB of the 20-bit field. Integer
   throughout: the console has no float formatting under nano.specs and a
   printf("%f") here would silently emit nothing. */
static uint32_t stat_sigma_milli(const axis_stat_t *st)
{
  if (st->n < 2U) { return 0U; }

  /* var = (sumsq - sum^2/n) / (n-1), scaled by 1e6 so the sqrt lands in
     milli-units. */
  int64_t n    = (int64_t)st->n;
  int64_t num  = st->sumsq - (st->sum * st->sum) / n;
  if (num < 0) { num = 0; }

  uint64_t var_micro = (uint64_t)((num * 1000000LL) / (n - 1));

  /* integer sqrt of a 64-bit value, Newton */
  uint64_t x = var_micro, r = 0;
  if (x > 0U)
  {
    r = x;
    uint64_t last = 0;
    while (r != last)
    {
      last = r;
      r = (r + x / r) / 2U;
    }
  }
  return (uint32_t)r;                            /* milli-LSB of the 20-bit field */
}

/* ==========================================================================
 * Collection
 * ========================================================================== */

#define VAL_PKTS_PER_READ  40U                   /* 40 x 20 B = 800 B < BUS_MAX_XFER */

static uint8_t s_buf[VAL_PKTS_PER_READ * ICM_PACKET4_LEN];

/* Reads n samples from the hi-res FIFO with no console traffic in the loop.
   Returns the number collected. Bulk reads, no flushing: for a variance
   measurement queue lag is irrelevant -- every sample is used and the order
   is preserved. That is exactly why M1 does not need the paired-capture
   machinery V0.4 needed. */
static uint32_t collect(bus_slot_t slot, uint32_t want, uint32_t timeout_ms,
                        uint32_t *overflows)
{
  icm_packet_t s;
  uint32_t got = 0;
  uint64_t t0 = timebase_now_us();

  *overflows = 0;
  (void)icm_fifo_flush(slot);

  while (got < want)
  {
    if ((timebase_now_us() - t0) > (uint64_t)timeout_ms * 1000ULL) { break; }

    uint16_t avail = 0;
    if (icm_fifo_count(slot, &avail) != BUS_OK) { break; }

    /* 2 KiB FIFO. If it is nearly full we are not keeping up and samples have
       already been overwritten in stream mode -- count it, because a variance
       computed across a discontinuity is not a variance. */
    if (avail > 1900U) { (*overflows)++; }

    uint32_t pkts = avail / ICM_PACKET4_LEN;
    if (pkts == 0U) { continue; }
    if (pkts > VAL_PKTS_PER_READ) { pkts = VAL_PKTS_PER_READ; }
    if (pkts > (want - got))      { pkts = want - got; }

    if (icm_fifo_read(slot, s_buf, (uint16_t)(pkts * ICM_PACKET4_LEN)) != BUS_OK)
    {
      break;
    }

    for (uint32_t i = 0; i < pkts; i++)
    {
      if (icm_packet4_decode(&s_buf[i * ICM_PACKET4_LEN], &s) != 0) { continue; }
      for (int a = 0; a < 3; a++) { stat_push(a, s.gyro[a]); }
      s_temp_sum += (int64_t)s.temp;
      s_temp_n++;
      got++;
    }
  }
  return got;
}

/* ==========================================================================
 * Test M1
 * ========================================================================== */

static const struct { long hz; uint8_t code; } s_sweep[] = {
  {   25, ICM_ODR_25HZ  },
  {   50, ICM_ODR_50HZ  },
  {  100, ICM_ODR_100HZ },
  {  200, ICM_ODR_200HZ },
  {  500, ICM_ODR_500HZ },
  { 1000, ICM_ODR_1KHZ  },
};
#define SWEEP_N (sizeof s_sweep / sizeof s_sweep[0])

/* integer sqrt of (x * 1000000), i.e. sqrt(x) in milli-units */
static uint32_t isqrt_milli(uint32_t x1000)
{
  uint64_t v = (uint64_t)x1000 * 1000ULL;        /* x * 1e6 when x1000 = x*1e3 */
  if (v == 0U) { return 0U; }
  uint64_t r = v, last = 0;
  while (r != last) { last = r; r = (r + v / r) / 2U; }
  return (uint32_t)r;
}

static void cmd_m1(int argc, char **argv)
{
  uint32_t want = 3000;
  int      aaf_floor = 0;
  bus_slot_t slot = BUS_SLOT_1;

  for (int i = 1; i < argc; i++)
  {
    if (strcmp(argv[i], "aaf") == 0)      { aaf_floor = 1; }
    else if (strcmp(argv[i], "slot2") == 0) { slot = BUS_SLOT_2; }
    else
    {
      long n = strtol(argv[i], NULL, 10);
      if (n >= 100 && n <= 60000L) { want = (uint32_t)n; }
      else { console_printf("usage: m1 [samples] [aaf] [slot2]\r\n"); return; }
    }
  }

  if (icm_probe(slot) != 0) { return; }

  console_printf("M1: sigma vs ODR from the 19-bit stream, "
                 "GYRO_UI_FILT_BW = 0\r\n");
  console_printf("  AAF %s, %lu samples per point, slot %d\r\n",
                 aaf_floor ? "42 Hz floor  (DELT 1)"
                           : "585 Hz default (DELT 13)",
                 (unsigned long)want, (int)slot + 1);
  console_printf("  sigma is in milli-LSB of the 20-bit field; "
                 "rho = sigma / 16 in 16-bit LSB\r\n");
  console_printf("  DO NOT TOUCH THE BENCH while this runs.\r\n\r\n");

  console_printf("  ODR   n     sigma20   rho     ratio  sqrt(f/25)  "
                 "codes  range   ovf\r\n");

  uint32_t sig25 = 0;

  for (unsigned k = 0; k < SWEEP_N; k++)
  {
    icm_config_t cfg = {
      .odr_code   = s_sweep[k].code,
      .fs_sel     = 0U,
      .ui_filt_bw = 0U,                   /* the only setting that tracks ODR */
      .aaf        = aaf_floor ? ICM_AAF_FLOOR : ICM_AAF_DEFAULT,
      .hires      = 1U,
      .watermark  = ICM_PACKET4_LEN,
    };

    if (icm_configure(slot, &cfg) != 0)
    {
      console_printf("  %5ld  configure FAILED\r\n", s_sweep[k].hz);
      continue;
    }

    /* FIFO: gyro only is enough for M1 and quarters the bus traffic, which
       matters because bus activity is a controlled confound (rule R8). */
    (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_BYPASS);
    (void)icm_write8_verify(slot, ICM_FIFO_CONFIG1,
                            ICM_FIFO_HIRES_EN | ICM_FIFO_GYRO_EN
                            | ICM_FIFO_ACCEL_EN);
    (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_STREAM);

    HAL_Delay(2000);                      /* let the filter chain settle      */

    stat_reset();
    uint32_t ovf = 0;
    uint32_t timeout = (uint32_t)((want * 1500UL) / (uint32_t)s_sweep[k].hz) + 5000UL;
    uint32_t got = collect(slot, want, timeout, &ovf);

    if (got < 100U)
    {
      console_printf("  %5ld  only %lu samples\r\n", s_sweep[k].hz,
                     (unsigned long)got);
      continue;
    }

    /* Pool the three axes: they share the same bandwidth, and pooling
       triples the effective sample count for the bandwidth question M1 asks.
       Per-axis figures follow underneath. */
    uint32_t sg = (stat_sigma_milli(&s_ax[0]) + stat_sigma_milli(&s_ax[1])
                   + stat_sigma_milli(&s_ax[2])) / 3U;

    if (k == 0U) { sig25 = sg; }

    uint32_t ratio  = (sig25 > 0U) ? (sg * 1000U) / sig25 : 0U;
    uint32_t expect = isqrt_milli((uint32_t)((s_sweep[k].hz * 1000L) / 25L));

    console_printf("  %5ld %5lu %7lu %5lu.%03lu %3lu.%03lu   %2lu.%03lu   "
                   "%4lu  %4d..%-4d %3lu\r\n",
                   s_sweep[k].hz, (unsigned long)got,
                   (unsigned long)sg,
                   (unsigned long)(sg / 16000U), (unsigned long)((sg / 16U) % 1000U),
                   (unsigned long)(ratio / 1000U), (unsigned long)(ratio % 1000U),
                   (unsigned long)(expect / 1000U), (unsigned long)(expect % 1000U),
                   (unsigned long)s_ax[0].codes,
                   s_ax[0].c_min, s_ax[0].c_max,
                   (unsigned long)ovf);
  }

  console_printf("\r\nM1 verdict:\r\n");
  console_printf("  ratio tracking sqrt(f/25) => sigma falls as sqrt(ODR); "
                 "case (a), the low-ODR axis is real\r\n");
  console_printf("  ratio flat near 1.000     => sigma plateaus; case (b), "
                 "aliasing dominates and the low-ODR sweep must be replanned\r\n");
  console_printf("  TN-13 Z.1, from the datasheet NBW tables at BW = 0:\r\n"
                 "    NBW 13.0 / 26.0 / 52.0 / 103.9 / 259.6 Hz at "
                 "25 / 50 / 100 / 200 / 500\r\n"
                 "    -> rho 0.165 / 0.234 / 0.331 / 0.468 / 0.739, which IS "
                 "sqrt(ODR) from 25 up.\r\n"
                 "    (12.5 Hz shares 13.0 Hz NBW with 25, which is why "
                 "TN-14 drops it.)\r\n");
  console_printf("  CAVEAT: absolute rho will read HIGH. TN-16 11.3 measured "
                 "4-6x the datasheet\r\n"
                 "  noise density on this bench. M1 asks about SCALING, not "
                 "level -- but a bench\r\n"
                 "  dominated by a coherent line or LF drift breaks the "
                 "scaling too, so a failure\r\n"
                 "  here is not automatically the sensor. Screen the spectrum "
                 "before concluding.\r\n");
}

/* ==========================================================================
 * Settle time
 *
 * TN-14 section 5: settling is 26 h of the 55 h campaign wall-clock and is
 * "the single biggest lever". The 15-minute figure is an assumption that has
 * never been measured, and TN-14 explicitly asks for it to be measured at
 * Validation Zero and the budget re-derived.
 *
 * What settles is the die temperature. Power draw rises with ODR, the die
 * warms, and the zero-rate output moves at +-5 mdps/K -- which moves the
 * sub-LSB bias phase, which is what rule R2's gate protects. So the test
 * imposes the worst realistic step (low ODR to high ODR) and watches dT/dt
 * until it drops below the gate rate.
 *
 * Criterion, tied directly to R2 rather than chosen: the ODR 25 gate is
 * 0.78 K/h = 13 mK/min. Settled when |dT/dt| stays under that.
 * ========================================================================== */

static void cmd_settle(int argc, char **argv)
{
  long to_hz    = 1000;
  long from_hz  = 25;
  uint32_t block_s = 10;
  uint32_t total_s = 900;                 /* 15 min -- TN-14's assumption */
  bus_slot_t slot = BUS_SLOT_1;

  if (argc >= 2) { to_hz   = strtol(argv[1], NULL, 10); }
  if (argc >= 3) { from_hz = strtol(argv[2], NULL, 10); }
  if (argc >= 4) { block_s = (uint32_t)strtol(argv[3], NULL, 10); }
  if (argc >= 5) { total_s = (uint32_t)strtol(argv[4], NULL, 10); }

  if (icm_odr_code(to_hz) == 0xFFU || icm_odr_code(from_hz) == 0xFFU ||
      block_s < 2U || block_s > 600U || total_s < block_s || total_s > 43200U)
  {
    console_printf("usage: settle [to_odr] [from_odr] [block_s] [total_s]\r\n"
                   "  default: settle 1000 25 10 900\r\n");
    return;
  }

  if (icm_probe(slot) != 0) { return; }

  icm_config_t cfg = {
    .fs_sel = 0U, .ui_filt_bw = 0U, .aaf = ICM_AAF_DEFAULT,
    .hires = 1U, .watermark = ICM_PACKET4_LEN,
  };

  console_printf("settle: %ld Hz -> %ld Hz, %lu s blocks, %lu s total\r\n",
                 from_hz, to_hz, (unsigned long)block_s,
                 (unsigned long)total_s);

  /* Establish the starting thermal state at the low ODR. */
  cfg.odr_code = icm_odr_code(from_hz);
  if (icm_configure(slot, &cfg) != 0) { console_printf("  configure failed\r\n"); return; }
  (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_BYPASS);
  (void)icm_write8(slot, ICM_FIFO_CONFIG1,
                   ICM_FIFO_HIRES_EN | ICM_FIFO_GYRO_EN | ICM_FIFO_ACCEL_EN);
  (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_STREAM);

  console_printf("  holding at %ld Hz for 120 s to reach a baseline...\r\n",
                 from_hz);
  HAL_Delay(120000);

  /* The step. */
  cfg.odr_code = icm_odr_code(to_hz);
  if (icm_configure(slot, &cfg) != 0) { console_printf("  configure failed\r\n"); return; }
  (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_BYPASS);
  (void)icm_write8(slot, ICM_FIFO_CONFIG1,
                   ICM_FIFO_HIRES_EN | ICM_FIFO_GYRO_EN | ICM_FIFO_ACCEL_EN);
  (void)icm_write8(slot, ICM_FIFO_CONFIG, ICM_FIFO_MODE_STREAM);

  console_printf("\r\n   t(s)   temp(mC)  dT(mK)  dT/dt(mK/min)   "
                 "bias20   sigma20   n\r\n");

  const uint32_t per_block = (uint32_t)((long)block_s * to_hz);
  int32_t  t_first = 0, t_prev = 0;
  uint32_t elapsed = 0;
  uint32_t settled_at = 0;
  int      have_first = 0;

  while (elapsed < total_s)
  {
    stat_reset();
    uint32_t ovf = 0;
    uint32_t got = collect(slot, per_block, block_s * 1500U + 5000U, &ovf);
    elapsed += block_s;

    if (got < 10U || s_temp_n == 0U)
    {
      console_printf("  %5lu   (only %lu samples)\r\n",
                     (unsigned long)elapsed, (unsigned long)got);
      continue;
    }

    int32_t traw_milli = (int32_t)((s_temp_sum * 1000LL) / (int64_t)s_temp_n);
    int32_t tmc = temp_milli_c(traw_milli);

    if (!have_first) { t_first = tmc; t_prev = tmc; have_first = 1; }

    int32_t dT   = tmc - t_first;
    int32_t rate = ((tmc - t_prev) * 60) / (int32_t)block_s;   /* mK/min */
    t_prev = tmc;

    /* Pooled bias, in milli-LSB of the 20-bit field. Phase lives here:
       +-5 mdps/K over a 61.035 mdps LSB is one LSB of phase per 12.2 K. */
    int64_t bias = 0;
    for (int a = 0; a < 3; a++)
    {
      bias += (int64_t)s_ax[a].origin * 1000
              + (s_ax[a].sum * 1000) / (int64_t)s_ax[a].n;
    }
    bias /= 3;

    uint32_t sg = (stat_sigma_milli(&s_ax[0]) + stat_sigma_milli(&s_ax[1])
                   + stat_sigma_milli(&s_ax[2])) / 3U;

    console_printf("  %5lu   %7ld  %6ld  %8ld       %7ld  %7lu %5lu%s\r\n",
                   (unsigned long)elapsed, (long)tmc, (long)dT, (long)rate,
                   (long)(bias / 1000), (unsigned long)sg,
                   (unsigned long)got, ovf ? "  OVF" : "");

    if ((settled_at == 0U) && (elapsed > block_s) &&
        (rate < 13) && (rate > -13))
    {
      settled_at = elapsed;
    }
  }

  console_printf("\r\nsettle: |dT/dt| first fell below 13 mK/min "
                 "(the ODR 25 gate rate of 0.78 K/h) at ");
  if (settled_at) { console_printf("t = %lu s\r\n", (unsigned long)settled_at); }
  else            { console_printf("no point in %lu s\r\n", (unsigned long)total_s); }

  console_printf("  TN-14 budgets 15 min x 26 configs x specimens = 26 h of "
                 "the 55 h wall clock.\r\n"
                 "  Every minute saved here is ~26 min off the campaign per "
                 "specimen.\r\n");
}

static const console_cmd_t s_val_cmds[] = {
  { "m1", "m1 [samples] [aaf] [slot2] - Test M1: does sigma fall as sqrt(ODR)?",
    cmd_m1 },
  { "settle", "settle [to] [from] [blk_s] [tot_s] - die-temp settle after an ODR step",
    cmd_settle },
};

void validate_console_init(void)
{
  (void)console_register(s_val_cmds,
                         (uint8_t)(sizeof s_val_cmds / sizeof s_val_cmds[0]));
}
