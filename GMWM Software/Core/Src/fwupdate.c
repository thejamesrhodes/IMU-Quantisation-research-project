/**
  ******************************************************************************
  * @file    fwupdate.c
  * @brief   Self-flashing firmware update over the CDC endpoints.
  ******************************************************************************
  */

#include "fwupdate.h"
#include "sheppard_config.h"
#include "console.h"
#include "arena.h"

#include <stdlib.h>
#include <string.h>

#include "main.h"
#include "usbd_def.h"
#include "usbd_core.h"

extern USBD_HandleTypeDef hUsbDeviceHS;

#if SHEPPARD_FW_UPDATE

/* ==========================================================================
 * Staging buffer
 *
 * .bss, so it costs nothing in the image. 8-byte aligned because the
 * programming loop reads it as 32-bit words and alignment faults during the
 * one operation you cannot retry are not worth the risk.
 * ========================================================================== */

/* The staging buffer is the shared arena, not a private array. 128 KiB here
   plus 128 KiB for the SD ring would be 256 KiB against a 192 KiB region --
   they do not both fit and do not both need to exist at once, because you do
   not flash firmware in the middle of a record. arena.h has the reasoning. */
static uint8_t *s_stage;

#define FW_STAGE_MAX  ARENA_SIZE
static const char *const FW_ARENA_OWNER = "fwupdate";

/* The tail-padding loop in fw_task() rounds the image length up to a word
   boundary in place. If the buffer length were not itself a multiple of 4,
   a maximum-size image would pad one byte past the end. */
typedef char fw_stage_size_check[((FW_STAGE_MAX & 3U) == 0U) ? 1 : -1];

typedef enum {
  FW_IDLE = 0,
  FW_RECEIVING,
  FW_VERIFY,
  FW_ARMED
} fw_state_t;

static volatile fw_state_t s_state    = FW_IDLE;
static volatile uint32_t   s_expected = 0U;   /* image length, bytes          */
static volatile uint32_t   s_received = 0U;   /* bytes staged so far          */
static volatile uint32_t   s_last_rx  = 0U;   /* HAL tick of the last packet  */
static uint32_t            s_want_crc = 0U;
static uint32_t            s_fire_at  = 0U;

/* ==========================================================================
 * CRC-32 (zlib / IEEE 802.3): reflected, poly 0xEDB88320, init and final
 * XOR 0xFFFFFFFF. Nibble table -- 64 bytes of flash, ~4x faster than the
 * bitwise form, which matters over 160 KiB at 32 MHz.
 * ========================================================================== */

static const uint32_t s_crc_nibble[16] = {
  0x00000000UL, 0x1DB71064UL, 0x3B6E20C8UL, 0x26D930ACUL,
  0x76DC4190UL, 0x6B6B51F4UL, 0x4DB26158UL, 0x5005713CUL,
  0xEDB88320UL, 0xF00F9344UL, 0xD6D6A3E8UL, 0xCB61B38CUL,
  0x9B64C2B0UL, 0x86D3D2D4UL, 0xA00AE278UL, 0xBDBDF21CUL
};

static uint32_t crc32(const uint8_t *p, uint32_t n)
{
  uint32_t crc = 0xFFFFFFFFUL;
  while (n--)
  {
    crc ^= *p++;
    crc = (crc >> 4) ^ s_crc_nibble[crc & 0x0FU];
    crc = (crc >> 4) ^ s_crc_nibble[crc & 0x0FU];
  }
  return ~crc;
}

/* ==========================================================================
 * The RAM-resident flasher
 *
 * Constraints this function must satisfy, all of them load-bearing:
 *
 *  - It executes from SRAM. On single-bank F7 flash, any read of the array
 *    during program/erase stalls the bus, so a flash-resident routine cannot
 *    survive erasing the sector it lives in -- and a mass erase erases every
 *    sector. [fact, RM0431 embedded flash chapter]
 *
 *  - `long_call`. The linker places .RamFunc at 0x20000000 and the caller at
 *    0x08000000, 384 MiB apart. A direct BL reaches +-16 MiB, so without this
 *    the link fails with "relocation truncated to fit".
 *
 *  - It calls nothing. Every HAL and CMSIS non-inline function lives in
 *    flash. Only register writes, inline barriers, and loops appear below.
 *    GCC emits literal pools into the enclosing section, so the constants
 *    below land in RAM with the code.
 *
 *  - Interrupts must already be disabled by the caller. A vector fetch during
 *    the erase would read flash.
 *
 * @param  probe   non-zero: return a magic value and touch nothing. Used to
 *                 prove the processor really can fetch instructions from this
 *                 address before anything destructive happens.
 * @retval on probe: 0x00C0FFEE.  On failure: the FLASH_SR error bits.
 *         On success it does not return -- the board resets.
 * ========================================================================== */

