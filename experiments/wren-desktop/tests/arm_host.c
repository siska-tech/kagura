/* CPU-only ARM/newlib harness, adapted from PR #69's Linux syscall host.
   Not a Pico executable, not a peripheral or cycle model. */
#include "runtime.h"
#include "mock_hal.h"
#include <malloc.h>
#include <stdalign.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/times.h>
#include <sys/types.h>
static alignas(max_align_t) unsigned char arena[512*1024];
static size_t used,high_water,limit=135168,failures;
void wd_platform_tick(void) {}
uint64_t wd_platform_us(void) { return 0; }
void *_sbrk(ptrdiff_t n) {
    void *p=arena+used;
    if (n<0) { if ((size_t)(-n)>used) return (void *)-1; used-=(size_t)(-n); return p; }
    if ((size_t)n>limit-used) { errno=ENOMEM; failures++; return (void *)-1; }
    used+=(size_t)n; if (used>high_water) high_water=used; return p;
}
int _write(int fd,const void *data,size_t n) {
    register long r0 __asm__("r0")=fd,r1 __asm__("r1")=(long)data,r2 __asm__("r2")=(long)n,r7 __asm__("r7")=4;
    __asm__ volatile("svc #0":"+r"(r0):"r"(r1),"r"(r2),"r"(r7):"memory"); return (int)r0;
}
int _read(int fd,void *p,size_t n) { (void)fd;(void)p;(void)n;return 0; }
int _close(int fd) { (void)fd;return -1; }
int _fstat(int fd,struct stat *s) { (void)fd;s->st_mode=S_IFCHR;return 0; }
int _isatty(int fd) { (void)fd;return 1; }
off_t _lseek(int fd,off_t n,int whence) { (void)fd;(void)n;(void)whence;return 0; }
int _getpid(void) { return 1; }
int _kill(int pid,int sig) { (void)pid;(void)sig;return -1; }
clock_t _times(struct tms *t) { (void)t;return 0; }
void _fini(void) {} /* C-only freestanding test host: no process destructors */
__attribute__((noreturn)) void _exit(int code) {
    register long r0 __asm__("r0")=code,r7 __asm__("r7")=1;
    __asm__ volatile("svc #0"::"r"(r0),"r"(r7):"memory"); while(1) {}
}
static void metrics(unsigned cycle,int status) {
    const wd_metrics *m=wd_last_metrics();
    printf("MEM cycle=%u status=%d init=%zu compiled=%zu gc_live=%zu peak=%zu ledger_peak=%zu arena_peak=%zu used_peak=%zu live=%zu blocks=%zu allocs=%zu reallocs=%zu frees=%zu largest=%zu collections=%u foreign=%u completed=%u oom=%d fail_stage=%u init_peak=%zu compile_peak=%zu run_peak=%zu\n",
           cycle,status,m->init_live,m->compile_live,m->gc_live,m->peak,m->ledger_peak,m->arena_peak,m->used_peak,m->live,m->blocks,m->allocations,m->reallocations,m->frees,m->largest,m->collections,m->foreign_calls,m->completed,m->oom_kind,m->fail_stage,m->init_peak,m->compile_peak,m->run_peak);
}
__attribute__((used)) void arm_main(const long *entry_sp) {
    int argc=entry_sp[0]; char **argv=(char **)(entry_sp+1);
    size_t budget=argc>1?strtoul(argv[1],NULL,10):98304;
    limit=argc>2?strtoul(argv[2],NULL,10):135168;
    unsigned cycles=argc>3?(unsigned)strtoul(argv[3],NULL,10):20;
    const char *mode=argc>4?argv[4]:"normal";
    if (!limit || limit>sizeof arena || !cycles) _exit(2);
    uintptr_t sp; __asm__ volatile("mov %0, sp":"=r"(sp));
    uint32_t *lo=(uint32_t *)((uintptr_t)entry_sp-128*1024),*hi=(uint32_t *)((sp-256)&~3u);
    for (uint32_t *p=lo;p<hi;p++) *p=0xcafe1234;
    puts("INFO CPU emulation only; mock external FPGA, no hardware timing");
#ifdef WD_ARM_TESTS
    if (!strcmp(mode,"tests")) {
        extern int integration_test_main(void);
        int status=integration_test_main(); fflush(stdout); _exit(status);
    }
#endif
    if (!strcmp(mode,"malloc-recovery") || !strcmp(mode,"budget-recovery")) {
        mock_reset(); int status=wd_run(!strcmp(mode,"malloc-recovery")?262144:4096,1,false,false,!strcmp(mode,"malloc-recovery")?6:0,0);
        metrics(999,status);
        const wd_metrics *m=wd_last_metrics();
        if (status!=1 || m->live || m->blocks || wd_ui_owned() || m->allocations!=m->frees ||
            m->oom_kind!=(!strcmp(mode,"malloc-recovery")?2:1)) _exit(2);
    }
    int result=0;
    for (unsigned i=0;i<cycles;i++) {
        mock_reset(); int status=wd_run(budget,10,!strcmp(mode,"cover"),true,0,0);
        metrics(i,status); const wd_metrics *m=wd_last_metrics();
        if (status>result) result=status;
        if (m->live || m->blocks || wd_ui_owned() || m->allocations!=m->frees) _exit(2);
        if (!status && (m->completed!=10 || m->foreign_calls!=161 || m->collections<61 || m->utf8_outputs!=1)) _exit(2);
    }
    uint32_t *p=lo;while(p<hi && *p==0xcafe1234)p++;
    struct mallinfo mi=mallinfo();
    printf("ARENA capacity=%zu high_water=%zu current_break=%zu in_use=%u free=%u sbrk_failures=%zu stack_painted_upper=%lu\n",
           limit,high_water,used,mi.uordblks,mi.fordblks,failures,(unsigned long)((uintptr_t)entry_sp-(uintptr_t)p));
    fflush(stdout);_exit(result);
}
__attribute__((naked,noreturn)) void _start(void) { __asm__ volatile("mov r0, sp\nbl arm_main\n"); }
