#include "runtime.h"
#include "diagnostics.h"
#include "ui.h"
#include "pico/stdlib.h"
#include "pico/bootrom.h"
#include "hardware/clocks.h"
#include "hardware/watchdog.h"
#include <malloc.h>
#include <stdio.h>
extern char __StackBottom,__StackTop,__end__,__HeapLimit,__recovery_start,__recovery_end;
void wd_platform_tick(void) { watchdog_update(); }
uint64_t wd_platform_us(void) { return time_us_64(); }
static const kh_config config={KH_QSPI,2,2,6,7,8,9,10};
static unsigned visual_frame;
static uint32_t crc_byte(uint32_t c,uint8_t b) {
    c^=b; for (unsigned j=0;j<8;j++) c=(c>>1)^(0xedb88320u&(0u-(c&1u))); return c;
}
static void finish(const char *reason) __attribute__((noreturn));
static void finish(const char *reason) {
    printf("WD_STOP %s recovery=BOOTSEL\n",reason); stdio_flush(); sleep_ms(100);
    /* Explicit ROM recovery after testing, without firmware writes.
       USB reset interfaces, watchdog and MPU guards retain their settings. */
    reset_usb_boot(0,0);
    while (1) tight_loop_contents();
}
static void visual(void) {
    kd_desktop *d=wd_ui_desktop(); uint8_t expected[32],actual[32];
    uint32_t a=~0u,b=~0u; unsigned mismatch=0;
    uint64_t start=time_us_64();
    for (unsigned t=0;t<KD_TILES;t++) {
        watchdog_update(); kd_tile4_pack_tile(&d->fb,t,expected);
        kh_status status=kh_vram_read(t*32,actual,32);
        if (status!=KH_OK) { printf("WD_READ_ERROR tile=%u status=%d\n",t,status); finish("readback_failure"); }
        for (unsigned i=0;i<32;i++) { a=crc_byte(a,expected[i]); b=crc_byte(b,actual[i]); mismatch+=expected[i]!=actual[i]; }
    }
    printf("WD_FRAME frame=%u expected=%08lx actual=%08lx mismatch=%u readback_us=%llu dirty=%u ack_runs=%u ack_tiles=%u\n",
           visual_frame,(unsigned long)~a,(unsigned long)~b,mismatch,time_us_64()-start,kd_fb_dirty_count(&d->fb),
           wd_ui_transport()->acknowledged_runs,wd_ui_transport()->acknowledged_tiles);
    if (mismatch) finish("framebuffer_corruption");
    /* Capture waits/readback are excluded from the separately reset timed run. */
    stdio_flush(); bool next=false;
    for (unsigned i=0;i<1200;i++) { watchdog_update(); if (getchar_timeout_us(50000)=='n') { next=true; break; } }
    if (!next) finish("capture_timeout");
    visual_frame++;
}
static bool metrics(const char *name,int status) {
    const wd_metrics *m=wd_last_metrics();
    printf("WD_MEMORY name=%s status=%d init=%zu compile=%zu gc_live=%zu peak=%zu ledger_peak=%zu arena_peak=%zu used_peak=%zu live=%zu blocks=%zu allocs=%zu reallocs=%zu frees=%zu largest=%zu gc=%u foreign=%u completed=%u utf8=%u oom=%d fail_stage=%u owned=%d\n",
           name,status,m->init_live,m->compile_live,m->gc_live,m->peak,m->ledger_peak,m->arena_peak,m->used_peak,m->live,m->blocks,
           m->allocations,m->reallocations,m->frees,m->largest,m->collections,m->foreign_calls,m->completed,m->utf8_outputs,m->oom_kind,m->fail_stage,wd_ui_owned());
    return m->live==0 && m->blocks==0 && m->allocations==m->frees && !wd_ui_owned();
}
static bool balanced_run(const char *name,size_t cap,unsigned rounds,unsigned injection,int expected,int kind) {
    watchdog_update(); int status=wd_run(cap,rounds,false,true,injection,0);
    return metrics(name,status) && status==expected && wd_last_metrics()->oom_kind==kind;
}
int main(void) {
    bool watchdog_boot=watchdog_enable_caused_reboot();
    unsigned reset_reason=watchdog_hw->reason;
    watchdog_enable(8000,true); set_sys_clock_khz(125000,true);
    uintptr_t sp; __asm__ volatile("mov %0, sp":"=r"(sp));
    uint32_t *lo=(uint32_t *)(((uintptr_t)&__StackBottom+64)&~3u), *hi=(uint32_t *)((sp-256)&~3u);
    for (uint32_t *p=lo;p<hi;p++) *p=0xcafe1234;
    uint32_t *reserve=(uint32_t *)&__recovery_start,*reserve_end=(uint32_t *)&__recovery_end;
    for (uint32_t *p=reserve;p<reserve_end;p++) *p=0xface1357;
    stdio_init_all(); bool go=false;
    for (unsigned i=0;i<1200;i++) { watchdog_update(); if (stdio_usb_connected() && getchar_timeout_us(50000)=='g') { go=true; break; } sleep_ms(50); }
    if (!go) finish("start_timeout");
    printf("WD_BOOT watchdog=%d reset_reason=%u hz=%lu heap_start=%p heap_limit=%p stack_bottom=%p stack_top=%p recovery_start=%p recovery_end=%p\n",
           watchdog_boot,reset_reason,(unsigned long)clock_get_hz(clk_sys),&__end__,&__HeapLimit,&__StackBottom,&__StackTop,&__recovery_start,&__recovery_end);
    if (watchdog_boot) finish("unexpected_watchdog_reset");
    kh_init(&config);
    uint8_t ids[5],height,low,high,error;
    kh_status s=kh_wait_ready(100000);
    if (s==KH_OK) s=kh_read(KAGURA_REG_ID0,true,ids,5);
    if (s==KH_OK) s=kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT,&height);
    if (s==KH_OK) s=kh_ext_read(KAGURA_EXT_PATTERN_COUNT_L,&low);
    if (s==KH_OK) s=kh_ext_read(KAGURA_EXT_PATTERN_COUNT_H,&high);
    if (s==KH_OK) s=kh_read_reg(KAGURA_REG_ERROR_CODE,&error);
    if (s!=KH_OK) finish("preflight_io");
    printf("WD_ABI id=%02x%02x abi=%u.%u caps=%02x height=%u patterns=%u error=%02x qspi_mhz=5 io0=2 sck=6 cs=7 busy=8 ready=9 irq=10\n",ids[0],ids[1],ids[2],ids[3],ids[4],height,low|(high<<8),error);
    if (ids[0]!=KAGURA_ID0 || ids[1]!=KAGURA_ID1 || ids[2]!=0 || ids[3]!=6 || height!=240 || (low|(high<<8))!=1200 || error) finish("preflight_mismatch");
    wd_ui_observer(visual);
    if (!balanced_run("visual",98304,1,0,0,0) || visual_frame!=7) finish("visual_failure");
    wd_ui_observer(NULL); wd_diag_reset();
    if (!balanced_run("timed",98304,20,0,0,0)) finish("timed_failure");
    static const char *names[WD_SPANS]={"open","rect","event","present","gc","call","init","compile"};
    for (unsigned i=0;i<WD_SPANS;i++) { wd_span *p=&wd_spans[i]; printf("WD_LATENCY name=%s count=%lu min_us=%lu max_us=%lu total_us=%llu\n",names[i],(unsigned long)p->count,(unsigned long)p->minimum,(unsigned long)p->maximum,p->total); }
    if (!balanced_run("limit",32768,1,0,1,1)) finish("limit_failure");
    if (!balanced_run("owned_oom",98304,1,3,1,3)) finish("owned_oom_failure");
    if (!balanced_run("native_oom",262144,1,6,1,2)) finish("native_oom_failure");
    for (unsigned i=0;i<20;i++) if (!balanced_run("fresh",98304,1,0,0,0)) finish("fresh_failure");
    uint32_t *p=lo; while (p<hi && *p==0xcafe1234) p++;
    bool intact=true; for (uint32_t *q=reserve;q<reserve_end;q++) if (*q!=0xface1357) intact=false;
    unsigned canary=0; for (uint32_t *q=lo;q<lo+16;q++) if (*q==0xcafe1234) canary++;
    struct mallinfo mi=mallinfo();
    printf("WD_GUARDS stack_peak_upper=%lu stack_reserved=49152 bottom_canary_words=%u recovery_intact=%d malloc_arena=%u malloc_used=%u\n",(unsigned long)((uintptr_t)&__StackTop-(uintptr_t)p),canary,intact,mi.arena,mi.uordblks);
    if (!intact || canary!=16 || mi.arena>135168) finish("guard_failure");
    kh_stats *stats=kh_get_stats();
    printf("WD_TRANSPORT bytes=%llu transactions=%llu busy_waits=%llu busy_wait_us=%llu\n",stats->bytes_sent,stats->transactions,stats->busy_waits,stats->busy_wait_us);
    kh_deinit(); finish("PASS");
}
