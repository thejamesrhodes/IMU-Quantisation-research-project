/**
  ******************************************************************************
  * @file    bus.c
  * @brief   SPI transport for the four sensor slots.
  ******************************************************************************
  */

#include "bus.h"
#include "main.h"
#include "sheppard_config.h"

#include <string.h>

extern SPI_HandleTypeDef hspi1;   /* slot 1  ICM */
extern SPI_HandleTypeDef hspi3;   /* slot 2  ICM */
extern SPI_HandleTypeDef hspi5;   /* slot 3  ISM */
extern SPI_HandleTypeDef hspi4;   /* slot 4  BMI */

/* ==========================================================================
 * Slot table
 *
 * The bus-to-chip-select pairing below is the highest-cost error recorded in
 * TN-16 (section 1.2). Net labels SCK_3/MISO_3/MOSI_3 belong to SPI5 and
 * SCK_4/... to SPI4: the label number is the physical slot, not the
 * peripheral. Getting it wrong gives every register as 0x00 or 0xFF, stable
 * across the whole address space, which looks exactly like dead silicon.
 * ========================================================================== */

typedef struct {
  SPI_HandleTypeDef *hspi;
  GPIO_TypeDef      *cs_port;
  uint16_t           cs_pin;
  uint8_t            has_dma;
} bus_cfg_t;

static const bus_cfg_t s_cfg[BUS_SLOT_COUNT] = {
  { &hspi1, CS_1_GPIO_Port, CS_1_Pin, 1 },   /* slot 1  SPI1  ICM  DMA2 2/3 */
  { &hspi3, CS_2_GPIO_Port, CS_2_Pin, 1 },   /* slot 2  SPI3  ICM  DMA1 0/5 */
  { &hspi5, CS_3_GPIO_Port, CS_3_Pin, 0 },   /* slot 3  SPI5  ISM  polled */
  { &hspi4, CS_4_GPIO_Port, CS_4_Pin, 0 },   /* slot 4  SPI4  BMI  polled */
};

typedef struct {
  volatile uint8_t  busy;
  bus_done_fn       cb;
  void             *ctx;
  volatile uint32_t overruns;
  volatile uint32_t faults;
  volatile uint32_t completions;
} bus_state_t;

static bus_state_t s_st[BUS_SLOT_COUNT];

/* Absorbs returned bytes when the caller does not want them. Not static-const
   because the SPI peripheral writes into it. Lives in .bss, hence SRAM1. */
static uint8_t s_sink[BUS_MAX_XFER];

/* ==========================================================================
 * Helpers
 * ========================================================================== */

static inline int slot_valid(bus_slot_t s)
{
  return ((int)s >= 0) && ((int)s < (int)BUS_SLOT_COUNT);
}

static inline void cs_assert(const bus_cfg_t *c)
{
  HAL_GPIO_WritePin(c->cs_port, c->cs_pin, GPIO_PIN_RESET);
}

static inline void cs_release(const bus_cfg_t *c)
{
  HAL_GPIO_WritePin(c->cs_port, c->cs_pin, GPIO_PIN_SET);
}

static int slot_of(const SPI_HandleTypeDef *hspi)
{
  for (int i = 0; i < (int)BUS_SLOT_COUNT; i++)
  {
    if (s_cfg[i].hspi == hspi)
    {
      return i;
    }
  }
  return -1;
}

/* Ends a transfer: release CS, clear busy, then hand up. CS is released
   BEFORE the callback so that a callback which immediately starts another
   transfer on the same slot sees a clean bus. */
static void finish(int slot, int status)
{
  cs_release(&s_cfg[slot]);
  s_st[slot].busy = 0U;

  if (status == BUS_OK)
  {
    s_st[slot].completions++;
  }
  else
  {
    s_st[slot].faults++;
  }

  bus_done_fn cb = s_st[slot].cb;
  void *ctx = s_st[slot].ctx;
  s_st[slot].cb = NULL;

  if (cb != NULL)
  {
    cb((bus_slot_t)slot, status, ctx);
  }
}

/* ==========================================================================
 * Public API
 * ========================================================================== */

/* --------------------------------------------------------------------------
 * SPI clock normalisation
 *
 * Rule R8 controls bus activity as a confound, and the specimen comparison is
 * only meaningful if the two ICMs are read over identical buses. They were not:
 * SPI1/4/5 sit on APB2 and SPI3 on APB1, both clocked at 32 MHz here because
 * APB1CLKDivider is RCC_HCLK_DIV1, and CubeMX had SPI3 at /2 against /4 for the
 * rest. Slot 2 therefore ran at 16 MHz against slot 1's 8 MHz, which would have
 * built a bus-rate difference into the specimen axis. (TN-16 section 2 records
 * APB1 as 16 MHz, which is also wrong -- worth correcting there.)
 *
 * Computed from the live peripheral clock rather than hard-coded, so a future
 * change to the clock tree cannot silently reintroduce the mismatch. This lives
 * here rather than in the .ioc because CubeMX regeneration has twice reverted
 * settings in this project; bus.c is not generated.
 * -------------------------------------------------------------------------- */

