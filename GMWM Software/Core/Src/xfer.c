/**
  ******************************************************************************
  * @file    xfer.c
  * @brief   Bulk file download over CDC. See xfer.h for the protocol.
  ******************************************************************************
  */

#include "xfer.h"
#include "console.h"
#include "storage.h"
#include "record.h"
#include "arena.h"
#include "timebase.h"
#include "sheppard_config.h"

#include <string.h>
#include <stdio.h>

#include "fatfs.h"

static const char *const XFER_ARENA_OWNER = "xfer";

/* Two 8 KiB halves, alternated.
 *
 * CDC_Transmit_HS does not copy: it hands the pointer to the USB stack and
 * returns as soon as the transfer has STARTED. Refilling the same buffer
 * immediately would rewrite bytes still being DMA'd to the host. Alternating
 * halves means the buffer being filled is never the one in flight, and the
 * next console_write_cdc() blocks until the previous transfer completes, so
 * the two stay exactly one step apart without any explicit handshake. */
#define XFER_CHUNK  8192U

/* ==========================================================================
 * Helpers
 * ========================================================================== */

/* Accepts "name", "SHEPPARD/name" or "/SHEPPARD/name" and produces the full
   path. Typing the directory every time is a nuisance during a campaign, and
   getting it wrong is a silent "no such file". */
static void resolve(const char *in, char *out, size_t cap)
{
  if ((in[0] == '/') || (strchr(in, '/') != NULL))
  {
    (void)snprintf(out, cap, "%s", in);
  }
  else
  {
    (void)snprintf(out, cap, "%s/%s", SHEPPARD_SD_DIR, in);
  }
}

static const char *fr_str(FRESULT fr)
{
  switch (fr)
  {
    case FR_OK:              return "ok";
    case FR_NO_FILE:         return "no such file";
    case FR_NO_PATH:         return "no such path";
    case FR_DENIED:          return "denied";
    case FR_INVALID_NAME:    return "invalid name";
    case FR_NOT_READY:       return "card not ready";
    case FR_DISK_ERR:        return "disk error";
    case FR_NOT_ENABLED:     return "not mounted";
    case FR_NO_FILESYSTEM:   return "no filesystem";
    case FR_LOCKED:          return "locked";
    case FR_TIMEOUT:         return "timeout";
    default:                 break;
  }
  return "error";
}

/* ==========================================================================
 * ls
 * ========================================================================== */

static void cmd_ls(int argc, char **argv)
{
  const char *dir = (argc > 1) ? argv[1] : SHEPPARD_SD_DIR;

  if (!storage_is_mounted())
  {
    if (storage_mount() != 0) { return; }
  }

  static DIR d;
  FRESULT fr = f_opendir(&d, dir);
  if (fr != FR_OK)
  {
    console_printf("ls: %s: %s\r\n", dir, fr_str(fr));
    return;
  }

  /* FILINFO carries fname[_MAX_LFN + 1] with _MAX_LFN = 255, so it is roughly
     290 bytes -- too much to put on the stack next to FatFs' own frames when
     _Min_Stack_Size is 0x1000. Static is safe: the console is main-loop only. */
  static FILINFO fi;

  uint32_t n = 0;
  uint64_t total = 0;
  for (;;)
  {
    fr = f_readdir(&d, &fi);
    if ((fr != FR_OK) || (fi.fname[0] == 0)) { break; }
    if (fi.fattrib & AM_DIR) { continue; }

    /* Size in KiB: the console has no 64-bit printf under nano.specs, and a
       records directory will exceed 4 GB long before this matters in kB. */
    console_printf("  %-40s %8lu kB\r\n", fi.fname,
                   (unsigned long)(((uint64_t)fi.fsize + 1023U) / 1024U));
    total += (uint64_t)fi.fsize;
    n++;
  }
  (void)f_closedir(&d);

  console_printf("ls: %lu file(s), %lu kB total in %s\r\n",
                 (unsigned long)n, (unsigned long)((total + 1023U) / 1024U),
                 dir);
}

/* ==========================================================================
 * get
 * ========================================================================== */

