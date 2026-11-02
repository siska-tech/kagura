/* SPDX-License-Identifier: Apache-2.0 */
#include "kj_desktop.h"
#include "kd_desktop.h"
#include <stdio.h>
#include <string.h>
static kd_desktop desktop;
static const kd_menu menus[]={{NULL,NULL}};
static void draw(kd_window *w,const kd_draw *d) {
    (void)w; kd_draw_fill(d,0,0,d->w,d->h,KD_C_WHITE);
    const char *text=u8"Native C 日本語\n神楽デスクトップ\nASCII + かな・漢字\n未収録: \xf0\x9f\x98\x80";
    (void)kj_desktop_text(d->fb,&kd_font_small,d->ox+6,d->oy+6,text,strlen(text),KD_C_BLACK,-1,NULL);
}
static const kd_window_class cls={draw,NULL,NULL};
static int save(const char *dir,const char *name) {
    char path[1024]; int n=snprintf(path,sizeof path,"%s/%s.ppm",dir,name);
    if (n<0 || (size_t)n>=sizeof path) return 1;
    FILE *f=fopen(path,"wb"); if (!f) return 1;
    fprintf(f,"P6\n320 200\n255\n");
    for (int y=0;y<KD_H;y++) for (int x=0;x<KD_W;x++) {
        unsigned c=kd_palette_rgb444[kd_fb_get(&desktop.fb,x,y)];
        uint8_t rgb[3]={(uint8_t)(((c>>8)&15)*17),(uint8_t)(((c>>4)&15)*17),(uint8_t)((c&15)*17)};
        if (fwrite(rgb,1,3,f)!=3) { fclose(f); return 1; }
    }
    return fclose(f)!=0;
}
int main(int argc,char **argv) {
    if (argc!=2) return 2;
    kd_shell_hooks hooks={0}; kd_desktop_init(&desktop,menus,NULL,0,hooks);
    kd_window *a=kd_window_open(&desktop,&cls,NULL,u8"神楽 Desktop",kd_rect_make(10,25,218,122),KD_WF_CLOSE|KD_WF_MOVE);
    if (!a || !kd_desktop_render(&desktop) || save(argv[1],"01-japanese-title")) return 1;
    kd_window *b=kd_window_open(&desktop,&cls,NULL,u8"日本語の窓",kd_rect_make(105,60,192,118),KD_WF_CLOSE|KD_WF_MOVE);
    if (!b || !kd_desktop_render(&desktop) || save(argv[1],"02-overlap")) return 1;
    kd_window_close(&desktop,b);
    if (!kd_desktop_render(&desktop) || save(argv[1],"03-revealed-title")) return 1;
    printf("JAPANESE_HOST_DEMO_PASS one Desktop / %zu-byte framebuffer; streaming RGB export only\n",sizeof desktop.fb.px);
    return 0;
}
