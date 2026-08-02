/**
  ******************************************************************************
  * @file    seq.c
  * @brief   Unattended run sequencer. See seq.h for the format and rationale.
  ******************************************************************************
  */

#include "seq.h"
#include "storage.h"
#include "console.h"
#include "timebase.h"
#include "led.h"
#include "imu_icm42688.h"
#include "sheppard_config.h"

#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#include "fatfs.h"

#define SEQ_PLAN  SHEPPARD_SD_DIR "/plan.txt"
#define SEQ_ARM   SHEPPARD_SD_DIR "/plan.arm"
#define SEQ_DONE  SHEPPARD_SD_DIR "/plan.done"

#define SEQ_LINE_MAX  120

/* Static: FIL is ~600 B with exFAT and the stack is 0x1000. */
static FIL  s_f;
static char s_line[SEQ_LINE_MAX];
static char s_label[24];

/* ==========================================================================
 * Line reading
 *
 * f_gets exists, but it stops at the buffer size without telling you, which
 * turns an over-long plan line into two silently-executed half-lines. Reading
 * by hand lets an over-length line be reported and skipped.
 * ========================================================================== */

static int read_line(FIL *f, char *dst, int cap, int *too_long)
{
  int n = 0;
  *too_long = 0;
  for (;;)
  {
    char c; UINT br = 0;
    if ((f_read(f, &c, 1, &br) != FR_OK) || (br == 0))
    {
      dst[n] = '\0';
      return (n > 0) ? n : -1;                 /* -1 = end of file */
    }
    if (c == '\r') { continue; }
    if (c == '\n') { dst[n] = '\0'; return n; }
    if (n < cap - 1) { dst[n++] = c; }
    else             { *too_long = 1; }
  }
}

static int split(char *s, char **tok, int max)
{
  int n = 0;
  char *p = s;
  while (*p && (n < max))
  {
    while (*p == ' ' || *p == '\t') { p++; }
    if (*p == '\0') { break; }
    tok[n++] = p;
    while (*p && *p != ' ' && *p != '\t') { p++; }
    if (*p) { *p++ = '\0'; }
  }
  return n;
}

/* ==========================================================================
 * Execution
 * ========================================================================== */

typedef struct {
  uint32_t steps, ok, gate_fail, lost, setup_fail, skipped;
} seq_tally_t;

static void warmup(long secs)
{
  /* Idle, but with the LEDs and the console alive so the operator can see the
     board is not simply hung. Nothing is recorded: the point is to let the
     die reach its working temperature before any gated record starts. */
  console_printf("seq: warmup %ld s\r\n", secs);
  uint64_t t0 = timebase_now_us();
  long announced = -1;
  while ((timebase_now_us() - t0) < (uint64_t)secs * 1000000ULL)
  {
    long left = secs - (long)((timebase_now_us() - t0) / 1000000ULL);
    if ((left != announced) && ((left % 60) == 0))
    {
      announced = left;
      console_printf("seq: warmup %ld s left, die %ld mC\r\n",
                     left, (long)storage_last_temp_mc());
    }
    led_task();
    console_task();
  }
}

