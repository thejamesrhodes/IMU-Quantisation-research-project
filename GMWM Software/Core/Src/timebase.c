/**
  ******************************************************************************
  * @file    timebase.c
  * @brief   Microsecond timebase for sample timestamping.
  ******************************************************************************
  */

#include "timebase.h"
#include "main.h"

extern TIM_HandleTypeDef htim2;

/* High word of the 64-bit tick. Written only by the TIM2 update ISR. */
static volatile uint32_t s_hi = 0U;

/* ==========================================================================
 * Start-up
 * ========================================================================== */

int timebase_init(void)
{
  s_hi = 0U;

  __HAL_TIM_SET_COUNTER(&htim2, 0U);
  __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);

  if (HAL_TIM_Base_Start_IT(&htim2) != HAL_OK)
  {
    return -1;
  }
  return 0;
}

/* ==========================================================================
 * Wrap interrupt
 *
 * Overrides the __weak HAL default. Safe to define here because SysTick, not
 * a timer, is the HAL tick source -- if a TIM were ever made the tick source
 * this callback would be shared and would need demultiplexing beyond the
 * instance check below.
 * ========================================================================== */

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    s_hi++;
  }
}

uint32_t timebase_wraps(void)
{
  return s_hi;
}

/* ==========================================================================
 * Reading the 64-bit tick
 *
 * The obvious "read high, read low, read high again, retry if changed" idiom
 * is NOT sufficient here, and the failure it misses is the one that matters.
 *
 * Consider: the counter wraps; the TIM2 update ISR (preempt priority 1) is
 * held off because an EXTI data-ready ISR (priority 0) is running; and that
 * EXTI handler calls this function to timestamp a sample. Both reads of the
 * high word return the stale value, they agree, and the retry loop is
 * satisfied -- returning a timestamp 2^32 us = 71.6 minutes in the past.
 *
 * That is not a hypothetical ordering. Timestamping from the data-ready ISR
 * is precisely what TN-16 section 10.3 requires, so the sampler will call
 * this from priority 0 on every sample.
 *
 * The fix is to consult the hardware rather than the software mirror: if the
 * update flag is pending, the wrap has happened whether or not the ISR has
 * run. The counter value disambiguates the two orderings, because CNT is read
 * first:
 *
 *   CNT small + UIF set  -> read happened after the wrap; the high word is
 *                           one behind, so add one
 *   CNT large + UIF set  -> read happened before the wrap; the flag refers to
 *                           an event later than our sample, so do not adjust
 *
 * The half-range split is safe by an enormous margin: it would take 35 minutes
 * of interrupt latency to be wrong.
 * ========================================================================== */

uint64_t timebase_now_us(void)
{
  uint32_t hi, lo;
  uint32_t primask = __get_PRIMASK();

  __disable_irq();

  lo = TIM2->CNT;
  hi = s_hi;

  if (((TIM2->SR & TIM_SR_UIF) != 0U) && (lo < 0x80000000UL))
  {
    hi++;
  }

  if (primask == 0U)
  {
    __enable_irq();
  }

  return ((uint64_t)hi << 32) | (uint64_t)lo;
}

/* ==========================================================================
 * Short delays
 * ========================================================================== */

void timebase_delay_us(uint32_t us)
{
  uint64_t t0 = timebase_now_us();
  while ((timebase_now_us() - t0) < (uint64_t)us)
  {
    /* spin */
  }
}
