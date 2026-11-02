#ifndef WD_UI_H
#define WD_UI_H
#include "kd_desktop.h"
#include "transport.h"
void wd_ui_prepare(bool cover);
bool wd_ui_start(void);
bool wd_ui_open(const char *title);
#ifdef WD_JAPANESE
#include "wj_title.h"
bool wd_ui_open_utf8(const char *title,size_t bytes,wj_title_status *status);
const char *wd_ui_title(void);
bool wd_ui_move(int x,int y);
#endif
bool wd_ui_rect(int x,int y,int w,int h,int color);
int wd_ui_event(void);
bool wd_ui_present(void);
void wd_ui_abort(void);
bool wd_ui_owned(void);
kd_desktop *wd_ui_desktop(void);
wd_transport *wd_ui_transport(void);
void wd_ui_cover(bool show);
typedef void (*wd_frame_observer)(void);
void wd_ui_observer(wd_frame_observer observer);
unsigned wd_ui_events(void);
#endif
