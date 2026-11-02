// SPDX-License-Identifier: Apache-2.0
// kd_draw helpers: translate work-area coordinates and forward to Layers A/B.
// The compositor has already set fb->clip inside the work area.
#include "kd_app.h"

#include <string.h>

bool kd_draw_visible(const kd_draw *d, kd_rect r) {
    r.x = (int16_t)(r.x + d->ox);
    r.y = (int16_t)(r.y + d->oy);
    return kd_rect_overlaps(r, d->fb->clip);
}

void kd_draw_fill(const kd_draw *d, int x, int y, int w, int h, uint8_t color) {
    kd_fb_fill_rect(d->fb, d->ox + x, d->oy + y, w, h, color);
}

void kd_draw_rect(const kd_draw *d, int x, int y, int w, int h, uint8_t color) {
    kd_fb_rect(d->fb, d->ox + x, d->oy + y, w, h, color);
}

void kd_draw_hline(const kd_draw *d, int x, int y, int w, uint8_t color) {
    kd_fb_hline(d->fb, d->ox + x, d->oy + y, w, color);
}

void kd_draw_vline(const kd_draw *d, int x, int y, int h, uint8_t color) {
    kd_fb_vline(d->fb, d->ox + x, d->oy + y, h, color);
}

int kd_draw_text(const kd_draw *d, const kd_font *f, int x, int y, const char *s,
                 uint8_t fg, int bg) {
    return kd_text(d->fb, f, d->ox + x, d->oy + y, s, fg, bg) - d->ox;
}

void kd_draw_art(const kd_draw *d, int x, int y, const kd_art *a, uint8_t ink, uint8_t paper) {
    kd_gfx_art(d->fb, d->ox + x, d->oy + y, a, ink, paper);
}

void kd_draw_icon(const kd_draw *d, int x, int y, const kd_art *a, const char *label, bool selected) {
    if (kd_draw_visible(d, kd_icon_box(x, y, label)))
        kd_gfx_icon(d->fb, d->ox + x, d->oy + y, a, label, selected);
}

void kd_draw_button(const kd_draw *d, kd_rect r, const char *label, unsigned flags) {
    if (!kd_draw_visible(d, r)) return;
    r.x = (int16_t)(r.x + d->ox);
    r.y = (int16_t)(r.y + d->oy);
    kd_gfx_button(d->fb, r, label, flags);
}

void kd_draw_pattern(const kd_draw *d, int x, int y, int w, int h, const uint8_t rows[8],
                     uint8_t c0, uint8_t c1) {
    kd_fb_pattern_rect(d->fb, d->ox + x, d->oy + y, w, h, rows, c0, c1);
}

void kd_draw_sprite(const kd_draw *d, int x, int y, const kd_sprite *s, int zoom, int key) {
    kd_fb_blit_tile4(d->fb, d->ox + x, d->oy + y, s->data, KD_SPRITE_W, KD_SPRITE_H, zoom, key);
}

static char label_char(const kd_label *l, int i) {
    for (int k = 0; k <= i; k++)
        if (!l->text[k]) return ' ';
    return l->text[i];
}

void kd_label_init(kd_label *l, int x, int y, int width, const char *text) {
    l->x = (int16_t)x;
    l->y = (int16_t)y;
    l->width = (uint8_t)(width > KD_LABEL_MAX ? KD_LABEL_MAX : width);
    memset(l->text, 0, sizeof l->text);
    strncpy(l->text, text, l->width);
}

void kd_label_set(kd_desktop *d, kd_window *w, kd_label *l, const char *text) {
    kd_label next = *l;
    memset(next.text, 0, sizeof next.text);
    strncpy(next.text, text, next.width);
    // Invalidate each run of changed glyph cells as one rect.
    for (int i = 0; i < l->width;) {
        if (label_char(l, i) == label_char(&next, i)) { i++; continue; }
        int j = i;
        while (j < l->width && label_char(l, j) != label_char(&next, j)) j++;
        kd_window_invalidate(d, w, kd_rect_make(l->x + i * 8, l->y, (j - i) * 8, 8));
        i = j;
    }
    *l = next;
}

void kd_draw_label(const kd_draw *d, const kd_label *l, uint8_t fg, uint8_t bg) {
    char buf[KD_LABEL_MAX + 1];
    for (int i = 0; i < l->width; i++) buf[i] = label_char(l, i);
    buf[l->width] = 0;
    kd_draw_text(d, &kd_font_system, l->x, l->y, buf, fg, bg);
}
