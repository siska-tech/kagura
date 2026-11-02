#include "diagnostics.h"
#include <string.h>
wd_span wd_spans[WD_SPANS];
void wd_diag_reset(void) { memset(wd_spans,0,sizeof wd_spans); }
void wd_diag_add(unsigned kind,uint64_t start) {
    uint64_t elapsed=wd_platform_us()-start;
    wd_span *s=&wd_spans[kind];
    uint32_t n=elapsed>UINT32_MAX?UINT32_MAX:(uint32_t)elapsed;
    if (!s->count || n<s->minimum) s->minimum=n;
    if (n>s->maximum) s->maximum=n;
    s->total+=elapsed; s->count++;
}