static uint32_t presc_for(uint32_t pclk_hz, uint32_t target_hz, uint32_t *got)
{
  /* SPI_CR1_BR is a power-of-two divider, 2 to 256. Pick the smallest divider
     whose result does not exceed the target, so every bus lands on exactly the
     same frequency rather than merely close to it. */
  static const uint32_t code[8] = {
    SPI_BAUDRATEPRESCALER_2,   SPI_BAUDRATEPRESCALER_4,
    SPI_BAUDRATEPRESCALER_8,   SPI_BAUDRATEPRESCALER_16,
    SPI_BAUDRATEPRESCALER_32,  SPI_BAUDRATEPRESCALER_64,
    SPI_BAUDRATEPRESCALER_128, SPI_BAUDRATEPRESCALER_256
  };

  for (int i = 0; i < 8; i++)
  {
    uint32_t f = pclk_hz >> (i + 1);
    if (f <= target_hz)
    {
      if (got != NULL) { *got = f; }
      return code[i];
    }
  }
  if (got != NULL) { *got = pclk_hz >> 8; }
  return code[7];
}

static int normalise_clock(SPI_HandleTypeDef *hspi, uint32_t *got)
{
  /* SPI2 and SPI3 hang off APB1; SPI1, SPI4, SPI5 and SPI6 off APB2. */
  uint32_t pclk = ((hspi->Instance == SPI2) || (hspi->Instance == SPI3))
                    ? HAL_RCC_GetPCLK1Freq()
                    : HAL_RCC_GetPCLK2Freq();

  uint32_t presc = presc_for(pclk, SHEPPARD_SPI_HZ, got);
  if (hspi->Init.BaudRatePrescaler == presc)
  {
    return 0;                                   /* already correct */
  }

  hspi->Init.BaudRatePrescaler = presc;
  return (HAL_SPI_Init(hspi) == HAL_OK) ? 1 : -1;
}

int bus_init(void)
{
  for (int i = 0; i < (int)BUS_SLOT_COUNT; i++)
  {
    memset((void *)&s_st[i], 0, sizeof s_st[i]);
    cs_release(&s_cfg[i]);
    (void)normalise_clock(s_cfg[i].hspi, NULL);
  }
  return BUS_OK;
}

uint32_t bus_clock_hz(bus_slot_t slot)
{
  if (!slot_valid(slot)) { return 0U; }

  const SPI_HandleTypeDef *h = s_cfg[slot].hspi;
  uint32_t pclk = ((h->Instance == SPI2) || (h->Instance == SPI3))
                    ? HAL_RCC_GetPCLK1Freq()
                    : HAL_RCC_GetPCLK2Freq();

  /* BR field is bits 5:3 of CR1, encoding a shift of (BR + 1). */
  uint32_t br = (h->Instance->CR1 >> 3) & 0x7U;
  return pclk >> (br + 1U);
}

int bus_has_dma(bus_slot_t slot)
{
  return slot_valid(slot) ? (int)s_cfg[slot].has_dma : 0;
}

int bus_busy(bus_slot_t slot)
{
  return slot_valid(slot) ? (int)s_st[slot].busy : 1;
}

uint32_t bus_overruns(bus_slot_t slot)
{
  return slot_valid(slot) ? s_st[slot].overruns : 0U;
}

uint32_t bus_faults(bus_slot_t slot)
{
  return slot_valid(slot) ? s_st[slot].faults : 0U;
}

uint32_t bus_completions(bus_slot_t slot)
{
  return slot_valid(slot) ? s_st[slot].completions : 0U;
}

void bus_clear_stats(bus_slot_t slot)
{
  if (!slot_valid(slot))
  {
    return;
  }
  s_st[slot].overruns    = 0U;
  s_st[slot].faults      = 0U;
  s_st[slot].completions = 0U;
}