static void cmd_get(int argc, char **argv)
{
  if (argc < 2)
  {
    console_printf("get: usage: get <file>\r\n");
    return;
  }

  if (storage_is_open())
  {
    console_printf("get: a record is open; stop it first\r\n");
    return;
  }
  if (!storage_is_mounted())
  {
    if (storage_mount() != 0) { return; }
  }

  char path[80];
  resolve(argv[1], path, sizeof path);

  static FIL f;                      /* ~600 B with exFAT; keep off the stack */
  FRESULT fr = f_open(&f, path, FA_READ);
  if (fr != FR_OK)
  {
    console_printf("get: %s: %s\r\n", path, fr_str(fr));
    return;
  }

  /* The protocol carries the length as a 32-bit decimal, and nano.specs printf
     has no 64-bit conversion anyway. Refuse rather than truncate: a silently
     wrong length would leave the host reading into the next command's output.
     4 GB is 7.4 hours at ODR 8000, so this is reachable and worth checking. */
  if (f_size(&f) > 0xFFFFFFFFULL)
  {
    console_printf("get: %s exceeds 4 GB; split the run\r\n", path);
    (void)f_close(&f);
    return;
  }
  uint32_t size = (uint32_t)f_size(&f);

  uint8_t *buf = arena_claim(XFER_ARENA_OWNER);
  if (buf == NULL)
  {
    console_printf("get: arena held by %s\r\n", arena_owner());
    (void)f_close(&f);
    return;
  }

  console_printf("xfer: begin %lu %s\r\n", (unsigned long)size, path);

  /* From here to the END line, nothing else may write to the console: any
     stray byte lands in the middle of the payload and the host's byte count
     will never realign.
     The CRC accumulates over exactly the bytes handed to the endpoint, which
     is precisely what the host must check, so it is reported in the trailer
     rather than pre-computed. A pre-pass would mean reading a 13 MB record
     twice for no extra assurance -- if the trailer never arrives the transfer
     has failed anyway, and the host's byte count already says so. */
  uint64_t t0 = timebase_now_us();
  uint32_t sent = 0;
  uint32_t crc  = 0;
  uint32_t half = 0;
  int      bad  = 0;

  while (sent < size)
  {
    uint8_t *p = buf + (half * XFER_CHUNK);
    half ^= 1U;

    UINT br = 0;
    if (f_read(&f, p, XFER_CHUNK, &br) != FR_OK) { bad = 1; break; }
    if (br == 0U) { bad = 2; break; }

    crc = record_crc32_update(crc, p, (uint32_t)br);
    if (console_write_cdc(p, (uint16_t)br) != 0) { bad = 3; break; }
    sent += (uint32_t)br;
  }

  uint32_t ms = (uint32_t)((timebase_now_us() - t0) / 1000ULL);
  arena_release(XFER_ARENA_OWNER);
  (void)f_close(&f);

  if (bad != 0)
  {
    /* The host is still counting bytes, so it will time out rather than be
       fooled. Say what happened anyway, for the session log. */
    console_printf("\r\nxfer: abort %d after %lu of %lu bytes\r\n",
                   bad, (unsigned long)sent, (unsigned long)size);
    return;
  }

  console_printf("xfer: end %08lX\r\n", (unsigned long)crc);
  console_printf("get: %lu bytes in %lu ms (%lu kB/s)\r\n",
                 (unsigned long)sent, (unsigned long)ms,
                 (unsigned long)(ms ? ((uint64_t)sent / ms) : 0U));
}

/* ==========================================================================
 * rm
 * ========================================================================== */

static void cmd_rm(int argc, char **argv)
{
  if (argc < 2)
  {
    console_printf("rm: usage: rm <file>\r\n");
    return;
  }
  if (storage_is_open())
  {
    console_printf("rm: a record is open\r\n");
    return;
  }
  if (!storage_is_mounted())
  {
    if (storage_mount() != 0) { return; }
  }

  char path[80];
  resolve(argv[1], path, sizeof path);

  FRESULT fr = f_unlink(path);
  console_printf("rm: %s: %s\r\n", path, fr_str(fr));
}

/* ========================================================================== */

static const console_cmd_t s_cmds[] = {
  { "ls",  "ls [dir] - list records on the card",        cmd_ls  },
  { "get", "get <file> - download a file over USB",      cmd_get },
  { "rm",  "rm <file> - delete a file from the card",    cmd_rm  },
};

void xfer_console_init(void)
{
  (void)console_register(s_cmds, (uint8_t)(sizeof s_cmds / sizeof s_cmds[0]));
}
