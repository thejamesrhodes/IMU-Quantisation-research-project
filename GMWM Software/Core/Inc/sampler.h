/**
  ******************************************************************************
  * @file    sampler.h
  * @brief   FIFO watermark interrupt -> DMA -> ring, in interrupt context.
  *
  * FLOW
  *   ICM asserts INT1 when the FIFO reaches the watermark
  *     -> EXTI handler captures TIM2 immediately, before any SPI activity
  *        (TN-16 section 10.3: main-loop capture injects variable latency;
  *        ISR entry latency is ~1-2 us and near-constant, so it appears as a
  *        fixed offset rather than jitter)
  *     -> bus_xfer_async starts a DMA burst read of exactly the watermark
  *     -> DMA completion copies the payload into the storage ring and commits
  *
  *   Nothing blocks, so the FIFO keeps draining while the main loop is stalled
  *   inside an SD write. That is the entire reason this is not a polled loop:
  *   the ICM FIFO is 2 KiB, which is 12.8 ms at ODR 8000, and TN-16 section
  *   6.4 warns SD writes stall for "tens to hundreds of ms".
  *
  * WHY A FIXED-LENGTH READ
  *   The watermark guarantees at least that many bytes are present, so the
  *   length is known without first reading FIFO_COUNT -- which would mean a
  *   second chained SPI transaction inside the ISR. Reading exactly the
  *   watermark per interrupt keeps the sampler in balance with the sensor: one
  *   interrupt per watermark-worth of new samples, one watermark-worth read.
  *   Any backlog present at start is removed by flushing before arming.
  *
  * INT1 CARRIES THE WATERMARK ONLY
  *   Not data-ready as well. Both can be routed to INT1, but distinguishing
  *   them needs a read of INT_STATUS -- an SPI transaction, forbidden in the
  *   ISR by TN-16 section 9.3. Only INT1 is routed per slot on Sheppard
  *   (TN-16 section 1.2), so the choice is forced. INT2 routing is on the
  *   rev-B list.
  ******************************************************************************
  */

#ifndef SAMPLER_H
#define SAMPLER_H

#include <stdint.h>
#include "bus.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  uint32_t interrupts;      /* watermark IRQs seen                          */
  uint32_t reads_started;
  uint32_t reads_done;
  uint32_t ring_full;       /* IRQs dropped: storage had no room            */
  uint32_t bus_busy;        /* IRQs dropped: previous DMA still in flight   */
  uint32_t faults;          /* DMA/SPI errors                               */
} sampler_stats_t;

/**
  * @brief  Watermark in bytes for a given ODR, per the policy in
  *         sheppard_config.h: ~100 ms of samples, capped at
  *         SHEPPARD_WM_MAX_BYTES, always a whole number of packets.
  */
uint16_t sampler_watermark_for(long odr_hz);

/**
  * @brief  Arm the sampler. Configures the FIFO watermark and INT1, flushes
  *         the FIFO, and enables the interrupt. A record must already be open,
  *         because committed blocks go straight into the storage ring.
  */
int sampler_start(bus_slot_t slot, uint16_t watermark_bytes);

/** Disarm. Safe to call when not running. */
void sampler_stop(void);

/** Called from HAL_GPIO_EXTI_Callback. Interrupt context. */
void sampler_on_int(uint16_t gpio_pin);

int  sampler_running(void);
void sampler_get_stats(sampler_stats_t *out);

/** Samples the sensor produced but the sampler could not take, i.e. gaps. */
uint32_t sampler_lost_packets(void);

#ifdef __cplusplus
}
#endif

#endif /* SAMPLER_H */
