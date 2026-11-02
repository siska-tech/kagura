// SPDX-License-Identifier: Apache-2.0
// SRAM-only RP2040 CPU benchmark of the C desktop core (no KAGURA FPGA I/O).
//
// Built as a Pico SDK no_flash binary: every byte is loaded into SRAM and the
// program never calls a flash API (they panic in no_flash builds anyway). It
// touches no GPIO other than USB. Results go to USB CDC as "KDRP..." lines.
//
// Safety: the watchdog is enabled first. watchdog_enable() replaces the
// boot-to-RAM magic in scratch[4], so a hang, fault or the final reboot
// returns to the normal flash boot (the installed MicroPython).
//
// Protocol: wait for a USB host, wait for 'g', print results, print
// KDRP_DONE, then reboot into flash on 'r' or after 10 s.
#include <malloc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "hardware/clocks.h"
#include "hardware/structs/systick.h"
#include "hardware/sync.h"
#include "hardware/watchdog.h"
#include "pico/stdlib.h"
#include "workloads.h"

#ifndef KD_RP_VARIANT
#define KD_RP_VARIANT "sdk"
#endif
#define GUARD_WORD 0xC0DEFA11u
#define SAMPLES 32
#define WARM 4
#define CRC_SAMPLES 8

extern char __logical_binary_start, __etext, __data_start__, __bss_start__, __bss_end__, __end__;
extern char __StackLimit, __StackBottom, __StackTop, __scratch_x_start__, __scratch_x_end__;

static uint32_t cycles_render[SAMPLES], cycles_export[SAMPLES], cycles_total[SAMPLES];

static void paint(uint32_t *a, uint32_t *b) {
    while (a < b) *a++ = GUARD_WORD;
}

// Number of guard words still intact counted upwards from a.
static uint32_t intact_from(const uint32_t *a, const uint32_t *b) {
    const uint32_t *p = a;
    while (p < b && *p == GUARD_WORD) p++;
    return (uint32_t)(p - a);
}

static uint32_t intact_all(const uint32_t *a, const uint32_t *b) {
    uint32_t n = 0;
    for (const uint32_t *p = a; p < b; p++) n += *p == GUARD_WORD;
    return n;
}

static inline uint32_t systick(void) { return systick_hw->cvr; }

static uint32_t elapsed(uint32_t start, uint32_t end, uint32_t us) {
    uint32_t c = (start - end) & 0xFFFFFFu;   // SysTick counts down, 24 bits
    // Beyond about 100 ms at 125 MHz the counter may have wrapped.
    return us > 100000u ? (uint32_t)((uint64_t)us * clock_get_hz(clk_sys) / 1000000u) : c;
}

static int cmp_u32(const void *a, const void *b) {
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return x < y ? -1 : x > y;
}

static void wait_usb(void) {
    for (int i = 0; i < 300 && !stdio_usb_connected(); i++) {   // 30 s
        watchdog_update();
        sleep_ms(100);
    }
    if (!stdio_usb_connected()) watchdog_reboot(0, 0, 10);
}

static void wait_char(int want, int seconds) {
    for (int i = 0; i < seconds * 10; i++) {
        watchdog_update();
        if (getchar_timeout_us(100000) == want) return;
    }
}

static void measure(const workload *w) {
    kd_tile4_stats st;
    w->setup();
    kd_desktop_render(&S.desk);
    flush(&st);
    uint32_t tiles = 0, bytes = 0;
    for (int i = -WARM; i < SAMPLES; i++) {
        watchdog_update();
        if (w->pre) {
            w->pre(i);
            kd_desktop_render(&S.desk);
            flush(&st);
        }
        uint32_t irq = save_and_disable_interrupts();
        uint32_t u0 = time_us_32(), t0 = systick();
        w->op(i);
        kd_desktop_render(&S.desk);
        uint32_t t1 = systick(), u1 = time_us_32();
        flush(&st);
        uint32_t t2 = systick(), u2 = time_us_32();
        restore_interrupts(irq);
        if (i < 0) continue;
        cycles_render[i] = elapsed(t0, t1, u1 - u0);
        cycles_export[i] = elapsed(t1, t2, u2 - u1);
        cycles_total[i] = elapsed(t0, t2, u2 - u0);
        tiles += st.tiles;
        bytes += st.bytes;
        sleep_us(500);   // let USB catch up between samples
    }
    qsort(cycles_render, SAMPLES, sizeof(uint32_t), cmp_u32);
    qsort(cycles_export, SAMPLES, sizeof(uint32_t), cmp_u32);
    qsort(cycles_total, SAMPLES, sizeof(uint32_t), cmp_u32);
    printf("KDRP_TIME %s render_p50 %lu p90 %lu max %lu export_p50 %lu total_p50 %lu total_max %lu tiles %lu bytes %lu\n",
           w->name, (unsigned long)cycles_render[SAMPLES / 2], (unsigned long)cycles_render[SAMPLES * 9 / 10],
           (unsigned long)cycles_render[SAMPLES - 1], (unsigned long)cycles_export[SAMPLES / 2],
           (unsigned long)cycles_total[SAMPLES / 2], (unsigned long)cycles_total[SAMPLES - 1],
           (unsigned long)(tiles / SAMPLES), (unsigned long)(bytes / SAMPLES));
}

