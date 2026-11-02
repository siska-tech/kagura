#ifndef WD_DIAGNOSTICS_H
#define WD_DIAGNOSTICS_H
#include <stdint.h>
enum { WD_OPEN,WD_RECT,WD_EVENT,WD_PRESENT,WD_GC,WD_CALL,WD_INIT,WD_COMPILE,WD_SPANS };
typedef struct { uint64_t total; uint32_t minimum,maximum,count; } wd_span;
extern wd_span wd_spans[WD_SPANS];
uint64_t wd_platform_us(void);
void wd_diag_add(unsigned kind,uint64_t start);
void wd_diag_reset(void);
#endif
