/**
  ******************************************************************************
  * @file    xfer.h
  * @brief   Bulk file download over the CDC link.
  *
  * WHY THIS EXISTS
  *   The records live on a microSD card soldered to the board, and the only
  *   host connection is the USB-C port. Without a download path the entire
  *   campaign dataset is trapped on hardware that cannot be read by anything
  *   else -- so this is not a convenience, it is the only route from instrument
  *   to analysis. TN-18's original scope called for it as "bulk binary download
  *   afterwards of SD records".
  *
  * PROTOCOL
  *   The console is line-oriented, so the transfer announces itself with a line,
  *   sends exactly the announced number of raw bytes, and closes with a line:
  *
  *       > get SHEPPARD/r45944_smoke_100Hz.sdat
  *       xfer: begin <bytes> <name>
  *       <bytes raw bytes, no framing, no escaping>
  *       xfer: end <crc32hex>
  *
  *   The host reads lines until it sees `xfer: begin`, then reads exactly that
  *   many bytes, then one more line. Because the length is known up front the
  *   payload needs no escaping and may contain any byte sequence including CRLF.
  *
  *   The CRC accumulates over exactly the bytes handed to the endpoint, using
  *   the same zlib/IEEE polynomial as the block CRCs inside the record. It is
  *   an end-to-end check of the whole path -- card, FATFS, USB, host -- and is
  *   independent of the per-block CRCs, which only prove the blocks were
  *   written correctly in the first place. Both must pass before a record is
  *   considered landed.
  *
  * THE UART MIRROR IS SUPPRESSED DURING TRANSFER
  *   console_write() fans out to every enabled sink. Mirroring 13 MB to a
  *   115200 baud UART would take twenty minutes and would pace the whole
  *   transfer at 11 kB/s, so the payload goes to CDC only.
  ******************************************************************************
  */

#ifndef XFER_H
#define XFER_H

#ifdef __cplusplus
extern "C" {
#endif

/** Register the `ls`, `get` and `rm` commands. Call once from main(). */
void xfer_console_init(void);

#ifdef __cplusplus
}
#endif

#endif /* XFER_H */
