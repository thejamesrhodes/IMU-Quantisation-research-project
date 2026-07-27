#include <sys/stat.h>
#include <errno.h>
#include <stdio.h>
#include <signal.h>
#include <sys/time.h>
#include <sys/times.h>

int _close(int file) { return -1; }

int _fstat(int file, struct stat *st)
{
  st->st_mode = S_IFCHR;
  return 0;
}

int _isatty(int file) { return 1; }

int _lseek(int file, int ptr, int dir) { return 0; }

int _read(int file, char *ptr, int len) { return 0; }

int _write(int file, char *ptr, int len) { return len; }

void _kill(int pid, int sig) { return; }

int _getpid(void) { return 1; }

caddr_t _sbrk(int incr)
{
  extern char _end;              /* set by linker script — end of .bss/heap start */
  extern char _estack;           /* set by linker script — top of stack/RAM       */
  static char *heap_end = 0;
  char *prev_heap_end;

  if (heap_end == 0) heap_end = &_end;
  prev_heap_end = heap_end;

  if (heap_end + incr > &_estack) {
    errno = ENOMEM;
    return (caddr_t) -1;
  }

  heap_end += incr;
  return (caddr_t) prev_heap_end;
}