#define FW_PROBE_MAGIC   0x00C0FFEEUL

#define FW_FLASH_KEY1    0x45670123UL
#define FW_FLASH_KEY2    0xCDEF89ABUL

#define FW_SR_ERRORS  (FLASH_SR_OPERR | FLASH_SR_WRPERR | \
                       FLASH_SR_PGAERR | FLASH_SR_PGPERR | FLASH_SR_ERSERR)

__attribute__((section(".RamFunc"), noinline, long_call))
static uint32_t fw_flash_and_reset(const uint32_t *src, uint32_t nwords,
                                   uint32_t probe)
{
  if (probe != 0U)
  {
    return FW_PROBE_MAGIC;
  }

  volatile uint32_t *dst = (volatile uint32_t *)0x08000000UL;
  uint32_t sr;

  /* --- unlock ---------------------------------------------------------- */
  if ((FLASH->CR & FLASH_CR_LOCK) != 0U)
  {
    FLASH->KEYR = FW_FLASH_KEY1;
    FLASH->KEYR = FW_FLASH_KEY2;
  }

  while ((FLASH->SR & FLASH_SR_BSY) != 0U) { }
  FLASH->SR = FLASH_SR_EOP | FW_SR_ERRORS;      /* w1c */

  /* --- mass erase, 32-bit parallelism ----------------------------------
     PSIZE = 0b10 (x32) is permitted at 2.7-3.6 V with no external Vpp.
     Mass erase rather than sector erase so that nothing here depends on the
     F723ZE sector map, which is still unverified.                        */
  FLASH->CR &= ~FLASH_CR_PSIZE;
  FLASH->CR |= FLASH_CR_PSIZE_1;
  FLASH->CR |= FLASH_CR_MER;
  FLASH->CR |= FLASH_CR_STRT;
  __DSB();

  while ((FLASH->SR & FLASH_SR_BSY) != 0U) { }
  FLASH->CR &= ~FLASH_CR_MER;

  sr = FLASH->SR & FW_SR_ERRORS;
  if (sr != 0U)
  {
    FLASH->CR |= FLASH_CR_LOCK;
    return sr;                                  /* flash is now blank */
  }

  /* --- program --------------------------------------------------------- */
  FLASH->CR |= FLASH_CR_PG;
  __DSB();

  for (uint32_t i = 0U; i < nwords; i++)
  {
    dst[i] = src[i];
    __DSB();
    while ((FLASH->SR & FLASH_SR_BSY) != 0U) { }

    sr = FLASH->SR & FW_SR_ERRORS;
    if (sr != 0U)
    {
      FLASH->CR &= ~FLASH_CR_PG;
      FLASH->CR |= FLASH_CR_LOCK;
      return sr;
    }
  }

  FLASH->CR &= ~FLASH_CR_PG;
  __DSB();

  /* --- verify, still from RAM ------------------------------------------ */
  for (uint32_t i = 0U; i < nwords; i++)
  {
    if (dst[i] != src[i])
    {
      FLASH->CR |= FLASH_CR_LOCK;
      return 0xBADC0DE0UL;
    }
  }

  FLASH->CR |= FLASH_CR_LOCK;

  /* --- reset -----------------------------------------------------------
     AIRCR written directly rather than via NVIC_SystemReset(), which is
     __STATIC_INLINE and would almost certainly inline, but "almost" is not
     a word that belongs in a function that must not touch flash.        */
  __DSB();
  SCB->AIRCR = (uint32_t)((0x5FAUL << SCB_AIRCR_VECTKEY_Pos) |
                          SCB_AIRCR_SYSRESETREQ_Msk);
  __DSB();
  for (;;) { }
}

