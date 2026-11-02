// SPDX-License-Identifier: Apache-2.0
// mp_count: MicroPython (embed port) with kagura_desktop, built for
// Cortex-M0+ as a freestanding Linux user-mode ELF like bench/arm_count.c, so
// qemu-arm can count the Thumb-1 instructions the VM and the binding execute.
// No libc start-up or stdio: a naked _start and two raw Linux syscalls.
//
//   mp_count WORKLOAD N     run bench/workloads.py's WORKLOAD for N samples
//   mp_count markers N      N empty kdmark brackets (the marker overhead)
#include <stdio.h>
#include <string.h>

#include "port/micropython_embed.h"
#include "py/mphal.h"
#include "workloads_py.h"   // generated: bench/workloads.py + driver.py as a C string

static char heap[128 * 1024];

__attribute__((noinline, used)) void kd_mark_begin(void) { __asm__ volatile("" ::: "memory"); }
__attribute__((noinline, used)) void kd_mark_end(void) { __asm__ volatile("" ::: "memory"); }

static void sys_write(const char *s, size_t n) {
    register long r0 __asm__("r0") = 1;
    register long r1 __asm__("r1") = (long)s;
    register long r2 __asm__("r2") = (long)n;
    register long r7 __asm__("r7") = 4;   // write
    __asm__ volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
}

void mp_hal_stdout_tx_strn_cooked(const char *str, size_t len) { sys_write(str, len); }
mp_uint_t mp_hal_ticks_ms(void) { return 0; }   // the workloads pass explicit event times
void *_sbrk(int incr) {   // newlib may link malloc; nothing here allocates outside the GC heap
    (void)incr;
    return (void *)-1;
}

__attribute__((used)) int kd_count_main(const long *sp) {
    int argc = (int)sp[0];
    char **argv = (char **)(sp + 1);
    if (argc != 3) {
        sys_write("usage: mp_count WORKLOAD|markers N\n", 35);
        return 2;
    }
    int stack_top;
    mp_embed_init(heap, sizeof heap, &stack_top);
    mp_embed_exec_str(kd_workloads_py);
    char cmd[96];
    if (strcmp(argv[1], "markers") == 0) snprintf(cmd, sizeof cmd, "markers(%s)\n", argv[2]);
    else snprintf(cmd, sizeof cmd, "count('%s', %s)\n", argv[1], argv[2]);
    mp_embed_exec_str(cmd);
    mp_embed_deinit();
    return 0;
}

__attribute__((naked, noreturn, used)) void _start(void) {
    __asm__ volatile(
        "mov r0, sp\n"
        "bl kd_count_main\n"
        "movs r7, #1\n"   // exit
        "svc #0\n");
}
