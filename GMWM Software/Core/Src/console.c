/**
  ******************************************************************************
  * @file    console.c
  * @brief   Transport-independent diagnostic console.
  ******************************************************************************
  */

#include "console.h"
#include "sheppard_config.h"
#include "boot_ctrl.h"

#include <stdio.h>
#include <string.h>

#include "main.h"
#include "usbd_def.h"
#include "usbd_cdc_if.h"

extern USBD_HandleTypeDef hUsbDeviceHS;

#if SHEPPARD_CONSOLE_UART_MIRROR
extern UART_HandleTypeDef huart1;
#endif

/* ==========================================================================
 * Receive ring buffer
 *
 * Single producer (USB ISR) writing head, single consumer (main loop) reading
 * tail. With a power-of-two size and 32-bit aligned indices this needs no
 * critical section on Cortex-M7: each index is written by exactly one context
 * and word accesses are atomic.
 * ========================================================================== */

#if (SHEPPARD_CONSOLE_RX_RING & (SHEPPARD_CONSOLE_RX_RING - 1U)) != 0U
#error "SHEPPARD_CONSOLE_RX_RING must be a power of two"
#endif

#define RX_MASK (SHEPPARD_CONSOLE_RX_RING - 1U)

static volatile uint32_t s_rx_head = 0U;
static volatile uint32_t s_rx_tail = 0U;
static volatile uint32_t s_rx_dropped = 0U;
static uint8_t           s_rx_ring[SHEPPARD_CONSOLE_RX_RING];

/* ==========================================================================
 * Line assembly and command table
 * ========================================================================== */

static char     s_line[SHEPPARD_CONSOLE_LINE_MAX];
static uint16_t s_line_len = 0U;
static uint8_t  s_line_overflow = 0U;

static const console_cmd_t *s_cmd_sets[SHEPPARD_CONSOLE_MAX_CMD_SETS];
static uint8_t              s_cmd_counts[SHEPPARD_CONSOLE_MAX_CMD_SETS];
static uint8_t              s_cmd_set_count = 0U;

static uint8_t s_initialised = 0U;

/* ==========================================================================
 * Output
 * ========================================================================== */

int console_cdc_ready(void)
{
#if SHEPPARD_CONSOLE_CDC
  return (hUsbDeviceHS.dev_state == USBD_STATE_CONFIGURED) ? 1 : 0;
#else
  return 0;
#endif
}

#if SHEPPARD_CONSOLE_CDC
/* CDC_Transmit_HS dereferences pClassData without a NULL check in several
   CubeMX versions, so the dev_state guard is load-bearing, not cosmetic
   (TN-16 SS7.2). Busy-looping is bounded: if the host is not draining the
   endpoint we give up rather than stalling the logger. */
static int cdc_put(const uint8_t *buf, uint16_t len)
{
  if (hUsbDeviceHS.dev_state != USBD_STATE_CONFIGURED)
  {
    return -1;
  }

  uint32_t t0 = HAL_GetTick();
  for (;;)
  {
    uint8_t r = CDC_Transmit_HS((uint8_t *)buf, len);
    if (r == USBD_OK)
    {
      return 0;
    }
    if (r != USBD_BUSY)
    {
      return -1;                                  /* FAIL / EMEM */
    }
    if ((HAL_GetTick() - t0) > SHEPPARD_CONSOLE_CDC_TIMEOUT_MS)
    {
      return -1;
    }
  }
}
#endif

int console_write_cdc(const void *buf, uint16_t len)
{
  if ((buf == NULL) || (len == 0U))
  {
    return 0;
  }

#if SHEPPARD_CONSOLE_CDC
  return cdc_put((const uint8_t *)buf, len);
#else
  return -1;
#endif
}

int console_write(const void *buf, uint16_t len)
{
  int ok = -1;

  if ((buf == NULL) || (len == 0U))
  {
    return 0;
  }

#if SHEPPARD_CONSOLE_CDC
  if (cdc_put((const uint8_t *)buf, len) == 0)
  {
    ok = 0;
  }
#endif

#if SHEPPARD_CONSOLE_UART_MIRROR
  if (huart1.gState != HAL_UART_STATE_RESET)
  {
    if (HAL_UART_Transmit(&huart1, (uint8_t *)buf, len,
                          SHEPPARD_CONSOLE_UART_TIMEOUT_MS) == HAL_OK)
    {
      ok = 0;
    }
  }
#endif

  return ok;
}