static void run_step(char **tok, int ntok, int is_phase, seq_tally_t *t)
{
  /* step  <label> <secs> <odr> <slot> <def|floor> <offset>  <settle> */
  /*
     `phase` is REFUSED, not translated. It used to take <num>/<den> and solve
     for the step count landing nearest that phase, via a 0.512 Delta step size
     that TN-21 excluded at 338 sigma. A plan using it got a phase it had not
     asked for, silently.

     Refusing is deliberate. Accepting the line and reinterpreting the field as
     a step count would run the night at the wrong phases just as quietly; a
     skipped step is visible in the tally and in the console log. Fix the plan
     file, not the firmware.                                (30 July 2026) */
  if (is_phase)
  {
    console_printf("seq: `phase` was removed -- give an explicit step count "
                   "with `step` (TN-21). Skipped: %s\r\n", tok[1] ? tok[1] : "");
    t->skipped++;
    return;
  }

  if (ntok < 7)
  {
    console_printf("seq: too few fields, skipped: %s\r\n", tok[0]);
    t->skipped++;
    return;
  }

  snprintf(s_label, sizeof s_label, "%s", tok[1]);

  storage_rec_t p = {
    .label   = s_label,
    .secs    = strtol(tok[2], NULL, 10),
    .odr_hz  = strtol(tok[3], NULL, 10),
    .slot1   = (int)strtol(tok[4], NULL, 10),
    .aaf_floor = (uint8_t)((strcmp(tok[5], "floor") == 0) ? 1 : 0),
    .offset_user = 0,
    .delay_s = (ntok >= 8) ? strtol(tok[7], NULL, 10) : 0,
  };

  p.offset_user = (int16_t)strtol(tok[6], NULL, 10);

  t->steps++;
  console_printf("seq: [%lu] %s  %ld s @ %ld Hz slot %d %s off %d\r\n",
                 (unsigned long)t->steps, p.label, p.secs, p.odr_hz,
                 p.slot1, p.aaf_floor ? "floor" : "def", (int)p.offset_user);

  int rc = storage_record(&p);
  switch (rc)
  {
    case  0: t->ok++;         break;
    case -4: t->gate_fail++;  break;
    case -2:
    case -3: t->lost++;       break;
    default: t->setup_fail++; break;
  }

  /* Marked, not retried, and never fatal. The record carries its own verdict
     in its header; excision is an analysis decision under rule R2. Aborting
     the night on one transient is the expensive mistake. */
  if (rc != 0)
  {
    console_printf("seq: step %lu returned %d -- marked, continuing\r\n",
                   (unsigned long)t->steps, rc);
  }
}

static int run_plan(void)
{
  if (f_open(&s_f, SEQ_PLAN, FA_READ) != FR_OK)
  {
    console_printf("seq: no plan at %s\r\n", SEQ_PLAN);
    return -1;
  }

  seq_tally_t t = {0};
  uint64_t t_start = timebase_now_us();

  led_clear_faults();
  led_set_mode(LED_MODE_SEQ);

  for (;;)
  {
    int too_long = 0;
    int n = read_line(&s_f, s_line, sizeof s_line, &too_long);
    if (n < 0) { break; }
    if (too_long)
    {
      console_printf("seq: line over %d chars, skipped\r\n", SEQ_LINE_MAX);
      t.skipped++;
      continue;
    }
    if ((s_line[0] == '#') || (s_line[0] == '\0')) { continue; }

    char *tok[10];
    int ntok = split(s_line, tok, 10);
    if (ntok == 0) { continue; }

    if      (strcmp(tok[0], "warmup") == 0 && ntok >= 2)
    {
      warmup(strtol(tok[1], NULL, 10));
    }
    else if (strcmp(tok[0], "step")  == 0) { run_step(tok, ntok, 0, &t); }
    else if (strcmp(tok[0], "phase") == 0) { run_step(tok, ntok, 1, &t); }
    else
    {
      console_printf("seq: unknown directive '%s', skipped\r\n", tok[0]);
      t.skipped++;
    }
  }

  (void)f_close(&s_f);
  led_set_mode(LED_MODE_IDLE);

  uint32_t mins = (uint32_t)((timebase_now_us() - t_start) / 60000000ULL);
  console_printf("seq: done -- %lu steps in %lu min: %lu ok, %lu gate-fail, "
                 "%lu lost, %lu setup-fail, %lu skipped\r\n",
                 (unsigned long)t.steps, (unsigned long)mins,
                 (unsigned long)t.ok, (unsigned long)t.gate_fail,
                 (unsigned long)t.lost, (unsigned long)t.setup_fail,
                 (unsigned long)t.skipped);

  /* Leave a receipt on the card. The console output is gone the moment the
     board is unplugged, and on a battery run nobody was watching it. */
  FIL d;
  if (f_open(&d, SEQ_DONE, FA_CREATE_ALWAYS | FA_WRITE) == FR_OK)
  {
    char b[200];
    int k = snprintf(b, sizeof b,
                     "steps %lu\nok %lu\ngate_fail %lu\nlost %lu\n"
                     "setup_fail %lu\nskipped %lu\nminutes %lu\nfw %s %s\n",
                     (unsigned long)t.steps, (unsigned long)t.ok,
                     (unsigned long)t.gate_fail, (unsigned long)t.lost,
                     (unsigned long)t.setup_fail, (unsigned long)t.skipped,
                     (unsigned long)mins,
                     SHEPPARD_FW_VERSION_STR, SHEPPARD_BUILD_TAG);
    UINT bw = 0;
    (void)f_write(&d, b, (UINT)k, &bw);
    (void)f_close(&d);
  }

  /* Disarm. This is what stops the plan running again when the board is
     plugged back in to offload -- which would overwrite the campaign with a
     second copy, while you watched the first one download. */
  (void)f_unlink(SEQ_ARM);
  console_printf("seq: disarmed\r\n");

  return 0;
}

