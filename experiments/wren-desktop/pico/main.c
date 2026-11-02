#include "runtime.h"
#include "ui.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/watchdog.h"
#include <malloc.h>
#include <stdio.h>
extern char __StackBottom,__StackTop,__end__,__HeapLimit,__recovery_start,__recovery_end;
void wd_platform_tick(void) { watchdog_update(); }
static const kh_config config={KH_QSPI,2,2,6,7,8,9,10};
int main(void) {
    watchdog_enable(8000,true);
    set_sys_clock_khz(125000,true);
    uintptr_t sp; __asm__ volatile("mov %0, sp":"=r"(sp));
    uint32_t *lo=(uint32_t *)(((uintptr_t)&__StackBottom+64)&~3u), *hi=(uint32_t *)((sp-256)&~3u);
    for (uint32_t *p=lo;p<hi;p++) *p=0xcafe1234;
    uint32_t *reserve=(uint32_t *)&__recovery_start,*reserve_end=(uint32_t *)&__recovery_end;
    for (uint32_t *p=reserve;p<reserve_end;p++) *p=0xface1357;
    stdio_init_all();
    bool go=false;
    for (unsigned i=0;i<600;i++) {
        watchdog_update();
        if (stdio_usb_connected() && getchar_timeout_us(50000)=='g') { go=true; break; }
        sleep_ms(50);
    }
    if (go) {
        /* No device access before explicit serial start; hardware execution
           is NOT authorized by building this ELF. HAL sources are unchanged. */
        kh_init(&config);
        int status=wd_run(98304,20,false,true,0,0);
        const wd_metrics *m=wd_last_metrics();
        uint32_t *p=lo; while (p<hi && *p==0xcafe1234) p++;
        bool intact=true; for (uint32_t *q=reserve;q<reserve_end;q++) if (*q!=0xface1357) intact=false;
        struct mallinfo mi=mallinfo();
        printf("WD_RESULT status=%d init=%zu compiled=%zu peak=%zu ledger_peak=%zu shutdown=%zu allocs=%zu frees=%zu gc=%u foreign=%u completed=%u stack_peak_upper=%lu stack_reserved=49152 recovery_intact=%d malloc_arena=%u malloc_used=%u heap_start=%p heap_limit=%p arena_peak=%zu used_peak=%zu utf8=%u\n",
               status,m->init_live,m->compile_live,m->peak,m->ledger_peak,m->live,m->allocations,m->frees,m->collections,m->foreign_calls,m->completed,
               (unsigned long)((uintptr_t)&__StackTop-(uintptr_t)p),intact,mi.arena,mi.uordblks,&__end__,&__HeapLimit,m->arena_peak,m->used_peak,m->utf8_outputs);
        kh_deinit();
    }
    /* Flash-resident watchdog reset restarts THIS firmware, not MicroPython.
       No flash programming/restore operation exists in this program. */
    stdio_flush(); sleep_ms(20); watchdog_reboot(0,0,10);
    while (1) tight_loop_contents();
}
