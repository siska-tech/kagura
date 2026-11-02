#ifndef WD_RUNTIME_H
#define WD_RUNTIME_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
typedef struct {
    size_t live,peak,ledger_peak,allocations,reallocations,frees,blocks,largest;
    size_t init_live,compile_live,gc_live,init_peak,compile_peak,run_peak;
    size_t arena_peak,used_peak;
    unsigned collections,foreign_calls,errors,completed,utf8_outputs;
    unsigned stage,fail_stage;
    int oom_kind,status;
#ifdef WD_JAPANESE
    unsigned handle_rejections;
#endif
} wd_metrics;
/* Failure injection: 0 none, 1 init, 2 compile, 3 after native ownership,
   4 explicit GC allocation, 5 fail Nth allocator call, 6 native-arena probe
   (tests). Never changes OOM cleanup. */
int wd_run(size_t budget,unsigned rounds,bool cover,bool errors,unsigned injection,size_t nth);
#ifdef WD_JAPANESE
int wd_run_script(size_t budget,unsigned rounds,bool cover,bool errors,unsigned injection,size_t nth,const char *source);
bool wd_handles_idle(void);
#endif
const wd_metrics *wd_last_metrics(void);
void wd_platform_tick(void);
/* Successful native allocations must stay inside the platform arena.
   This is independent of returning NULL for an expected malloc failure. */
void wd_platform_check_allocation(void *ptr,size_t size);
#endif