/* ==========================================================================
 * Console
 * ========================================================================== */

static void cmd_seq(int argc, char **argv)
{
  if (!storage_is_mounted() && (storage_mount() != 0)) { return; }

  if (argc < 2)
  {
    console_printf("usage: seq new | add <line> | plan | arm | disarm | "
                   "run | status\r\n");
    return;
  }

  /* --- building a plan over the link ------------------------------------
     The card cannot be removed, so the plan has to arrive through the same
     console that everything else uses. `new` truncates, `add` appends one
     line. Deliberately dumb: no editing, no line numbers, no partial
     rewrites. A plan is short enough to resend in full, and a half-edited
     plan that ran overnight would be worse than no plan at all. */
  if (strcmp(argv[1], "new") == 0)
  {
    FIL f;
    if (f_open(&f, SEQ_PLAN, FA_CREATE_ALWAYS | FA_WRITE) != FR_OK)
    {
      console_printf("seq: cannot create %s\r\n", SEQ_PLAN);
      return;
    }
    (void)f_close(&f);
    (void)f_unlink(SEQ_ARM);          /* a new plan is never still armed */
    console_printf("seq: plan cleared (and disarmed)\r\n");
    return;
  }

  if (strcmp(argv[1], "add") == 0)
  {
    if (argc < 3)
    {
      console_printf("seq: add what?\r\n");
      return;
    }

    /* Reassemble the tail. The tokeniser has already replaced the separators
       with NULs, so this normalises runs of whitespace to single spaces --
       harmless for the plan format and it keeps the file tidy. */
    int n = 0;
    for (int i = 2; i < argc; i++)
    {
      int k = snprintf(s_line + n, (size_t)(SEQ_LINE_MAX - n), "%s%s",
                       (i > 2) ? " " : "", argv[i]);
      if (k < 0) { break; }
      n += k;
      if (n >= SEQ_LINE_MAX - 2) { break; }
    }
    s_line[n++] = '\n';
    s_line[n]   = '\0';

    FIL f;
    if (f_open(&f, SEQ_PLAN, FA_OPEN_APPEND | FA_WRITE) != FR_OK)
    {
      console_printf("seq: cannot append -- run `seq new` first\r\n");
      return;
    }
    UINT bw = 0;
    FRESULT fr = f_write(&f, s_line, (UINT)n, &bw);
    (void)f_close(&f);

    if ((fr != FR_OK) || (bw != (UINT)n))
    {
      console_printf("seq: write failed\r\n");
      return;
    }
    /* Echo it back. The host uploader checks this, so a line mangled by a
       dropped byte is caught at upload time rather than at 02:00. */
    s_line[n - 1] = '\0';
    console_printf("seq+ %s\r\n", s_line);
    return;
  }

  if (strcmp(argv[1], "plan") == 0)
  {
    if (f_open(&s_f, SEQ_PLAN, FA_READ) != FR_OK)
    {
      console_printf("seq: no plan at %s\r\n", SEQ_PLAN);
      return;
    }
    int n, tl;
    long total = 0;
    while ((n = read_line(&s_f, s_line, sizeof s_line, &tl)) >= 0)
    {
      console_printf("  %s\r\n", s_line);
      /* Rough wall-clock estimate so a plan that cannot finish overnight is
         obvious before it is armed rather than at 07:00. */
      char copy[SEQ_LINE_MAX]; snprintf(copy, sizeof copy, "%s", s_line);
      char *tok[10];
      int nt = split(copy, tok, 10);
      if (nt >= 3 && (strcmp(tok[0], "step") == 0 ||
                      strcmp(tok[0], "phase") == 0))
      {
        total += strtol(tok[2], NULL, 10);
        if (nt >= 8) { total += strtol(tok[7], NULL, 10); }
      }
      else if (nt >= 2 && strcmp(tok[0], "warmup") == 0)
      {
        total += strtol(tok[1], NULL, 10);
      }
    }
    (void)f_close(&s_f);
    console_printf("seq: about %ld min of wall clock\r\n", total / 60);
    return;
  }

  if (strcmp(argv[1], "arm") == 0)
  {
    FIL a;
    if (f_open(&s_f, SEQ_PLAN, FA_READ) != FR_OK)
    {
      console_printf("seq: refusing to arm -- no plan on the card\r\n");
      return;
    }
    (void)f_close(&s_f);
    if (f_open(&a, SEQ_ARM, FA_CREATE_ALWAYS | FA_WRITE) != FR_OK)
    {
      console_printf("seq: could not create the arm marker\r\n");
      return;
    }
    (void)f_close(&a);
    console_printf("seq: ARMED. Unplug USB, then power up from battery.\r\n");
    console_printf("     It will NOT run while VBUS is present.\r\n");
    return;
  }

  if (strcmp(argv[1], "disarm") == 0)
  {
    (void)f_unlink(SEQ_ARM);
    console_printf("seq: disarmed\r\n");
    return;
  }

  if (strcmp(argv[1], "status") == 0)
  {
    FIL a;
    int armed = (f_open(&a, SEQ_ARM, FA_READ) == FR_OK);
    if (armed) { (void)f_close(&a); }
    console_printf("seq: plan %s, %s\r\n",
                   (f_stat(SEQ_PLAN, NULL) == FR_OK) ? "present" : "MISSING",
                   armed ? "ARMED" : "disarmed");
    console_printf("     supply: VBUS %s, host %s -> next boot %s\r\n",
                   sheppard_vbus_present() ? "present" : "absent",
                   console_cdc_ready() ? "enumerated" : "none",
                   armed ? "WOULD AUTORUN unless a host enumerates"
                         : "will not autorun (not armed)");
    return;
  }

  if (strcmp(argv[1], "run") == 0)
  {
    (void)run_plan();
    return;
  }

  console_printf("usage: seq new | add <line> | plan | arm | disarm | "
                 "run | status\r\n");
}

