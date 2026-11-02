/* Link analysis only. No vector table, boot2, SDK, hardware IO or load target. */
#include "kj_text.h"
#ifdef KJ_DESKTOP_PROBE
#include "kd_desktop.h"
static kd_desktop desktop;
static const kd_menu menus[]={{0,0}};
static void draw(kd_window *w,const kd_draw *d) { (void)w; kd_draw_fill(d,0,0,d->w,d->h,KD_C_WHITE); }
static const kd_window_class cls={draw,0,0};
#endif
const uint32_t kj_type_sizes[]={sizeof(kj_font),sizeof(kj_glyph),sizeof(kj_metrics),sizeof(kj_target),sizeof(kj_surface4),sizeof(kj_decoded),
#ifdef KJ_DESKTOP_PROBE
sizeof(kd_desktop)
#else
0
#endif
};
static volatile unsigned result;
void _start(void) {
#ifdef KJ_DESKTOP_PROBE
    kd_shell_hooks hooks={0}; kd_desktop_init(&desktop,menus,0,0,hooks);
    (void)kd_window_open(&desktop,&cls,0,u8"神楽 Desktop",kd_rect_make(16,24,160,104),KD_WF_CLOSE);
    result=(unsigned)kd_desktop_render(&desktop);
#else
    static uint8_t pixels[32]; kj_font font; kj_metrics m;
    const uint8_t *s=(const uint8_t *)u8"A神楽\nB";
    kj_surface4 surface={pixels,sizeof pixels,4,8,8,{0,0,8,8},0,0};
    result=kj_font_open(&font,kj_misaki8.data,kj_misaki8.bytes);
    result+=(unsigned)kj_utf8_prefix(s,9,8);
    result+=(unsigned)kj_draw4(&font,s,9,0,0,1,-1,&surface,&m);
#endif
    while (1) {}
}
