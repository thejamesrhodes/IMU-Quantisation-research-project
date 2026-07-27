/**
  ******************************************************************************
  * @file    console.h
  * @brief   Transport-independent diagnostic console.
  *
  * One output path for every module in the firmware, with the sink selected at
  * build time in sheppard_config.h (CDC primary, USART1 mirror optional).
  * One input path with proper line assembly and an extensible command table,
  * replacing the fixed-width byte-indexing parser noted in TN-16 SS8.4 -- that
  * one produced silent garbage whenever a field was short.
  *
  * Modules register their own commands rather than main.c growing a switch:
  *
  *     static const console_cmd_t my_cmds[] = {
  *       { "odr", "odr <hz> - set output data rate", cmd_odr },
  *     };
  *     console_register(my_cmds, 1);
  *
  * THREADING
  *   console_rx_feed()  is called from USB interrupt context. It only touches
  *                      a lock-free single-producer ring buffer.
  *   everything else    must be called from the main loop. console_write()
  *                      blocks with a timeout and must never be called from an
  *                      ISR (TN-16 SS9.3: no uart_log in interrupt context).
  ******************************************************************************
  */

#ifndef CONSOLE_H
#define CONSOLE_H

#include <stdint.h>
#include <stdarg.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Command handler. argv[0] is the command name. */
typedef void (*console_cmd_fn)(int argc, char **argv);

typedef struct
{
  const char     *name;   /**< command word, matched case-sensitively */
  const char     *help;   /**< one-line usage, printed by `help`      */
  console_cmd_fn  fn;     /**< handler                                */
} console_cmd_t;

/**
  * @brief  Initialise the console. Call once from main(), after the UART and
  *         USB device init calls. Registers the built-in command set.
  */
void console_init(void);

/**
  * @brief  Drain received bytes, assemble lines, dispatch commands.
  *         Call every iteration of the main loop. Non-blocking.
  */
void console_task(void);

/**
  * @brief  Register a command table. The table must have static lifetime.
  * @retval 0 on success, -1 if SHEPPARD_CONSOLE_MAX_CMD_SETS is exhausted.
  */
int console_register(const console_cmd_t *cmds, uint8_t count);

/**
  * @brief  Write raw bytes to every enabled sink. Binary-safe.
  * @retval 0 if at least one sink accepted the data, -1 if none did.
  */
int console_write(const void *buf, uint16_t len);

/**
  * @brief  Formatted output. Truncates at SHEPPARD_CONSOLE_TX_MAX.
  */
void console_printf(const char *fmt, ...);
void console_vprintf(const char *fmt, va_list ap);

/**
  * @brief  Non-zero when the CDC endpoint is enumerated and configured.
  *         Data written before this is discarded by the host (TN-16 SS7.2),
  *         so log continuously rather than once at boot.
  */
int console_cdc_ready(void);

/**
  * @brief  Non-zero if unread input is waiting.
  *         Lets a long-running blocking command offer an abort key without
  *         consuming the byte or duplicating the ring-buffer logic.
  */
int console_rx_pending(void);

/**
  * @brief  Feed received bytes into the console. USB interrupt context only.
  *         Overflow drops the oldest unread data and sets a flag reported by
  *         console_task(), so a lost command is visible rather than silent.
  */
void console_rx_feed(const uint8_t *buf, uint32_t len);

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_H */
