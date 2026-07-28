/**
  ******************************************************************************
  * @file    led.h
  * @brief   Status indication for unattended operation.
  *
  * WHY THIS EXISTS
  *   The campaign runs overnight with no console attached. The question you
  *   walk up to the bench asking is always the same one: "is last night's run
  *   worth downloading?" Three LEDs answer it from across the room, without
  *   plugging anything in and without touching the board -- which matters,
  *   because touching it costs about nine minutes of thermal settling
  *   (TN-19 section 4).
  *
  * ASSIGNMENT
  *   LED1  ALIVE       slow breathe when idle, fast blink while recording.
  *                     A board that has hard-faulted shows a frozen LED, which
  *                     a steady-state indicator cannot distinguish from health.
  *   LED2  INTEGRITY   off = clean. LATCHES ON at the first FIFO overflow,
  *                     ring-full or bus fault. Latching, not live, because the
  *                     fault that matters happened at 03:00 and cleared itself.
  *   LED3  THERMAL     on while the R2 gate is being met, blinking when the
  *                     drift rate exceeds it. The gate is the one condition
  *                     that silently invalidates a record (TN-14 section 2.2),
  *                     and at ODR 25 it is the binding constraint of the whole
  *                     campaign.
  *   LED4              left alone; used by the bootloader/health path.
  *
  * SWITCHING ACTIVITY
  *   Rule R8 controls bus and digital activity as a confound. LED updates are
  *   deliberately slow -- nothing faster than 10 Hz, and the breathe is done in
  *   software PWM only while IDLE, never during a record. During a record each
  *   LED changes state at most a few times a second.
  ******************************************************************************
  */

#ifndef LED_H
#define LED_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
  LED_MODE_IDLE = 0,     /**< breathing, nothing in progress            */
  LED_MODE_REC,          /**< recording                                 */
  LED_MODE_SEQ,          /**< running a sequence                        */
  LED_MODE_BUSY,         /**< flashing firmware, transferring a file    */
} led_mode_t;

/**
  * @brief  Non-zero when VBUS is present on PB13, i.e. USB is supplying power.
  *
  *         Recorded in every record header. A record taken on battery differs
  *         from a wired one both electromagnetically and mechanically -- the
  *         cable is a tether as well as a supply -- and without this the two
  *         cannot be told apart in the archive.
  */
int sheppard_vbus_present(void);

/** Call once from main(), after MX_GPIO_Init(). */
void led_init(void);

/** Call often -- main loop, and inside any long blocking wait. Non-blocking. */
void led_task(void);

void led_set_mode(led_mode_t mode);

/**
  * @brief  Latch the integrity fault indicator. Never clears itself; only
  *         led_clear_faults() resets it, which a new record does.
  */
void led_fault(void);

/** Clear the integrity latch. Called when a record starts. */
void led_clear_faults(void);

/** Non-zero if the integrity latch is set since the last clear. */
int  led_faulted(void);

/**
  * @brief  Report thermal-gate state.
  * @param  active   non-zero if a gate applies to the current configuration
  * @param  within   non-zero if the measured drift is inside the gate
  */
void led_thermal(int active, int within);

#ifdef __cplusplus
}
#endif

#endif /* LED_H */
