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
  * WHY THE DRAIN IS A CHAIN, AND WHY IT RUNS IN PendSV
  *   A fixed-length read sized to the watermark can leave the FIFO still above
  *   threshold. INT1 is PULSED, so there is then no further transition and no
  *   further interrupt: the stream latches and dies silently. The drain must
  *   therefore read FIFO_COUNT and keep going until the FIFO is below
  *   threshold, which is two or more chained SPI transactions.
  *
  *   Those transactions must NOT be issued from inside the SPI DMA completion
  *   callback. HAL_SPI_TransmitReceive_DMA arms the RX stream, then the TX
  *   stream. TX and RX are separate NVIC lines at equal priority (SPI1: 58 and
  *   59), so when the RX completion handler runs the TX handler is still
  *   pending and hdmatx->State is still BUSY. Re-arming from there fails at the
  *   TX start -- and the HAL returns without un-arming RX, leaving hdmarx->State
  *   BUSY for ever. The slot is then dead for the rest of the run.
  *
  *   So each chain step is deferred to PendSV. PendSV tail-chains after every
  *   pending interrupt has been serviced, which is exactly the condition the
  *   HAL needs, and being an exception it still preempts thread mode -- so the
  *   drain continues through a 33 ms f_write stall, which was the whole point
  *   of not using the main loop.
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
  uint32_t bus_busy;        /* starts refused: previous DMA still in flight */
  uint32_t start_err;       /* starts that failed outright (HAL error)      */
  uint32_t faults;          /* DMA/SPI errors reported by the bus layer     */
  uint32_t watchdog_kicks;  /* times the pulsed interrupt had to be revived */
  uint32_t chained;         /* drains that had to go round again            */
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
int sampler_start(bus_slot_t slot, uint16_t watermark_bytes, long odr_hz);

/** Disarm. Safe to call when not running. */
void sampler_stop(void);

/** Called from HAL_GPIO_EXTI_Callback. Interrupt context. */
void sampler_on_int(uint16_t gpio_pin);

/**
  * @brief  Runs the next step of the drain chain. Called from PendSV_Handler
  *         and nowhere else. See the chain note at the top of this file for why
  *         the step cannot be issued from the DMA completion callback itself.
  */
void sampler_pendsv(void);

/**
  * @brief  Main-loop watchdog. Call alongside storage_task() while recording.
  *
  *         INT1 is pulsed, so the threshold interrupt fires on the transition
  *         across the watermark. Miss one service and the FIFO fills to 2 KiB,
  *         sits permanently above threshold in stream mode, and never pulses
  *         again -- the stream dies silently. This revives it, and counts the
  *         samples lost in the interval as the gap they are.
  */
void sampler_poll(void);

int  sampler_running(void);
void sampler_get_stats(sampler_stats_t *out);

/** Samples the sensor produced but the sampler could not take, i.e. gaps. */
uint32_t sampler_lost_packets(void);

#ifdef __cplusplus
}
#endif

#endif /* SAMPLER_H */