void console_vprintf(const char *fmt, va_list ap)
{
  /* static, not stack: the default _Min_Stack_Size is 0x400 (TN-16 open
     item 19) and a 192-byte frame plus vsnprintf's own use is uncomfortably
     close to it. Safe because the console is main-loop only. */
  static char buf[SHEPPARD_CONSOLE_TX_MAX];

  int n = vsnprintf(buf, sizeof buf, fmt, ap);
  if (n < 0)
  {
    return;
  }
  if (n >= (int)sizeof buf)
  {
    n = (int)sizeof buf - 1;                      /* vsnprintf truncated */
  }

  (void)console_write(buf, (uint16_t)n);
}

void console_printf(const char *fmt, ...)
{
  va_list ap;
  va_start(ap, fmt);
  console_vprintf(fmt, ap);
  va_end(ap);
}

/* ==========================================================================
 * Input
 * ========================================================================== */

void console_rx_feed(const uint8_t *buf, uint32_t len)
{
  uint32_t head = s_rx_head;

  for (uint32_t i = 0U; i < len; i++)
  {
    uint32_t next = (head + 1U) & RX_MASK;
    if (next == s_rx_tail)
    {
      s_rx_dropped++;                             /* consumer is behind */
      break;
    }
    s_rx_ring[head] = buf[i];
    head = next;
  }

  s_rx_head = head;
}

int console_rx_pending(void)
{
  /* Line terminators do not count as pending input, and are consumed here.
     Without this, `rate` aborted the instant it started: a host sending
     "rate\r\n" gets the command dispatched on the CR, while the LF is still
     sitting in the ring buffer -- so the very first pending-input check
     inside the command saw its own line ending and treated it as a keypress.

     Consuming them is safe: console_task() discards them anyway, and this
     only ever runs on the main loop, so there is no race with rx_get(). */
  uint32_t tail = s_rx_tail;

  while (tail != s_rx_head)
  {
    uint8_t c = s_rx_ring[tail];
    if ((c != '\r') && (c != '\n'))
    {
      s_rx_tail = tail;                 /* keep the real input for the parser */
      return 1;
    }
    tail = (tail + 1U) & RX_MASK;
  }

  s_rx_tail = tail;
  return 0;
}

static int rx_get(uint8_t *out)
{
  uint32_t tail = s_rx_tail;
  if (tail == s_rx_head)
  {
    return 0;
  }
  *out = s_rx_ring[tail];
  s_rx_tail = (tail + 1U) & RX_MASK;
  return 1;
}

/* ==========================================================================
 * Command dispatch
 * ========================================================================== */

#define CONSOLE_MAX_ARGS 8

static void dispatch(char *line)
{
  char *argv[CONSOLE_MAX_ARGS];
  int   argc = 0;
  char *p = line;

  while ((*p != '\0') && (argc < CONSOLE_MAX_ARGS))
  {
    while ((*p == ' ') || (*p == '\t'))
    {
      *p++ = '\0';
    }
    if (*p == '\0')
    {
      break;
    }
    argv[argc++] = p;
    while ((*p != '\0') && (*p != ' ') && (*p != '\t'))
    {
      p++;
    }
  }

  if (argc == 0)
  {
    return;
  }

  for (uint8_t s = 0U; s < s_cmd_set_count; s++)
  {
    const console_cmd_t *set = s_cmd_sets[s];
    for (uint8_t c = 0U; c < s_cmd_counts[s]; c++)
    {
      if (strcmp(argv[0], set[c].name) == 0)
      {
        set[c].fn(argc, argv);
        return;
      }
    }
  }

  console_printf("? %s  (try 'help')\r\n", argv[0]);
}

void console_task(void)
{
  uint8_t ch;

  if (s_rx_dropped != 0U)
  {
    uint32_t n = s_rx_dropped;
    s_rx_dropped = 0U;
    console_printf("console: dropped %lu rx bytes\r\n", (unsigned long)n);
  }

  while (rx_get(&ch))
  {
    if ((ch == '\r') || (ch == '\n'))
    {
      if (s_line_overflow)
      {
        console_printf("\r\nconsole: line too long (max %u)\r\n",
                       (unsigned)(SHEPPARD_CONSOLE_LINE_MAX - 1U));
        s_line_overflow = 0U;
        s_line_len = 0U;
        continue;
      }
      if (s_line_len == 0U)
      {
        continue;                                 /* bare CR/LF, or CRLF pair */
      }
#if SHEPPARD_CONSOLE_ECHO
      console_write("\r\n", 2U);
#endif
      s_line[s_line_len] = '\0';
      s_line_len = 0U;
      dispatch(s_line);
      continue;
    }

    if ((ch == 0x08U) || (ch == 0x7FU))           /* BS / DEL */
    {
      if (s_line_len > 0U)
      {
        s_line_len--;
#if SHEPPARD_CONSOLE_ECHO
        console_write("\b \b", 3U);
#endif
      }
      continue;
    }

    if ((ch < 0x20U) || (ch > 0x7EU))
    {
      continue;                                   /* ignore other control bytes */
    }

    if (s_line_len < (SHEPPARD_CONSOLE_LINE_MAX - 1U))
    {
      s_line[s_line_len++] = (char)ch;
#if SHEPPARD_CONSOLE_ECHO
      console_write(&ch, 1U);
#endif
    }
    else
    {
      s_line_overflow = 1U;
    }
  }
}