int bus_xfer_async(bus_slot_t slot, const uint8_t *tx, uint8_t *rx,
                   uint16_t len, bus_done_fn cb, void *ctx)
{
  if (!slot_valid(slot) || (tx == NULL) || (len == 0U) || (len > BUS_MAX_XFER))
  {
    return BUS_E_ARG;
  }

  const bus_cfg_t *c = &s_cfg[slot];
  bus_state_t     *st = &s_st[slot];

  /* Claim the slot atomically. Losing the race is an overrun: the sample the
     caller wanted does not exist and must be counted as a gap, not retried.
     Retrying would return data whose timestamp no longer matches its trigger,
     and the timestamp-to-sample relationship is the whole point of TN-16
     section 10.3. */
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  if (st->busy)
  {
    st->overruns++;
    if (primask == 0U) { __enable_irq(); }
    return BUS_E_BUSY;
  }
  st->busy = 1U;
  if (primask == 0U) { __enable_irq(); }

  st->cb  = cb;
  st->ctx = ctx;

  uint8_t *dst = (rx != NULL) ? rx : s_sink;

  cs_assert(c);

  if (c->has_dma)
  {
    if (HAL_SPI_TransmitReceive_DMA(c->hspi, (uint8_t *)tx, dst, len) != HAL_OK)
    {
      /* A failed start is not necessarily harmless: HAL_SPI_TransmitReceive_DMA
         arms the RX stream BEFORE the TX stream, and if the TX start fails it
         returns without un-arming RX. hdmarx->State is then left BUSY for ever
         and every subsequent transfer on this slot fails at the first
         HAL_DMA_Start_IT -- the slot is bricked until reset.
         That is precisely what happened on 28 July: one chained read issued
         from inside HAL_SPI_TxRxCpltCallback failed (the other stream's IRQ was
         still pending, so its state was BUSY), and the remaining 49 attempts in
         the record all failed instantly. Aborting here returns both streams and
         the SPI state machine to READY, so a failed start costs one read rather
         than the whole record. */
      (void)HAL_SPI_Abort(c->hspi);
      finish((int)slot, BUS_E_FAULT);
      return BUS_E_FAULT;
    }
    return BUS_OK;                      /* completion arrives in the DMA ISR */
  }

  /* Polled slot. The transfer runs here and the callback fires before we
     return -- documented in bus.h, because a caller that assumes deferral
     would be wrong on slots 3 and 4. */
  HAL_StatusTypeDef hs =
      HAL_SPI_TransmitReceive(c->hspi, (uint8_t *)tx, dst, len, 100U);

  finish((int)slot, (hs == HAL_OK) ? BUS_OK : BUS_E_FAULT);
  return (hs == HAL_OK) ? BUS_OK : BUS_E_FAULT;
}

/* --- blocking wrapper ------------------------------------------------------
 * Main loop only. Spins on the busy flag, which never clears if this is
 * called from an interrupt that outranks the DMA completion.
 * -------------------------------------------------------------------------- */

static volatile int s_block_status[BUS_SLOT_COUNT];

static void block_done(bus_slot_t slot, int status, void *ctx)
{
  (void)ctx;
  s_block_status[slot] = status;
}

int bus_xfer(bus_slot_t slot, const uint8_t *tx, uint8_t *rx,
             uint16_t len, uint32_t timeout_ms)
{
  if (!slot_valid(slot))
  {
    return BUS_E_ARG;
  }

  s_block_status[slot] = BUS_E_TIMEOUT;

  int rc = bus_xfer_async(slot, tx, rx, len, block_done, NULL);
  if (rc != BUS_OK)
  {
    return rc;
  }

  if (!s_cfg[slot].has_dma)
  {
    return s_block_status[slot];        /* already completed inline */
  }

  uint32_t t0 = HAL_GetTick();
  while (s_st[slot].busy)
  {
    if ((HAL_GetTick() - t0) > timeout_ms)
    {
      /* Abandon it. HAL_SPI_Abort tears down the DMA and, on this path,
         does not invoke the completion callback -- so release the slot here
         or it stays busy for ever. */
      (void)HAL_SPI_Abort(s_cfg[slot].hspi);
      cs_release(&s_cfg[slot]);
      s_st[slot].busy = 0U;
      s_st[slot].cb   = NULL;
      s_st[slot].faults++;
      return BUS_E_TIMEOUT;
    }
  }

  return s_block_status[slot];
}

/* ==========================================================================
 * HAL callbacks
 *
 * These override __weak HAL definitions and must not be static. Only the
 * slots configured for DMA reach them; polled slots complete inside
 * bus_xfer_async.
 * ========================================================================== */

void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef *hspi)
{
  int slot = slot_of(hspi);
  if (slot >= 0)
  {
    finish(slot, BUS_OK);
  }
}

void HAL_SPI_ErrorCallback(SPI_HandleTypeDef *hspi)
{
  int slot = slot_of(hspi);
  if (slot >= 0)
  {
    finish(slot, BUS_E_FAULT);
  }
}
