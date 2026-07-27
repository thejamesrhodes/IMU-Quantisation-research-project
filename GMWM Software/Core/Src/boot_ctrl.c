/**
  ******************************************************************************
  * @file    boot_ctrl.c
  * @brief   Boot-mode handshake between the application and the DFU loader.
  ******************************************************************************
  */

#include "boot_ctrl.h"
#include "sheppard_config.h"
#include "console.h"

extern RTC_HandleTypeDef hrtc;

/* ---- module state ------------------------------------------------------- */

static uint32_t s_attempts_at_boot = 0U;   /* value the loader left behind     */
static uint8_t  s_healthy          = 0U;   /* counter has been cleared         */
static uint8_t  s_dfu_pending      = 0U;   /* reset scheduled                  */
static uint32_t s_dfu_reset_at     = 0U;   /* HAL tick at which to reset       */
static uint32_t s_boot_tick        = 0U;

/* ---- backup register access ---------------------------------------------
 * HAL_PWR_EnableBkUpAccess() normally lives in HAL_RTC_MspInit(). TN-16 SS8.2
 * records that if it is missing, BKUPWrite silently does nothing -- the write
 * is discarded with no error and the failure only shows up as "DFU request
 * ignored". Calling it again here is free and removes that dependency.
 * ------------------------------------------------------------------------- */

static void bkp_enable_access(void)
{
  __HAL_RCC_PWR_CLK_ENABLE();
  HAL_PWR_EnableBkUpAccess();
}

static uint32_t bkp_read(uint32_t reg)
{
  return HAL_RTCEx_BKUPRead(&hrtc, reg);
}

static void bkp_write(uint32_t reg, uint32_t val)
{
  HAL_RTCEx_BKUPWrite(&hrtc, reg, val);
}

/* ---- public API ---------------------------------------------------------- */

void boot_ctrl_init(void)
{
  bkp_enable_access();

  s_boot_tick = HAL_GetTick();
  s_healthy   = 0U;
  s_dfu_pending = 0U;

  /* Clear any stale request so that a spurious magic left in the register
     cannot bounce us into DFU on every subsequent boot. The loader is
     expected to have cleared it already; this is belt and braces. */
  if (bkp_read(SHEPPARD_BKP_BOOT_REQ) != SHEPPARD_BOOT_REQ_NONE)
  {
    bkp_write(SHEPPARD_BKP_BOOT_REQ, SHEPPARD_BOOT_REQ_NONE);
  }

  s_attempts_at_boot = bkp_read(SHEPPARD_BKP_BOOT_ATTEMPTS);

  /* A wildly out-of-range value means the backup domain was not retained
     (no VBAT cell -- TN-16 open item 17) or has never been written. Treat it
     as a clean first boot rather than as many failures. */
  if (s_attempts_at_boot > 64U)
  {
    s_attempts_at_boot = 0U;
    bkp_write(SHEPPARD_BKP_BOOT_ATTEMPTS, 0U);
  }
}

void boot_ctrl_task(void)
{
  uint32_t now = HAL_GetTick();

  if (!s_healthy && (now - s_boot_tick) >= SHEPPARD_BOOT_HEALTHY_MS)
  {
    s_healthy = 1U;
    bkp_write(SHEPPARD_BKP_BOOT_ATTEMPTS, 0U);
  }

  if (s_dfu_pending && (int32_t)(now - s_dfu_reset_at) >= 0)
  {
    /* Committed. Nothing after this line runs. */
    __disable_irq();
    NVIC_SystemReset();
  }
}

void boot_ctrl_request_dfu(void)
{
  if (s_dfu_pending)
  {
    return;                       /* already committed; do not restart the clock */
  }

  bkp_enable_access();
  bkp_write(SHEPPARD_BKP_BOOT_REQ, SHEPPARD_BOOT_REQ_DFU);

  /* Read back. If the backup domain is not writable the request would be
     silently lost and the board would simply reboot into the application,
     which looks exactly like "DFU is broken". Say so instead. */
  if (bkp_read(SHEPPARD_BKP_BOOT_REQ) != SHEPPARD_BOOT_REQ_DFU)
  {
    console_printf("boot: BKP write failed -- HAL_PWR_EnableBkUpAccess missing?\r\n");
    return;
  }

  s_dfu_pending  = 1U;
  s_dfu_reset_at = HAL_GetTick() + SHEPPARD_DFU_DETACH_GRACE_MS;

  console_printf("boot: DFU requested, resetting in %u ms\r\n",
                 (unsigned)SHEPPARD_DFU_DETACH_GRACE_MS);
}

void boot_ctrl_reset_now(void)
{
  bkp_enable_access();
  bkp_write(SHEPPARD_BKP_BOOT_REQ, SHEPPARD_BOOT_REQ_NONE);
  __disable_irq();
  NVIC_SystemReset();
}

uint32_t boot_ctrl_attempts(void)
{
  return s_healthy ? 0U : s_attempts_at_boot;
}

int boot_ctrl_is_healthy(void)
{
  return (int)s_healthy;
}

int boot_ctrl_dfu_pending(void)
{
  return (int)s_dfu_pending;
}

/* ---- USB hook -----------------------------------------------------------
 * Overrides the __weak stub in usbd_composite.c. Keeps USB policy out of the
 * USB layer: the class driver decides only that a detach was requested, this
 * module decides what a detach means.
 * ------------------------------------------------------------------------- */

void USBD_Composite_DfuDetach(void)
{
  boot_ctrl_request_dfu();
}