int main(void) {
    watchdog_enable(8000, true);   // also clears the boot-to-RAM magic
    set_sys_clock_khz(125000, true);   // the clock of the estimates and KAGURA-UI records
    // Guard regions: the unused core-1 stack (scratch X), the stack below
    // the current frame, and all main RAM above the heap.
    uint32_t sp_now;
    __asm__ volatile("mov %0, sp" : "=r"(sp_now));
    uint32_t *stack_lo = (uint32_t *)(((uintptr_t)&__StackBottom + 64u) & ~3u);   // above the MPU guard
    uint32_t *stack_hi = (uint32_t *)((sp_now - 256u) & ~3u);
    uint32_t *sx_lo = (uint32_t *)&__scratch_x_end__, *sx_hi = (uint32_t *)0x20041000u;
    // Linker symbols are 1-byte objects to the compiler: compute addresses as integers.
    uint32_t *heap_hi = (uint32_t *)((uintptr_t)&__StackLimit - 256u);   // keep clear of the very top
    paint(stack_lo, stack_hi);
    paint(sx_lo, sx_hi);
    stdio_init_all();
    uint32_t *free_lo = (uint32_t *)(((uintptr_t)sbrk(0) + 3u) & ~3u);
    paint(free_lo, heap_hi);
    systick_hw->rvr = 0xFFFFFFu;
    systick_hw->cvr = 0;
    systick_hw->csr = 5;   // processor clock, no interrupt
    wait_usb();
    wait_char('g', 60);

    printf("KDRP_INFO variant %s clk_sys_hz %lu fc0_khz %lu samples %d warm %d\n", KD_RP_VARIANT,
           (unsigned long)clock_get_hz(clk_sys),
           (unsigned long)frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLK_SYS), SAMPLES, WARM);
    printf("KDRP_LAYOUT image_start %p etext %p data %p bss %p..%p end %p stack %p..%p scratch_x_end %p\n",
           (void *)&__logical_binary_start, (void *)&__etext, (void *)&__data_start__, (void *)&__bss_start__,
           (void *)&__bss_end__, (void *)&__end__, (void *)&__StackBottom, (void *)&__StackTop,
           (void *)&__scratch_x_end__);
    workloads_init();
    for (unsigned k = 0; k < KD_WORKLOAD_COUNT; k++) {
        watchdog_update();
        printf("KDRP_CRC %s %08lx\n", workloads[k].name, (unsigned long)workload_crc(&workloads[k], CRC_SAMPLES));
    }
    for (unsigned k = 0; k < KD_WORKLOAD_COUNT; k++) measure(&workloads[k]);

    struct mallinfo mi = mallinfo();
    uint32_t stack_words = (uint32_t)(stack_hi - stack_lo), stack_free = intact_from(stack_lo, stack_hi);
    printf("KDRP_MEM static_bytes %lu heap_arena %lu heap_inuse %lu stack_size %lu stack_peak_bytes %lu "
           "stack_guard_words %lu/%lu scratch_x_words %lu/%lu free_ram_words %lu/%lu\n",
           (unsigned long)((uintptr_t)&__end__ - (uintptr_t)&__logical_binary_start), (unsigned long)mi.arena,
           (unsigned long)mi.uordblks, (unsigned long)((uintptr_t)&__StackTop - (uintptr_t)&__StackBottom),
           (unsigned long)((uintptr_t)&__StackTop - (uintptr_t)(stack_lo + stack_free)),
           (unsigned long)stack_free, (unsigned long)stack_words,
           (unsigned long)intact_all(sx_lo, sx_hi), (unsigned long)(sx_hi - sx_lo),
           (unsigned long)intact_all(free_lo, heap_hi), (unsigned long)(heap_hi - free_lo));
    printf("KDRP_DONE\n");
    wait_char('r', 10);
    stdio_flush();
    sleep_ms(50);
    watchdog_reboot(0, 0, 10);   // regular flash boot: back to MicroPython
    for (;;) tight_loop_contents();
}
