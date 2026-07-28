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

int bus_init(void)
{
  for (int i = 0; i < (int)BUS_SLOT_COUNT; i++)
  {
    memset((void *)&s_st[i], 0, sizeof s_st[i]);
    cs_release(&s_cfg[i]);
  }
  return BUS_OK;
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
