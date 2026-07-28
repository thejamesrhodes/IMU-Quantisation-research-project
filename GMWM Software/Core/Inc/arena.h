/**
  ******************************************************************************
  * @file    arena.h
  * @brief   The one large RAM block, shared by the two subsystems that need it.
  *
  * WHY THIS EXISTS
  *   The 27 July linker split moved .data and .bss out of DTCM into the
  *   192 KiB SRAM1+SRAM2 region, so DMA buffers are reachable by construction.
  *   That left two consumers wanting most of the same memory:
  *
  *     fwupdate.c   a staging buffer for the whole firmware image before it
  *                  erases flash -- must exceed the image, ~80 KiB and growing
  *     storage.c    a ring buffer between the FIFO sampler and the SD writer,
  *                  sized by the worst-case SD write stall
  *
  *   128 + 128 KiB does not fit in 192. But they are never in use at the same
  *   time: you do not flash firmware in the middle of a record, and you do not
  *   start a record while an image is being written. So they overlay, with a
  *   runtime guard rather than a comment.
  *
  * DISCIPLINE
  *   Call arena_claim() before use and arena_release() after. A second claim
  *   while another owner holds it fails and says who has it. Both subsystems
  *   check, so the failure mode is a clear refusal rather than two writers
  *   silently corrupting each other's buffer.
  *
  *   The memory is in .bss, hence SRAM1, hence DMA-reachable.
  ******************************************************************************
  */

#ifndef ARENA_H
#define ARENA_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Total shared block. Sized so that fwupdate's staging need (the image, with
    headroom) and storage's ring need (stall x rate) are both met, and so that
    everything else still fits in the 192 KiB region. Check the .map after
    changing it; the link fails loudly with "region RAM overflowed".

    RAISED 128 -> 144 KiB, 28 Jul 2026. The image reached 131,268 bytes at
    Stage B and the self-flasher refused it -- the staging buffer must exceed
    the image it stages, so the limit grows with the firmware.

    Must stay a multiple of SDAT_BLOCK_BYTES (4096): 144 KiB gives 36 ring
    blocks, which at ODR 8000 is 900 ms of SD-stall absorption.

    THE TREND IS THE PROBLEM, not this number. The image grows roughly a stage
    at a time and the region is 192 KiB. The real answer is -O2, which would
    roughly halve it -- but optimisation level is a science parameter (TN-16
    open item 20: it affects SPI timing and must be recorded in every header),
    so that is a deliberate, logged treatment change and not a convenience. */
#define ARENA_SIZE  (144U * 1024U)

/**
  * @brief  Claim the arena.
  * @param  owner short static string, used in the refusal message
  * @retval pointer to ARENA_SIZE bytes, or NULL if someone else holds it
  */
uint8_t *arena_claim(const char *owner);

/**
  * @brief  Release it. Only the current owner may release; anything else is
  *         ignored, so a stale release cannot free someone else's buffer.
  */
void arena_release(const char *owner);

/** Current owner, or NULL. */
const char *arena_owner(void);

/** Total size, for callers that want to size themselves against it. */
static inline size_t arena_size(void) { return ARENA_SIZE; }

#ifdef __cplusplus
}
#endif

#endif /* ARENA_H */
