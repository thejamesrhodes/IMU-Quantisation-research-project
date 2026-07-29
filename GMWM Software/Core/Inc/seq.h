/**
  ******************************************************************************
  * @file    seq.h
  * @brief   Unattended run sequencer, driven by a plan on the SD card.
  *
  * WHY THE PLAN LIVES ON THE CARD
  *   The quietest configuration this bench can reach is battery power with no
  *   USB cable attached at any point -- no host switch-mode supply, no ground
  *   loop, no mechanical tether. But console INPUT only arrives over CDC, so a
  *   board running on battery cannot be told what to do.
  *
  *   So it is told in advance. The plan is a text file on the card, armed from
  *   the console while USB is connected, and executed at boot when VBUS is
  *   absent. Write the plan, arm it, unplug, power up from battery, walk away.
  *
  * WHY IT DISARMS ITSELF
  *   The plan must not run again when the board is plugged back in to offload
  *   data -- that would overwrite the card with a second copy of the campaign
  *   and, worse, do it while you were watching the first one download. Arming
  *   is a separate marker file, deleted the moment the sequence completes, and
  *   auto-run additionally requires VBUS to be absent. Two independent
  *   conditions, either of which prevents an accidental restart.
  *
  * PLAN FORMAT
  *   One directive per line, '#' begins a comment. Unknown lines are reported
  *   and skipped rather than silently ignored.
  *
  *     warmup <seconds>
  *         Idle with the sensor running before the first record. The board
  *         self-heats: 6.8 K/h was measured shortly after handling against a
  *         0.78 K/h gate at ODR 25 (TN-19). Without this every low-ODR step
  *         fails R2.
  *
  *     step <label> <secs> <odr> <slot> <def|floor> <offset> <settle>
  *         One record. `offset` is an OFFSET_USER step count; use `phase N/D`
  *         below if you would rather specify the phase itself.
  *
  *     phase <label> <secs> <odr> <slot> <def|floor> <num>/<den> <settle>
  *         As `step`, but the offset is computed to land on phase num/den --
  *         the register is coarser than one LSB, so the step count that
  *         achieves a given phase is not obvious (see ICM_OFFSET_USER0).
  *
  *   A step that fails its thermal gate or overflows is MARKED AND SKIPPED
  *   PAST, not retried and not fatal: the record is already flagged in its own
  *   header, excision belongs to analysis under rule R2, and an overnight run
  *   that aborts at 02:00 on one transient costs the whole night.
  ******************************************************************************
  */

#ifndef SEQ_H
#define SEQ_H

#ifdef __cplusplus
extern "C" {
#endif

/** Register the `seq` command. Call once from main(). */
void seq_console_init(void);

/**
  * @brief  Run the armed plan if this is a battery boot. Call once from main()
  *         after the card and console are up.
  *
  *         Does nothing when VBUS is present, so plugging in to offload data
  *         can never start a campaign.
  */
void seq_autorun_if_armed(void);

#ifdef __cplusplus
}
#endif

#endif /* SEQ_H */
