/**
  ******************************************************************************
  * @file    validate.h
  * @brief   Validation Zero harness -- the gating measurements.
  *
  * These are not logger features. They are the measurements TN-13 and the
  * Hardware Notes call "Validation Zero", which gate the campaign design and
  * must report before the run matrix is frozen.
  *
  *   V0.4  Is the 16-bit register a memoryless rounder of the fine word?
  *         ANSWERED 28 Jul 2026: no -- it is bits [19:4], a truncation.
  *         450 discriminating axis-samples at ODR 25/100/1000, all floor.
  *         (Harness lives in imu_icm42688.c as the `fifo` command.)
  *
  *   M1    Does sigma fall as sqrt(ODR) under GYRO_UI_FILT_BW = 0, or does it
  *         plateau near sigma_a * sqrt(42) because the AAF, whose cutoff is
  *         absolute, is what actually bandlimits at low ODR?
  *         OPEN. Gates the low-ODR axis, which TN-13 section 8 calls the
  *         study's primary evidential channel.
  *
  * M1 is computed on-device and printed. It needs no SD card, no record
  * format and no sequencer -- sigma is a two-accumulator calculation, and
  * putting it behind the storage stack would have delayed the one result that
  * can still invalidate the campaign matrix.
  ******************************************************************************
  */

#ifndef VALIDATE_H
#define VALIDATE_H

#ifdef __cplusplus
extern "C" {
#endif

/** Register the `m1` console command. */
void validate_console_init(void);

#ifdef __cplusplus
}
#endif

#endif /* VALIDATE_H */