static const console_cmd_t s_cmds[] = {
  { "seq", "seq new|add|plan|arm|disarm|run|status - run sequencer", cmd_seq },
};

void seq_console_init(void)
{
  (void)console_register(s_cmds, (uint8_t)(sizeof s_cmds / sizeof s_cmds[0]));
}

void seq_autorun_if_armed(void)
{
  /* Autorun requires an armed plan AND the absence of a HOST -- not the
     absence of power.

     Three supply cases, and they are not equivalent for noise:
       battery       no VBUS. Quietest supply, but measured WORST for the
                     119 Hz line (1.28 Delta against 0.42 Delta on USB) --
                     losing the cable loses a ground reference.
       charger       VBUS present, nothing ever enumerates. Keeps the ground
                     reference, no host traffic, and the PC can be switched
                     off so its fans stop driving the bench. Best of the three.
       host          VBUS present and CDC enumerates. Someone is at the
                     keyboard; never autorun, or plugging in to offload data
                     would start a campaign on top of the download.

     So the test is enumeration, not VBUS. main() already waits 2.5 s for the
     host before the banner; allow a further margin here for a slow one, because
     mistaking a host for a charger is the expensive direction of this error. */
  if (sheppard_vbus_present())
  {
    uint64_t t0 = timebase_now_us();
    while ((timebase_now_us() - t0) < 8000000ULL)
    {
      if (console_cdc_ready()) { return; }      /* a host -- stand down */
      led_task();
    }
    console_printf("seq: VBUS but no host after 8 s -- treating as charger\r\n");
  }

  if (!storage_is_mounted() && (storage_mount() != 0)) { return; }

  FIL a;
  if (f_open(&a, SEQ_ARM, FA_READ) != FR_OK) { return; }
  (void)f_close(&a);

  console_printf("seq: battery boot with an armed plan -- starting in 30 s\r\n");
  uint64_t t0 = timebase_now_us();
  while ((timebase_now_us() - t0) < 30000000ULL) { led_task(); }

  (void)run_plan();
}
