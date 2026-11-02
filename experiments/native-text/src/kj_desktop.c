/* SPDX-License-Identifier: Apache-2.0 */
#include "kj_desktop.h"
#include <string.h>
kj_font kj_desktop_font(const kd_font *ascii) {
    kj_font font=kj_misaki8;
    if (ascii) (void)kj_font_ascii(&font,ascii->rows,95u*8u,ascii->width);
    return font;
}
static void plot(void *context,int32_t x,int32_t y,uint8_t color) {
    kd_fb_pixel(context,x,y,color); /* existing exact dirty marking and clip */
}
kj_status kj_desktop_text(kd_fb *fb,const kd_font *ascii,int x,int y,
                          const char *text,size_t bytes,uint8_t fg,int bg,kj_metrics *out) {
    if (!fb || !ascii || ascii->height!=8 || (ascii->width!=4 && ascii->width!=8)) return KJ_ARGUMENT;
    kj_font font=kj_desktop_font(ascii);
    kj_target target={fb,plot,{fb->clip.x,fb->clip.y,fb->clip.w,fb->clip.h}};
    return kj_draw(&font,(const uint8_t *)text,bytes,x,y,fg,bg,&target,out);
}
void kj_desktop_copy_title(char *out,size_t capacity,const char *text) {
    if (!out || !capacity) return;
    if (!text) text="";
    size_t bytes=kj_utf8_prefix((const uint8_t *)text,strlen(text),capacity-1);
    memmove(out,text,bytes); memset(out+bytes,0,capacity-bytes);
}
size_t kj_desktop_title_fit(const char *text,int pixels,int *width) {
    size_t n=strlen(text),pos=0; int w=0;
    if (pixels<0) pixels=0;
    /* System titles use 8px legacy ASCII and 8px Japanese. LF/CR cannot
       introduce a second title row: stop before either control character. */
    while (pos<n && pixels-w>=8) {
        kj_decoded d=kj_utf8_next((const uint8_t *)text+pos,n-pos);
        if (d.scalar=='\n' || d.scalar=='\r') break;
        pos+=d.consumed; w+=8;
    }
    *width=w; return pos;
}
