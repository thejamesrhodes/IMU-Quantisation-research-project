/**
  ******************************************************************************
  * @file    fwupdate.h
  * @brief   Self-flashing firmware update over the CDC endpoints.
  *
  * Replaces the ST-LINK in the edit-build-flash loop. No bootloader, no
  * second image, no relink: the running application receives its replacement,
  * stages it in SRAM, and overwrites itself from a routine executing in RAM.
  *
  * WIRE PROTOCOL
  *
  *   host -> `fw <size> <crc32hex>\r\n`      on the normal console
  *   dev  -> `FWREADY <n>\r\n`               n = bytes it will accept
  *   host -> <size> raw bytes                (nothing else on the link)
  *   dev  -> `FWRECV <size>\r\n`
  *   dev  -> `FWCRC ok\r\n`   | `FWCRC bad ...\r\n`
  *   dev  -> `FWVEC ok\r\n`   | `FWVEC bad ...\r\n`
  *   dev  -> `FWPROG\r\n`                    last thing you will hear
  *           <USB detaches, flash is erased and rewritten, board resets>
  *
  *   Any failure returns `FWABORT <reason>\r\n` and leaves flash untouched.
  *
  * The host MUST wait for `FWREADY` before streaming. Bytes that arrive in
  * the same USB packet as the command line go to the console parser, not the
  * staging buffer, and would be lost.
  *
  * CRC-32 is the zlib/IEEE-802.3 variant: reflected, poly 0xEDB88320, init
  * 0xFFFFFFFF, final XOR 0xFFFFFFFF. Chosen so the host side is one call to
  * `zlib.crc32`. It is deliberately NOT the STM32 hardware CRC unit, which
  * computes the non-reflected MPEG-2 variant and would not match.
  ******************************************************************************
  */

#ifndef FWUPDATE_H
#define FWUPDATE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
  * @brief  Register the `fw` console command. Call once from main(), after
  *         console_init().
  */
void fw_init(void);

/**
  * @brief  Main-loop step: transfer timeout, verification, and the trigger.
  *         Call every iteration.
  */
void fw_task(void);

/**
  * @brief  Consume received bytes if an image transfer is in progress.
  *
  *         Called from CDC_Receive_HS, i.e. USB interrupt context, BEFORE
  *         console_rx_feed(). Copies straight into the staging buffer: the
  *         console's 256-byte ring cannot absorb 512-byte high-speed bulk
  *         packets arriving faster than the main loop drains them.
  *
  * @retval 1 if the bytes were consumed as image data, 0 to pass them on to
  *         the console.
  */
int fw_rx_isr(const uint8_t *buf, uint32_t len);

/**
  * @brief  Non-zero while a transfer or programming operation is in progress.
  *         Other modules should stay quiet on the console while this is set.
  */
int fw_busy(void);

#ifdef __cplusplus
}
#endif

#endif /* FWUPDATE_H */