int console_register(const console_cmd_t *cmds, uint8_t count)
{
  if ((cmds == NULL) || (count == 0U))
  {
    return 0;
  }
  if (s_cmd_set_count >= SHEPPARD_CONSOLE_MAX_CMD_SETS)
  {
    return -1;
  }
  s_cmd_sets[s_cmd_set_count]   = cmds;
  s_cmd_counts[s_cmd_set_count] = count;
  s_cmd_set_count++;
  return 0;
}

/* ==========================================================================
 * Built-in commands
 * ========================================================================== */

static void cmd_help(int argc, char **argv)
{
  (void)argc;
  (void)argv;
  console_printf("commands:\r\n");
  for (uint8_t s = 0U; s < s_cmd_set_count; s++)
  {
    for (uint8_t c = 0U; c < s_cmd_counts[s]; c++)
    {
      console_printf("  %-8s %s\r\n",
                     s_cmd_sets[s][c].name,
                     s_cmd_sets[s][c].help ? s_cmd_sets[s][c].help : "");
    }
  }
}

static void cmd_ver(int argc, char **argv)
{
  (void)argc;
  (void)argv;
  console_printf("%s %s (%s)  built %s %s\r\n",
                 SHEPPARD_FW_NAME, SHEPPARD_FW_VERSION_STR,
                 SHEPPARD_BUILD_TAG, __DATE__, __TIME__);
  console_printf("  app base 0x%08lX  VTOR 0x%08lX\r\n",
                 (unsigned long)SHEPPARD_APP_BASE, (unsigned long)SCB->VTOR);
  console_printf("  SYSCLK %lu  HCLK %lu  PCLK1 %lu  PCLK2 %lu Hz\r\n",
                 (unsigned long)HAL_RCC_GetSysClockFreq(),
                 (unsigned long)HAL_RCC_GetHCLKFreq(),
                 (unsigned long)HAL_RCC_GetPCLK1Freq(),
                 (unsigned long)HAL_RCC_GetPCLK2Freq());
  console_printf("  boot attempts %lu  healthy %d\r\n",
                 (unsigned long)boot_ctrl_attempts(), boot_ctrl_is_healthy());
}

static void cmd_usb(int argc, char **argv)
{
  (void)argc;
  (void)argv;
  console_printf("USB dev_state=%d (1=DEFAULT 2=ADDRESSED 3=CONFIGURED 4=SUSPENDED)\r\n",
                 (int)hUsbDeviceHS.dev_state);
  if (hUsbDeviceHS.dev_state != USBD_STATE_CONFIGURED)
  {
    console_printf("  not enumerated: try another cable before debugging firmware\r\n");
  }
#if SHEPPARD_USB_DFU_RUNTIME
  console_printf("  interfaces: 0,1 = CDC (IAD)  2 = DFU run-time\r\n");
#else
  console_printf("  interfaces: 0,1 = CDC only (DFU run-time disabled)\r\n");
#endif
}

/* The `dfu` command is gone. It wrote the loader request magic and reset --
   useful when a resident DFU loader was planned, but with the self-flasher of
   fwupdate.c there is nothing to boot into and it would only have rebooted
   the application into itself. boot_ctrl_request_dfu() is kept in place for
   the day a loader appears; `reset` covers the honest use case. */

static void cmd_reset(int argc, char **argv)
{
  (void)argc;
  (void)argv;
  console_printf("resetting...\r\n");
  HAL_Delay(20);                                  /* let the line flush */
  boot_ctrl_reset_now();
}

static const console_cmd_t s_builtin_cmds[] = {
  { "help",  "list commands",                       cmd_help  },
  { "ver",   "firmware version, clocks, boot state", cmd_ver   },
  { "usb",   "USB device state",                     cmd_usb   },
  { "reset", "reboot",                               cmd_reset },
};

void console_init(void)
{
  if (s_initialised)
  {
    return;
  }
  s_initialised = 1U;

  s_rx_head = 0U;
  s_rx_tail = 0U;
  s_rx_dropped = 0U;
  s_line_len = 0U;
  s_line_overflow = 0U;

  (void)console_register(s_builtin_cmds,
                         (uint8_t)(sizeof s_builtin_cmds / sizeof s_builtin_cmds[0]));
}
