// SPDX-License-Identifier: Apache-2.0
#include "kd_font.h"

#include <string.h>

int kd_text_n(kd_fb *fb, const kd_font *f, int x, int y, const char *s, int n,
              uint8_t fg, int bg) {
    for (int i = 0; i < n && s[i]; i++, x += f->width) {
        // Skip glyphs wholly outside the clip before touching the raster.
        if (x + f->width <= fb->clip.x || x >= fb->clip.x + fb->clip.w ||
            y + f->height <= fb->clip.y || y >= fb->clip.y + fb->clip.h)
            continue;
        unsigned char c = (unsigned char)s[i];
        if (c < 0x20 || c > 0x7e) c = '?';
        kd_fb_mono(fb, x, y, f->width, f->height, f->rows + (c - 0x20) * 8, fg, bg);
    }
    return x;
}

int kd_text(kd_fb *fb, const kd_font *f, int x, int y, const char *s, uint8_t fg, int bg) {
    return kd_text_n(fb, f, x, y, s, (int)strlen(s), fg, bg);
}

int kd_text_width(const kd_font *f, const char *s) {
    return (int)strlen(s) * f->width;
}
