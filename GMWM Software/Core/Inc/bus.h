/**
  ******************************************************************************
  * @file    bus.h
  * @brief   SPI transport for the four sensor slots.
  *
  * One API for all four slots; DMA underneath where it is configured, polled
  * where it is not, with identical semantics either way.
  *
  * SLOT MAP  (TN-16 section 1.2 -- the label number is the PHYSICAL SLOT, not
  * the peripheral number, and pairing them wrongly produces symptoms
  * indistinguishable from dead hardware)
  *
  *   slot 1   SPI1   CS_1   ICM-42688-P    DMA2 stream 2/3
  *   slot 2   SPI3   CS_2   ICM-42688-P    DMA1 stream 0/5
  *   slot 3   SPI5   CS_3   ISM330DHCX     polled
  *   slot 4   SPI4   CS_4   BMI323         polled
  *
  * WHY ONLY SLOTS 1 AND 2 GET DMA
  *   They are the specimens the campaign logs at rate. Slots 3 and 4 are
  *   positive controls at ~100 Hz, where a 20 us polled burst is irrelevant,
  *   and both their peripherals sit on DMA2 where they would compete with the
  *   streams SDMMC2 needs. DMA does not improve timestamp accuracy -- the
  *   timestamp is taken in the data-ready ISR before any transfer starts.
  *
  * SPI CLOCK IS A TREATMENT VARIABLE
  *   8 MHz, fixed. Raising it would shorten bursts, but TN-14 section 4.3 makes
  *   bus activity a controlled confound (rule R8): supply coupling from SPI
  *   bursts is an ODR-correlated artefact that mimics an ODR-dependent noise
  *   term. Do not change it without logging it as a treatment.
  *
  * BUFFERS MUST BE DMA-REACHABLE
  *   That is, in SRAM1/SRAM2, not DTCM. Since the 27 July linker split all of
  *   .data and .bss lives at 0x20010000 and above, so this is satisfied by
  *   construction -- but a buffer explicitly placed in .dtcm would fail.
  ******************************************************************************
  */

#ifndef BUS_H
#define BUS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
  BUS_SLOT_1 = 0,
  BUS_SLOT_2,
  BUS_SLOT_3,
  BUS_SLOT_4,
  BUS_SLOT_COUNT
} bus_slot_t;

/* Return codes. Negative is failure; the distinction matters because the two
   failures are counted separately and mean different things in a record. */
#define BUS_OK          0
#define BUS_E_BUSY    (-1)   /* a transfer was already in flight -- an overrun */
#define BUS_E_FAULT   (-2)   /* SPI or DMA reported an error                   */
#define BUS_E_ARG     (-3)   /* bad slot, null buffer, zero length             */
#define BUS_E_TIMEOUT (-4)

/**
  * @brief  Completion callback. Runs in DMA interrupt context on slots 1-2 and
  *         synchronously on slots 3-4. Treat it as an ISR either way: no SPI,
  *         no HAL_Delay, no console output (TN-16 section 9.3).
  * @param  status BUS_OK or BUS_E_FAULT.
  */
typedef void (*bus_done_fn)(bus_slot_t slot, int status, void *ctx);

/**
  * @brief  Initialise. Call once from main(), after the MX_SPIx_Init() calls
  *         and MX_DMA_Init(). Deasserts every chip select.
  */
int bus_init(void);

/**
  * @brief  Full-duplex transfer, blocking. MAIN LOOP ONLY -- it spins waiting
  *         for completion and will deadlock if called from an ISR.
  *
  * @param  tx  bytes to send; must not be NULL
  * @param  rx  receive buffer; may be NULL for write-only, in which case an
  *             internal scratch buffer absorbs the returned bytes
  * @param  len 1..BUS_MAX_XFER
  */
int bus_xfer(bus_slot_t slot, const uint8_t *tx, uint8_t *rx,
             uint16_t len, uint32_t timeout_ms);

/**
  * @brief  Full-duplex transfer, non-blocking. Safe from an ISR.
  *
  *         On a DMA slot this returns immediately and `cb` fires from the DMA
  *         completion interrupt. On a polled slot the transfer runs inline and
  *         `cb` fires before this function returns -- so callers must not
  *         assume the callback is deferred.
  *
  *         `tx` and `rx` must remain valid until the callback fires.
  *
  * @retval BUS_E_BUSY if a transfer is already in flight on this slot. That is
  *         an overrun: the sample is lost, the counter increments, and the
  *         caller should record a gap rather than retry.
  */
int bus_xfer_async(bus_slot_t slot, const uint8_t *tx, uint8_t *rx,
                   uint16_t len, bus_done_fn cb, void *ctx);

/** Non-zero while a transfer is in flight. */
int bus_busy(bus_slot_t slot);

/** Overruns since the last clear: transfers refused because the slot was busy. */
uint32_t bus_overruns(bus_slot_t slot);

/** Faults since the last clear: SPI or DMA errors reported by the HAL. */
uint32_t bus_faults(bus_slot_t slot);

/** Completed transfers since the last clear. Denominator for the rate checks. */
uint32_t bus_completions(bus_slot_t slot);

/** Reset the counters. Call at the start of every record. */
void bus_clear_stats(bus_slot_t slot);

/** Non-zero if this slot's transfers use DMA. */
int bus_has_dma(bus_slot_t slot);

/** Largest single transfer.
 *
 *  Sized to drain the ICM's entire 2 KiB FIFO in one burst, plus the leading
 *  address byte. That matters: the sampler must be able to empty the FIFO
 *  completely in a single read, because the threshold interrupt is PULSED and
 *  fires only on the transition across the watermark. A read that leaves the
 *  FIFO above threshold produces no further transition and the stream latches
 *  until something notices -- which is exactly how the first two ODR 8000
 *  attempts died. */
#define BUS_MAX_XFER  2064U

#ifdef __cplusplus
}
#endif

#endif /* BUS_H */
