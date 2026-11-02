/* SPDX-License-Identifier: Apache-2.0 */
#include "kj_desktop.h"
#include "kd_desktop.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d %s\n",__LINE__,#x); exit(1); } } while (0)
static kd_desktop desktop; /* one owner, no reference framebuffer */
static const kd_menu menus[]={{NULL,NULL}};
static uint32_t crc(const void *data,size_t n) {
    const uint8_t *p=data; uint32_t c=~0u;
    for (size_t i=0;i<n;i++) { c^=p[i]; for (int j=0;j<8;j++) c=(c>>1)^(0xedb88320u&(0u-(c&1u))); }
    return ~c;
}
static void ascii(void) {
    kd_fb *fb=&desktop.fb; const kd_font *fonts[]={&kd_font_system,&kd_font_small};
    for (unsigned f=0;f<2;f++) for (int cp=32;cp<=126;cp++) for (int bg=-1;bg<=3;bg+=4) {
        char text[2]={(char)cp,0}; kd_fb_init(fb,0); kd_fb_set_clip(fb,kd_rect_make(2,3,19,12)); kd_fb_clear_dirty(fb);
        int x=cp%7-3,y=cp%9-2;
        int end=kd_text(fb,fonts[f],x,y,text,1,bg);
        uint32_t pixels=crc(fb->px,sizeof fb->px),dirty=crc(fb->dirty,sizeof fb->dirty);
        kd_fb_init(fb,0); kd_fb_set_clip(fb,kd_rect_make(2,3,19,12)); kd_fb_clear_dirty(fb);
        kj_metrics m; CHECK(kj_desktop_text(fb,fonts[f],x,y,text,1,1,bg,&m)==KJ_OK);
        CHECK(end==x+m.end_x && pixels==crc(fb->px,sizeof fb->px) && dirty==crc(fb->dirty,sizeof fb->dirty));
    }
}
static void dirty_tiles(void) {
    kd_fb *fb=&desktop.fb; const char *s=u8"神"; kj_glyph g=kj_lookup(&kj_misaki8,0x795e);
    for (int y=-8;y<17;y++) for (int x=-8;x<17;x++) {
        kd_fb_init(fb,0); kd_fb_clear_dirty(fb); uint8_t expected[(KD_TILES+7)/8]={0};
        CHECK(kj_desktop_text(fb,&kd_font_system,x,y,s,strlen(s),1,KD_NO_KEY,NULL)==KJ_OK);
        for (int gy=0;gy<8;gy++) for (int gx=0;gx<8;gx++) if ((g.rows[gy]&(0x80u>>gx)) && x+gx>=0 && y+gy>=0 && x+gx<KD_W && y+gy<KD_H) {
            unsigned tile=(unsigned)(y+gy)/8*KD_TILE_COLS+(unsigned)(x+gx)/8;
            expected[tile/8]|=(uint8_t)(1u<<(tile%8));
        }
        CHECK(!memcmp(expected,fb->dirty,sizeof expected));
        kd_fb_clear_dirty(fb);
        CHECK(kj_desktop_text(fb,&kd_font_system,x,y,s,strlen(s),1,-1,NULL)==KJ_OK && kd_fb_dirty_count(fb)==0);
    }
}
static void content(kd_window *w,const kd_draw *d) {
    (void)w; kd_draw_fill(d,0,0,d->w,d->h,KD_C_WHITE);
    const char *s=u8"ASCII 123\n日本語と神楽";
    CHECK(kj_desktop_text(d->fb,&kd_font_small,d->ox+3,d->oy+3,s,strlen(s),KD_C_BLACK,-1,NULL)==KJ_OK);
}
static const kd_window_class cls={content,NULL,NULL};
static void step(uint32_t *out) { CHECK(kd_desktop_render(&desktop)); *out=crc(desktop.fb.px,sizeof desktop.fb.px); kd_fb_clear_dirty(&desktop.fb); }
static void sequence(bool painter,uint32_t out[6]) {
    kd_shell_hooks hooks={0}; kd_desktop_init(&desktop,menus,NULL,0,hooks); desktop.painter=painter;
    kd_window *a=kd_window_open(&desktop,&cls,NULL,u8"神楽 Desktop",kd_rect_make(8,22,200,110),KD_WF_CLOSE|KD_WF_MOVE); CHECK(a);
    step(out);
    kd_window *b=kd_window_open(&desktop,&cls,NULL,u8"日本語の窓",kd_rect_make(52,29,150,100),KD_WF_CLOSE|KD_WF_MOVE); CHECK(b); step(out+1);
    kd_window_set_title(&desktop,a,u8"重なりの確認 ABC"); step(out+2);
    kd_desktop_move(&desktop,b,100,65); step(out+3);
    kd_window_close(&desktop,b); step(out+4);
    kd_window_set_title(&desktop,a,u8"日本語日本語日本語日本語"); step(out+5);
    CHECK(strlen(a->title)==21); /* capacity unchanged: seven whole 3-byte glyphs */
    kd_window_set_title(&desktop,a,a->title); CHECK(strlen(a->title)==21);
    (void)kd_desktop_render(&desktop); kd_fb_clear_dirty(&desktop.fb);
    kj_metrics m; CHECK(kj_measure(&kj_misaki8,(const uint8_t *)a->title,strlen(a->title),&m)==KJ_OK && !m.invalid);
    kd_window_invalidate_all(&desktop,a); CHECK(kd_desktop_render(&desktop) && !kd_fb_dirty_count(&desktop.fb));
}
int main(void) {
    ascii(); dirty_tiles(); uint32_t visible[6],painter[6]; sequence(false,visible); sequence(true,painter);
    for (unsigned i=0;i<6;i++) { CHECK(visible[i]==painter[i]); printf("GUI_CRC step=%u crc=%08x\n",i,visible[i]); }
    char title[8]; kj_desktop_copy_title(title,sizeof title,u8"神楽語"); CHECK(strlen(title)==6);
    int width; CHECK(kj_desktop_title_fit(u8"神楽ABC",23,&width)==6 && width==16);
    CHECK(kj_desktop_title_fit("AB\nC",100,&width)==2 && width==16);
    printf("DESKTOP_TEXT_PASS ASCII-equivalent dirty-exact overlap painter title-prefix sizeof_desktop=%zu framebuffer=%zu\n",sizeof desktop,sizeof desktop.fb.px);
    return 0;
}
