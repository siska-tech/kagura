#include "ui.h"
#include <string.h>
typedef struct {
    kd_desktop desktop; /* exactly one instance; owns the only 32,000 B framebuffer */
    wd_transport transport;
    kd_window *window,*cover;
    kd_rect rectangle;
    kd_event events[4];
    unsigned next_event,delivered;
    uint8_t color;
    bool has_rectangle,want_cover,busy;
    wd_frame_observer observer;
} DesktopState;
static DesktopState desktop_state;
_Static_assert(sizeof(desktop_state.desktop.fb.px)==32000,"one full desktop framebuffer retained");
_Static_assert(sizeof(desktop_state.desktop.snap)==1280,"shared scratch capacity must cover a full tile row");
static const kd_menu empty_menus[]={{NULL,NULL}};
static void draw(kd_window *w,const kd_draw *d) {
    (void)w;
    kd_draw_fill(d,0,0,d->w,d->h,KD_C_WHITE);
    if (desktop_state.has_rectangle) {
        kd_rect r=desktop_state.rectangle;
        kd_draw_rect(d,r.x,r.y,r.w,r.h,desktop_state.color);
    }
}
static void draw_cover(kd_window *w,const kd_draw *d) {
    (void)w; kd_draw_fill(d,0,0,d->w,d->h,KD_C_DGREY);
}
static const kd_window_class window_class={draw,NULL,NULL}, cover_class={draw_cover,NULL,NULL};
kd_desktop *wd_ui_desktop(void) { return &desktop_state.desktop; }
wd_transport *wd_ui_transport(void) { return &desktop_state.transport; }
void wd_ui_observer(wd_frame_observer observer) { desktop_state.observer=observer; }
void wd_ui_prepare(bool cover) {
    wd_frame_observer observer=desktop_state.observer;
    memset(&desktop_state,0,sizeof desktop_state); desktop_state.observer=observer;
    kd_shell_hooks hooks={0};
    kd_desktop_init(&desktop_state.desktop,empty_menus,NULL,0,hooks);
    desktop_state.want_cover=cover;
    for (unsigned i=0;i<4;i++) {
        desktop_state.events[i].type=KD_EV_KEY; desktop_state.events[i].key=KD_KEY_CHAR;
        desktop_state.events[i].ch=(char)('1'+i); desktop_state.events[i].time_ms=i+1;
    }
}
bool wd_ui_start(void) {
    if (desktop_state.busy) return false;
    desktop_state.busy=true;
    bool ok=wd_transport_init(&desktop_state.transport,desktop_state.desktop.snap);
    desktop_state.busy=false;
    if (!ok || !wd_ui_present()) return false;
    kh_status s=kh_write_reg(KAGURA_REG_DISPLAY_CTRL,KAGURA_DISPLAY_CTRL_DISPLAY_ENABLE|KAGURA_DISPLAY_CTRL_BG_ENABLE);
    if (s==KH_OK) s=kh_commit(500000);
    if (s==KH_OK) s=kh_check_errors();
    if (s!=KH_OK) { desktop_state.transport.ready=false; desktop_state.transport.faulted=true; desktop_state.transport.error=s; }
    return s==KH_OK;
}
void wd_ui_cover(bool show) {
    if (desktop_state.busy) return;
    if (show && !desktop_state.cover)
        desktop_state.cover=kd_window_open(&desktop_state.desktop,&cover_class,NULL,"Native cover",kd_rect_make(48,40,96,80),KD_WF_CLOSE|KD_WF_MOVE);
    if (!show && desktop_state.cover) {
        kd_window_close(&desktop_state.desktop,desktop_state.cover); desktop_state.cover=NULL;
    }
}
bool wd_ui_open(const char *title) {
    if (desktop_state.busy || desktop_state.window || strlen(title)>=KD_TITLE_MAX) return false;
    for (const unsigned char *p=(const unsigned char *)title;*p;p++) if (*p<32 || *p>126) return false;
    desktop_state.window=kd_window_open(&desktop_state.desktop,&window_class,NULL,title,kd_rect_make(16,24,160,104),KD_WF_CLOSE|KD_WF_MOVE);
    if (desktop_state.want_cover) wd_ui_cover(true);
    return desktop_state.window!=NULL;
}
bool wd_ui_rect(int x,int y,int w,int h,int color) {
    if (desktop_state.busy || !desktop_state.window || x < -32768 || x>32767 || y < -32768 || y>32767 || w<0 || w>32767 || h<0 || h>32767 || color<0 || color>15) return false;
    desktop_state.rectangle=kd_rect_make(x,y,w,h); desktop_state.color=(uint8_t)color; desktop_state.has_rectangle=true;
    kd_window_invalidate_all(&desktop_state.desktop,desktop_state.window); return true;
}
int wd_ui_event(void) {
    if (desktop_state.busy || desktop_state.next_event==4) return 0;
    kd_event *e=&desktop_state.events[desktop_state.next_event++];
    kd_desktop_event(&desktop_state.desktop,e); desktop_state.delivered++;
    return e->ch-'0';
}
unsigned wd_ui_events(void) { return desktop_state.delivered; }
bool wd_ui_present(void) {
    if (desktop_state.busy) return false;
    desktop_state.busy=true;
    kd_desktop_render(&desktop_state.desktop);
    /* snap is dead after render returns. Sink is blocking; busy rejects
       re-entry until write+FENCE+error checks have completed. No DMA/core 1. */
    bool ok=kd_tile4_flush(&desktop_state.desktop.fb,0,desktop_state.desktop.snap,KD_TILE_COLS,
                          wd_transport_sink,&desktop_state.transport,NULL);
    if (ok && desktop_state.observer) desktop_state.observer();
    desktop_state.busy=false; return ok;
}
bool wd_ui_owned(void) { return desktop_state.window!=NULL; }
void wd_ui_abort(void) {
    /* No C pointer into Wren: all text/pixels/model state is native-owned.
       Closing invalidates exposed regions; a later acknowledged present repairs
       display contents. Never perform transport IO from the OOM boundary. */
    if (desktop_state.window) kd_window_close(&desktop_state.desktop,desktop_state.window);
    desktop_state.window=NULL; desktop_state.has_rectangle=false;
    desktop_state.next_event=4;
}
