/**
  ******************************************************************************
  * @file    arena.c
  * @brief   The one large RAM block, shared by fwupdate and storage.
  ******************************************************************************
  */

#include "arena.h"
#include "console.h"

/* 8-byte aligned: the SD writer hands slices of this straight to FATFS and
   the FIFO sampler hands them straight to the SPI DMA, and both are happier
   word-aligned. */
static uint8_t     s_arena[ARENA_SIZE] __attribute__((aligned(8)));
static const char *s_owner = NULL;

uint8_t *arena_claim(const char *owner)
{
  if (owner == NULL)
  {
    return NULL;
  }

  if (s_owner != NULL)
  {
    if (s_owner == owner)
    {
      return s_arena;                  /* idempotent for the same owner */
    }
    console_printf("arena: refused to '%s', held by '%s'\r\n", owner, s_owner);
    return NULL;
  }

  s_owner = owner;
  return s_arena;
}

void arena_release(const char *owner)
{
  /* Pointer comparison, not strcmp: owners are static literals, and this way
     a caller cannot release a buffer it never held by passing a matching
     string. */
  if (s_owner == owner)
  {
    s_owner = NULL;
  }
}

const char *arena_owner(void)
{
  return s_owner;
}