/* ==========================================================================
 * Image sanity checks
 * ========================================================================== */

static int vectors_plausible(const uint8_t *img, uint32_t len, const char **why)
{
  uint32_t msp, pc;

  if (len < 8U)
  {
    *why = "too short for a vector table";
    return 0;
  }

  memcpy(&msp, img + 0, 4);
  memcpy(&pc,  img + 4, 4);

  /* 256 KiB of SRAM, contiguous from 0x20000000 on this part. The initial
     stack pointer is the top of the stack, so it may legitimately equal the
     end of the region. */
  if ((msp < 0x20000000UL) || (msp > 0x20040000UL))
  {
    *why = "initial SP not in SRAM";
    return 0;
  }

  /* Reset vector must point into flash, with the Thumb bit set. */
  if ((pc < 0x08000000UL) || (pc >= (0x08000000UL + (512UL * 1024UL))))
  {
    *why = "reset vector not in flash";
    return 0;
  }
  if ((pc & 1UL) == 0U)
  {
    *why = "reset vector has no Thumb bit";
    return 0;
  }

  return 1;
}

/* ==========================================================================
 * Console command
 * ========================================================================== */

static void cmd_fw(int argc, char **argv)
{
  if (s_state != FW_IDLE)
  {
    console_printf("FWABORT already-in-progress\r\n");
    return;
  }

  if (argc < 3)
  {
    console_printf("usage: fw <size-bytes> <crc32-hex>\r\n");
    console_printf("       staging buffer is %lu bytes\r\n",
                   (unsigned long)FW_STAGE_MAX);
    return;
  }

  char    *end = NULL;
  uint32_t size = (uint32_t)strtoul(argv[1], &end, 0);
  if ((end == argv[1]) || (*end != '\0'))
  {
    console_printf("FWABORT bad-size\r\n");
    return;
  }

  uint32_t crc = (uint32_t)strtoul(argv[2], &end, 16);
  if (end == argv[2])
  {
    console_printf("FWABORT bad-crc\r\n");
    return;
  }

  if ((size < SHEPPARD_FW_MIN_SIZE) || (size > FW_STAGE_MAX))
  {
    console_printf("FWABORT size-out-of-range %lu (min %lu max %lu)\r\n",
                   (unsigned long)size,
                   (unsigned long)SHEPPARD_FW_MIN_SIZE,
                   (unsigned long)FW_STAGE_MAX);
    return;
  }

  /* Claim the shared buffer. Fails, with an explanation, if a record is
     open -- which is the guard that lets fwupdate and storage overlay. */
  s_stage = arena_claim(FW_ARENA_OWNER);
  if (s_stage == NULL)
  {
    console_printf("FWABORT arena-busy\r\n");
    return;
  }

  s_expected = size;
  s_want_crc = crc;
  s_received = 0U;
  s_last_rx  = HAL_GetTick();
  s_state    = FW_RECEIVING;                    /* arms fw_rx_isr() */

  console_printf("FWREADY %lu\r\n", (unsigned long)size);
}

static const console_cmd_t s_fw_cmds[] = {
  { "fw", "fw <size> <crc32hex> - flash a new image over USB", cmd_fw },
};

/* ==========================================================================
 * Receive path -- USB interrupt context
 * ========================================================================== */

int fw_rx_isr(const uint8_t *buf, uint32_t len)
{
  if (s_state != FW_RECEIVING)
  {
    return 0;
  }

  uint32_t room = s_expected - s_received;
  uint32_t n    = (len < room) ? len : room;

  /* Anything beyond the declared length is discarded rather than allowed to
     run off the buffer. The CRC check will fail, which is the correct
     outcome for a host that overshot. */
  memcpy(&s_stage[s_received], buf, n);
  s_received += n;
  s_last_rx   = HAL_GetTick();

  if (s_received >= s_expected)
  {
    s_state = FW_VERIFY;
  }

  return 1;
}

int fw_busy(void)
{
  return (s_state != FW_IDLE);
}

/* ==========================================================================
 * Main-loop state machine
 * ========================================================================== */

