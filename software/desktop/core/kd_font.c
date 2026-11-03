// SPDX-License-Identifier: Apache-2.0
#include "kd_font.h"

#include <string.h>

#if KD_UTF8
#include "kj_text.h"
#endif

// One glyph of s[0..n): its rows (MSB is the left pixel), width and length in
// bytes. Printable ASCII uses the font f; other bytes draw '?'. With KD_UTF8
// a non-ASCII UTF-8 sequence is one 8x8 Misaki glyph (kj_misaki8 in flash);
// invalid bytes are consumed one at a time and draw the replacement glyph.
static int glyph(const kd_font *f, const char *s, int n, const uint8_t **rows, int *width) {
    unsigned char c = (unsigned char)s[0];
#if KD_UTF8
    if (c >= 0x80) {
        kj_decoded d = kj_utf8_next((const uint8_t *)s, (size_t)n);
        kj_glyph g = kj_lookup(&kj_misaki8, d.scalar);
        *rows = g.rows;
        *width = 8;
        return d.consumed;
    }
#else
    (void)n;
#endif
    if (c < 0x20 || c > 0x7e) c = '?';
    *rows = f->rows + (c - 0x20) * 8;
    *width = f->width;
    return 1;
}

static int bounded_len(const char *s, int n) {
    int len = 0;
    while (len < n && s[len]) len++;
    return len;
}

// Width and length of the glyph at s, as glyph() gives them, without the
// font lookup (for glyphs that will not be drawn).
static int advance(const kd_font *f, const char *s, int n, int *width) {
#if KD_UTF8
    if ((unsigned char)s[0] >= 0x80) {
        *width = 8;
        return kj_utf8_next((const uint8_t *)s, (size_t)n).consumed;
    }
#else
    (void)s, (void)n;
#endif
    *width = f->width;
    return 1;
}

int kd_text_n(kd_fb *fb, const kd_font *f, int x, int y, const char *s, int n,
              uint8_t fg, int bg) {
    n = bounded_len(s, n);
    // A string outside the clip rows draws nothing: only its width is needed.
    bool rows_out = y + f->height <= fb->clip.y || y >= fb->clip.y + fb->clip.h;
    for (int i = 0; i < n;) {
        int w, len = advance(f, s + i, n - i, &w);
        // Glyphs wholly outside the clip skip the lookup and the raster
        // (long or scrolled lines are mostly outside).
        if (rows_out || x + w <= fb->clip.x || x >= fb->clip.x + fb->clip.w) {
            i += len;
        } else {
            const uint8_t *rows;
            i += glyph(f, s + i, n - i, &rows, &w);
            kd_fb_mono(fb, x, y, w, f->height, rows, fg, bg);
        }
        x += w;
    }
    return x;
}

int kd_text(kd_fb *fb, const kd_font *f, int x, int y, const char *s, uint8_t fg, int bg) {
    return kd_text_n(fb, f, x, y, s, (int)strlen(s), fg, bg);
}

int kd_text_width_n(const kd_font *f, const char *s, int n) {
    int x = 0;
    n = bounded_len(s, n);
    for (int i = 0; i < n;) {
        const uint8_t *rows;
        int w;
        i += glyph(f, s + i, n - i, &rows, &w);
        x += w;
    }
    return x;
}

int kd_text_width(const kd_font *f, const char *s) { return kd_text_width_n(f, s, (int)strlen(s)); }

int kd_text_fit(const kd_font *f, const char *s, int pixels, int *width) {
    int n = (int)strlen(s), x = 0, i = 0;
    while (i < n) {
        const uint8_t *rows;
        int w, len = glyph(f, s + i, n - i, &rows, &w);
        if (x + w > pixels) break;
        x += w;
        i += len;
    }
    *width = x;
    return i;
}
