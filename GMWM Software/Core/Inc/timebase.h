/**
  ******************************************************************************
  * @file    timebase.h
  * @brief   Microsecond timebase for sample timestamping.
  *
  * TIM2 free-running at 1 MHz, extended to 64 bits in software.
  *
  * WHY 64 BITS
  *   The 32-bit counter wraps every 71.6 minutes. TN-16 section 10.3 specified
  *   TIM2 on the basis that "a 20-minute record never wraps" -- true for the
  *   ODR axis, but TN-13 block 10 calls for 12-hour bias-instability records,
  *   which wrap ten times. A wrapped timestamp inside a record looks like a
  *   71-minute backwards jump and would silently corrupt the Allan analysis at
  *   long tau, which is exactly where those records carry their evidence.
  *
  * WHY NOT SysTick
  *   1 ms resolution against a 125 us sample period at 8 kHz. Useless.
  *
  * WHY CAPTURE IN THE ISR
  *   TN-16 section 10.3: main-loop capture injects variable latency up to the
  *   loop period. ISR entry latency is ~1-2 us and near-constant, so it shows
  *   up as a fixed offset rather than jitter -- and jitter is the thing the
  *   timestamps exist to measure.
  *
  * All functions here are safe to call from interrupt context.
  ******************************************************************************
  */

#ifndef TIMEBASE_H
#define TIMEBASE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
  * @brief  Start the timebase. Call once from main(), after MX_TIM2_Init().
  * @retval 0 on success, -1 if the timer would not start.
  */
int timebase_init(void);

/**
  * @brief  Microseconds since timebase_init(). Monotonic for 584,000 years.
  *         Race-free against the wrap interrupt; safe from any context.
  */
uint64_t timebase_now_us(void);

/**
  * @brief  Microseconds elapsed since an earlier timebase_now_us() value.
  */
static inline uint64_t timebase_since_us(uint64_t then)
{
  return timebase_now_us() - then;
}

/**
  * @brief  Busy-wait. For short sensor timing only -- microseconds, not
  *         milliseconds. Use HAL_Delay for anything longer.
  */
void timebase_delay_us(uint32_t us);

/**
  * @brief  Number of counter wraps observed. Diagnostic; a record spanning
  *         more than one is normal for the long bias-instability captures and
  *         is the case the 64-bit extension exists for.
  */
uint32_t timebase_wraps(void);

#ifdef __cplusplus
}
#endif

#endif /* TIMEBASE_H */
