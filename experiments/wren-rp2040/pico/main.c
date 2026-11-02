#include "experiment.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/watchdog.h"
#include <malloc.h>
#include <stdio.h>
#include <stdint.h>
#include <unistd.h>
extern char __StackBottom, __StackTop, __end__, __HeapLimit;
uint64_t experiment_time_us(void) { return time_us_64(); }
void experiment_tick(void) { watchdog_update(); }
static void reboot(void) { watchdog_reboot(0, 0, 10); while (1) tight_loop_contents(); }
int main(void) {
    watchdog_enable(8000, true); /* first: clear RAM-boot magic, reset returns to flash */
    set_sys_clock_khz(125000, true);
    uintptr_t sp;
    __asm__ volatile("mov %0, sp" : "=r"(sp));
    uint32_t *lo = (uint32_t *)(((uintptr_t)&__StackBottom + 64) & ~3u);
    uint32_t *hi = (uint32_t *)((sp - 256) & ~3u);
    for (uint32_t *p = lo; p < hi; p++) *p = 0xCAFE1234;
    stdio_init_all();
    bool go = false;
    for (unsigned i = 0; i < 600; i++) {
        watchdog_update();
        if (stdio_usb_connected() && getchar_timeout_us(50000) == 'g') { go = true; break; }
        sleep_ms(50);
    }
    if (!go) reboot();
    printf("WR_INFO clk_hz=%lu stack_bottom=%p stack_top=%p heap_start=%p heap_limit=%p brk=%p\n",
           (unsigned long)clock_get_hz(clk_sys), &__StackBottom, &__StackTop, &__end__, &__HeapLimit, sbrk(0));
    /* The SRAM-only image leaves too little room for a 128 KiB malloc arena.
     * 1 KiB deliberately exercises OOM; larger budgets are host-only until
     * the ELF/allocator overhead analysis permits them on this target. */
    const size_t budgets[] = {1024, 32768, 65536, 98304};
    for (size_t i = 0; i < sizeof(budgets)/sizeof(budgets[0]); i++) {
        watchdog_update();
        int status = experiment(budgets[i], 2, 1);
        printf("WR_BUDGET bytes=%zu status=%d\n", budgets[i], status);
    }
    uint32_t *p = lo;
    while (p < hi && *p == 0xCAFE1234) p++;
    struct mallinfo mi = mallinfo();
    printf("WR_MEMORY stack_peak_upper=%lu stack_capacity=%lu arena=%d in_use=%d brk=%p\n",
           (unsigned long)((uintptr_t)&__StackTop - (uintptr_t)p),
           (unsigned long)((uintptr_t)&__StackTop - (uintptr_t)&__StackBottom), mi.arena, mi.uordblks, sbrk(0));
    puts("WR_DONE");
    for (int i = 0; i < 100; i++) {
        watchdog_update();
        if (getchar_timeout_us(100000) == 'r') break;
    }
    reboot();
}
