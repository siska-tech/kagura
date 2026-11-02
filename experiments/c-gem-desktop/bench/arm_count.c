// SPDX-License-Identifier: Apache-2.0
// kd_count: the benchmark workloads built for Cortex-M0+ (Thumb-1, no FPU, no
// hardware divide) as a freestanding Linux user-mode ELF, so qemu-arm can run
// it and count every executed instruction (tools/arm_report.sh). No libc
// start-up or stdio: a naked _start and two raw Linux syscalls.
//
//   kd_count WORKLOAD N
//
// Runs the same loop as the RP2040 benchmark (pico/main.c): setup, 4 warm-up
// and N measured samples of (pre, render, export) then (op, render, export).
// The measured region of each sample, op + render + export, is bracketed by
// calls to kd_mark_begin/kd_mark_end; the report counts only the executed
// instructions between them. (An earlier version subtracted a run without
// the op instead, which miscounted workloads whose pre-step only does work
// after the op, such as closing a menu the op opened.)
#include "workloads.h"

#define WARM 4

__attribute__((noinline, used)) void kd_mark_begin(void) { __asm__ volatile("" ::: "memory"); }
__attribute__((noinline, used)) void kd_mark_end(void) { __asm__ volatile("" ::: "memory"); }

static void sys_write(const char *s) {
    register long r0 __asm__("r0") = 1;
    register long r1 __asm__("r1") = (long)s;
    register long r2 __asm__("r2") = (long)strlen(s);
    register long r7 __asm__("r7") = 4;   // write
    __asm__ volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
}

static int to_int(const char *s) {
    int v = 0;
    while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0');
    return v;
}

__attribute__((used)) int kd_count_main(const long *sp) {
    int argc = (int)sp[0];
    char **argv = (char **)(sp + 1);
    if (argc != 3) {
        sys_write("usage: kd_count WORKLOAD N\n");
        return 2;
    }
    const workload *w = NULL;
    for (unsigned k = 0; k < KD_WORKLOAD_COUNT; k++)
        if (strcmp(workloads[k].name, argv[1]) == 0) w = &workloads[k];
    if (!w) {
        sys_write("unknown workload\n");
        return 2;
    }
    int n = to_int(argv[2]);
    kd_tile4_stats st;
    workloads_init();
    w->setup();
    kd_desktop_render(&S.desk);
    flush(&st);
    for (int i = -WARM; i < n; i++) {
        if (w->pre) {
            w->pre(i);
            kd_desktop_render(&S.desk);
            flush(&st);
        }
        if (i >= 0) kd_mark_begin();
        w->op(i);
        kd_desktop_render(&S.desk);
        flush(&st);
        if (i >= 0) kd_mark_end();
    }
    sys_write("done\n");
    return 0;
}

__attribute__((naked, noreturn)) void _start(void) {
    __asm__ volatile(
        "mov r0, sp\n\t"
        "bl kd_count_main\n\t"
        "movs r7, #1\n\t"   // exit(r0)
        "svc #0\n\t");
}
