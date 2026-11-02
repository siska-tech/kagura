/* Host-only indexed reference output, reusing the one native desktop. */
#include "ui.h"
#include "mock_hal.h"
#include <stdio.h>
#include <stdlib.h>
static unsigned frame;
void wd_platform_tick(void) {}
void wd_platform_check_allocation(void *ptr,size_t size) { (void)ptr; (void)size; }
uint64_t wd_platform_us(void) { return 0; }
static void save(void) {
    char name[32]; snprintf(name,sizeof name,"frame-%u.pgm",frame++);
    FILE *f=fopen(name,"wb"); if (!f) exit(2);
    fputs("P5\n320 240\n255\n",f);
    for (int y=0;y<240;y++) for (int x=0;x<320;x++) {
        /* Pattern 1000 is all index zero in the unused bottom forty rows. */
        int index=y<KD_H?kd_fb_get(&wd_ui_desktop()->fb,x,y):0;
        if (fputc(index,f)==EOF) exit(2);
    }
    if (fclose(f)) exit(2);
}
int main(void) {
    mock_reset(); wd_ui_prepare(false); wd_ui_observer(save);
    if (!wd_ui_start() || !wd_ui_open("Wren Window")) return 2;
    int x=4,c=12;
    if (!wd_ui_rect(x,8,48,24,c) || !wd_ui_present()) return 2;
    for (int i=1;i<=4;i++) {
        if (wd_ui_event()!=i) return 2;
        x+=i; c=(c+i)%16;
        if (!wd_ui_rect(x,8,48,24,c) || !wd_ui_present()) return 2;
    }
    wd_ui_abort(); if (!wd_ui_present()) return 2;
    return frame==7?0:2;
}