void fw_task(void)
{
  switch (s_state)
  {
    case FW_IDLE:
      break;

    case FW_RECEIVING:
      if ((HAL_GetTick() - s_last_rx) > SHEPPARD_FW_RX_TIMEOUT_MS)
      {
        arena_release(FW_ARENA_OWNER);   /* ownership-checked; safe anywhere */
        s_state = FW_IDLE;
        console_printf("FWABORT timeout after %lu of %lu bytes\r\n",
                       (unsigned long)s_received, (unsigned long)s_expected);
      }
      break;

    case FW_VERIFY:
    {
      const char *why = "";

      console_printf("FWRECV %lu\r\n", (unsigned long)s_received);

      uint32_t got = crc32(s_stage, s_expected);
      if (got != s_want_crc)
      {
        arena_release(FW_ARENA_OWNER);   /* ownership-checked; safe anywhere */
        s_state = FW_IDLE;
        console_printf("FWCRC bad got=%08lX want=%08lX\r\n",
                       (unsigned long)got, (unsigned long)s_want_crc);
        return;
      }
      console_printf("FWCRC ok\r\n");

      if (!vectors_plausible(s_stage, s_expected, &why))
      {
        arena_release(FW_ARENA_OWNER);   /* ownership-checked; safe anywhere */
        s_state = FW_IDLE;
        console_printf("FWVEC bad: %s\r\n", why);
        return;
      }
      console_printf("FWVEC ok\r\n");

      /* Prove we can actually execute from the .RamFunc address before
         erasing anything. If the processor cannot fetch instructions there,
         this faults now -- with flash still intact and a reset all that is
         needed -- rather than halfway through a mass erase. */
      if (fw_flash_and_reset(NULL, 0U, 1U) != FW_PROBE_MAGIC)
      {
        arena_release(FW_ARENA_OWNER);   /* ownership-checked; safe anywhere */
        s_state = FW_IDLE;
        console_printf("FWABORT ramfunc-probe-failed\r\n");
        return;
      }

      /* Pad the tail so the final partial word programs as erased flash. */
      while ((s_expected & 3U) != 0U)
      {
        s_stage[s_expected++] = 0xFFU;
      }

      console_printf("FWPROG\r\n");
      s_fire_at = HAL_GetTick() + SHEPPARD_FW_PROGRAM_DELAY_MS;
      s_state   = FW_ARMED;
      break;
    }

    case FW_ARMED:
      if ((int32_t)(HAL_GetTick() - s_fire_at) < 0)
      {
        break;
      }

      /* Detach cleanly. The host then sees an ordinary removal instead of a
         device that stopped answering, and the flashing script can simply
         wait for the port to come back. */
      (void)USBD_Stop(&hUsbDeviceHS);
      HAL_Delay(20);

      __disable_irq();

      {
        uint32_t err = fw_flash_and_reset((const uint32_t *)(const void *)s_stage,
                                          s_expected / 4U, 0U);
        /* Only reached on failure -- success resets inside the routine.
           Flash is now blank or partially written, so there is nothing to
           return to. Re-enable interrupts, report, and sit still: the console
           may survive long enough to say why, and SWD certainly will. */
        __enable_irq();
        arena_release(FW_ARENA_OWNER);   /* ownership-checked; safe anywhere */
        s_state = FW_IDLE;
        console_printf("FWFAIL FLASH_SR=%08lX -- reflash over SWD\r\n",
                       (unsigned long)err);
      }
      break;

    default:
      arena_release(FW_ARENA_OWNER);
      s_state = FW_IDLE;
      break;
  }
}

void fw_init(void)
{
  s_state = FW_IDLE;
  (void)console_register(s_fw_cmds,
                         (uint8_t)(sizeof s_fw_cmds / sizeof s_fw_cmds[0]));
}

#else  /* SHEPPARD_FW_UPDATE */

void fw_init(void)                                    { }
void fw_task(void)                                    { }
int  fw_rx_isr(const uint8_t *b, uint32_t l)          { (void)b; (void)l; return 0; }
int  fw_busy(void)                                    { return 0; }

#endif /* SHEPPARD_FW_UPDATE */
