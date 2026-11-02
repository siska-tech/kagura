#include "runtime.h"
#include "mock_hal.h"
#include <stdio.h>
#include <string.h>
void wd_platform_tick(void) {}
void wd_platform_check_allocation(void *p,size_t n) { (void)p;(void)n; }
uint64_t wd_platform_us(void) { return 0; }
static const char *directory;
static unsigned frame;
static bool failed;
static void save(void) {
    char path[1024]; int n=snprintf(path,sizeof path,"%s/frame-%u.pgm",directory,frame++);
    if (n<0 || (size_t)n>=sizeof path) { failed=true; return; }
    FILE *f=fopen(path,"wb"); if (!f) { failed=true; return; }
    fputs("P5\n320 240\n255\n",f);
    for (int y=0;y<240;y++) for (int x=0;x<KD_W;x++)
        if (fputc(y<KD_H?kd_fb_get(&wd_ui_desktop()->fb,x,y):0,f)==EOF) failed=true;
    if (fclose(f)) failed=true;
}
int main(int argc,char **argv) {
    if (argc!=3) return 2;
    directory=argv[2]; mock_reset(); wd_ui_observer(save);
    int status=0;
    /* The 64-bit PC ABI needs the same host cap as PR70's correctness suite.
       The measured 32-bit ARM/Pico payload cap remains 96 KiB. */
    bool cover=!strcmp(argv[1],"wren-cover");
    if (!strcmp(argv[1],"wren") || cover) status=wd_run(sizeof(void *)>4?262144:98304,1,cover,false,0,0);
    else if (!strcmp(argv[1],"native")) {
        wd_ui_prepare(false);
        if (!wd_ui_start() || !wd_ui_open_utf8(u8"神楽 Desktop",strlen(u8"神楽 Desktop"),NULL)) return 2;
        int x=4,c=12;
        if (!wd_ui_rect(x,8,48,24,c) || !wd_ui_present()) return 2;
        for (int i=1;i<=4;i++) {
            if (wd_ui_event()!=i) return 2;
            x+=i; c=(c+i)%16;
            if (!wd_ui_rect(x,8,48,24,c) || !wd_ui_present()) return 2;
        }
        wd_ui_abort(); if (!wd_ui_present()) return 2;
    } else return 2;
    printf("JAPANESE_HOST_DEMO mode=%s status=%d frames=%u one_desktop=1 framebuffer=32000\n",argv[1],status,frame);
    return status || failed || frame!=(cover?10u:7u);
}
