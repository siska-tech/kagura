/* CPU emulation ONLY: ARMv6-M code + newlib under qemu-arm Linux user mode.
 * Not Pico execution, not a Pico timing model. No hardware/device access.
 * Linux provides the native stack; the artificial malloc arena is 512 KiB. */
#include "experiment.h"
#include <errno.h>
#include <malloc.h>
#include <stdalign.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/times.h>
#include <stdint.h>
static alignas(max_align_t) unsigned char arena[512*1024];
static size_t used;
static size_t arena_limit = sizeof(arena);
static size_t sbrk_failures;
static size_t arena_high_water;
static size_t last_sbrk_failure;
static uint32_t *paint_lo, *paint_hi;
static uintptr_t stack_top;
uint64_t experiment_time_us(void) { return 0; }
void experiment_tick(void) {}
void *_sbrk(ptrdiff_t n) {
    void *p = arena + used;
    if (n < 0) {
        if ((size_t)(-n) > used) { errno = ENOMEM; return (void *)-1; }
        used -= (size_t)(-n); return p;
    }
    if ((size_t)n > arena_limit-used) { sbrk_failures++; last_sbrk_failure = (size_t)n; errno = ENOMEM; return (void *)-1; }
    used += (size_t)n;
    if (used > arena_high_water) arena_high_water = used;
    return p;
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
    if (argc > 4) arena_limit = strtoul(argv[4], NULL, 10);
    if (!arena_limit || arena_limit > sizeof(arena)) _exit(2);
    uintptr_t current_sp;
    __asm__ volatile("mov %0, sp" : "=r"(current_sp));
    stack_top = (uintptr_t)sp; /* include arm_main's own frame in the high-water */
    paint_lo = (uint32_t *)(stack_top - 128*1024);
    paint_hi = (uint32_t *)(current_sp - 256);
    for (uint32_t *p = paint_lo; p < paint_hi; p++) *p = 0xACEDBEEF;
    puts("INFO ARM emulation memory only: time fields are zero, not RP2040 results");
    if (argc > 6) {
        int system_oom = !strcmp(argv[6], "malloc-recovery");
        int failed = experiment_named(system_oom ? 262144 : 82000, 1, 0, system_oom ? "strings" : "small_gui");
        if (failed != 1) _exit(2);
    }
    int result = experiment_named(budget, argc > 5 ? (unsigned)strtoul(argv[5], NULL, 10) : 1,
                                  argc > 2 && strcmp(argv[2], "plain"), argc > 3 && strcmp(argv[3], "all") ? argv[3] : NULL);
    struct mallinfo mi = mallinfo();
    uint32_t *p = paint_lo;
    while (p < paint_hi && *p == 0xACEDBEEF) p++;
    printf("ARM_MALLOC arena_high_water=%zu arena=%u in_use=%u limit=%zu stack_painted_upper=%lu sbrk_failures=%zu brk_now=%zu last_sbrk_failure=%zu\n", arena_high_water, mi.arena, mi.uordblks, arena_limit,
           (unsigned long)(stack_top - (uintptr_t)p), sbrk_failures, used, last_sbrk_failure);
    fflush(stdout); _exit(result);
}
__attribute__((naked,noreturn)) void _start(void) {
    __asm__ volatile("mov r0, sp\nbl arm_main\n");
}
