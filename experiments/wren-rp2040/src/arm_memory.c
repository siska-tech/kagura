/* CPU emulation ONLY: ARMv6-M code + newlib under qemu-arm Linux user mode.
 * Not Pico execution, not a Pico timing model. No hardware/device access.
 * Linux provides the native stack; the artificial malloc arena is 512 KiB. */
#include "experiment.h"
#include <errno.h>
#include <malloc.h>
#include <stdalign.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/times.h>
#include <stdint.h>
static alignas(max_align_t) unsigned char arena[512*1024];
static size_t used;
uint64_t experiment_time_us(void) { return 0; }
void experiment_tick(void) {}
void *_sbrk(ptrdiff_t n) {
    if (n < 0 || (size_t)n > sizeof(arena)-used) { errno = ENOMEM; return (void *)-1; }
    void *p = arena+used; used += (size_t)n; return p;
}
int _write(int fd, const void *data, size_t n) {
    register long r0 __asm__("r0") = fd;
    register long r1 __asm__("r1") = (long)data;
    register long r2 __asm__("r2") = (long)n;
    register long r7 __asm__("r7") = 4;
    __asm__ volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return (int)r0;
}
int _read(int fd, void *p, size_t n) { (void)fd; (void)p; (void)n; return 0; }
int _close(int fd) { (void)fd; return -1; }
int _fstat(int fd, struct stat *s) { (void)fd; s->st_mode = S_IFCHR; return 0; }
int _isatty(int fd) { (void)fd; return 1; }
off_t _lseek(int fd, off_t off, int whence) { (void)fd; (void)off; (void)whence; return 0; }
int _getpid(void) { return 1; }
clock_t _times(struct tms *t) { (void)t; return 0; }
int _kill(int pid, int sig) { (void)pid; (void)sig; return -1; }
__attribute__((noreturn)) void _exit(int code) {
    register long r0 __asm__("r0") = code;
    register long r7 __asm__("r7") = 1;
    __asm__ volatile("svc #0" : : "r"(r0), "r"(r7) : "memory");
    while (1) {}
}
__attribute__((used)) void arm_main(const long *sp) {
    int argc = sp[0]; char **argv = (char **)(sp+1);
    size_t budget = argc > 1 ? strtoul(argv[1], NULL, 10) : 128*1024;
    puts("INFO ARM emulation memory only: time fields are zero, not RP2040 results");
    int result = experiment(budget, 1, argc > 2);
    struct mallinfo mi = mallinfo();
    printf("ARM_MALLOC arena_high_water=%zu arena=%d in_use=%d\n", used, mi.arena, mi.uordblks);
    fflush(stdout); _exit(result);
}
__attribute__((naked,noreturn)) void _start(void) {
    __asm__ volatile("mov r0, sp\nbl arm_main\n");
}
