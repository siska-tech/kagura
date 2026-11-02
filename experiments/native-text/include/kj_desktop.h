/* SPDX-License-Identifier: Apache-2.0 */
#ifndef KJ_DESKTOP_H
#define KJ_DESKTOP_H
#include "kj_text.h"
#include "kd_font.h"
kj_font kj_desktop_font(const kd_font *ascii);
kj_status kj_desktop_text(kd_fb *fb,const kd_font *ascii,int x,int y,
                          const char *text,size_t bytes,uint8_t fg,int bg,kj_metrics *out);
void kj_desktop_copy_title(char *out,size_t capacity,const char *text);
size_t kj_desktop_title_fit(const char *text,int pixels,int *width);
#endif
