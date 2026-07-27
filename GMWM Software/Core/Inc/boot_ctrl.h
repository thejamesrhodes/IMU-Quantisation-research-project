/**
  ******************************************************************************
  * @file    boot_ctrl.h
  * @brief   Boot-mode handshake between the application and the DFU loader.
  *
  * The two images communicate through the RTC backup registers, which survive
  * a system reset. Register allocation is in sheppard_config.h and MUST be
  * kept identical in both projects -- a mismatch is silent and presents as
  * "the board never enters DFU".
  *
  * This module is safe to build and run with no loader present (stage 1):
  * boot_ctrl_request_dfu() then simply resets into the application again,
  * which is a useful end-to-end test of the reset path on its own.
  ******************************************************************************
  */

#ifndef BOOT_CTRL_H
#define BOOT_CTRL_H

#include <stdint.h>
#include "main.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
  * @brief  Prepare the backup domain and read the boot state left by the loader.
  *         Call once from main(), AFTER MX_RTC_Init() and before the main loop.
  *         Safe to call when no loader exists.
  */
void boot_ctrl_init(void);

/**
  * @brief  Per-iteration housekeeping. Call from the main loop.
  *         Clears the failed-boot counter once the application has been alive
  *         for SHEPPARD_BOOT_HEALTHY_MS, and performs the deferred reset after
  *         a DFU request has been acknowledged.
  */
void boot_ctrl_task(void);

/**
  * @brief  Ask to reboot into the DFU loader.
  *         Writes the request magic and schedules a reset
  *         SHEPPARD_DFU_DETACH_GRACE_MS later, so that an in-flight USB
  *         control transfer completes and the console line is flushed.
  *         Returns immediately; the reset happens inside boot_ctrl_task().
  */
void boot_ctrl_request_dfu(void);

/**
  * @brief  Reboot into the application immediately, with no DFU request.
  */
void boot_ctrl_reset_now(void);

/**
  * @brief  Number of consecutive boots that did not reach the healthy point.
  *         0 once boot_ctrl_task() has declared this boot healthy.
  */
uint32_t boot_ctrl_attempts(void);

/**
  * @brief  Non-zero once this boot has been declared healthy.
  */
int boot_ctrl_is_healthy(void);

/**
  * @brief  Non-zero if a DFU reset is pending (request acknowledged, reset not
  *         yet issued). Used to suppress further console output.
  */
int boot_ctrl_dfu_pending(void);

#ifdef __cplusplus
}
#endif

#endif /* BOOT_CTRL_H */
