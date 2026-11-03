// SPDX-License-Identifier: Apache-2.0
#include "kd_fb.h"

#include <string.h>

#include "kd_fault.h"

static int imin(int a, int b) { return a < b ? a : b; }
static int imax(int a, int b) { return a > b ? a : b; }

kd_rect kd_rect_intersect(kd_rect a, kd_rect b) {
    int x0 = imax(a.x, b.x), y0 = imax(a.y, b.y);
    int x1 = imin(a.x + a.w, b.x + b.w), y1 = imin(a.y + a.h, b.y + b.h);
    if (kd_rect_empty(a) || kd_rect_empty(b) || x1 <= x0 || y1 <= y0)
        return kd_rect_make(0, 0, 0, 0);
    return kd_rect_make(x0, y0, x1 - x0, y1 - y0);
}

kd_rect kd_rect_union(kd_rect a, kd_rect b) {
    if (kd_rect_empty(a)) return b;
    if (kd_rect_empty(b)) return a;
    int x0 = imin(a.x, b.x), y0 = imin(a.y, b.y);
    int x1 = imax(a.x + a.w, b.x + b.w), y1 = imax(a.y + a.h, b.y + b.h);
    return kd_rect_make(x0, y0, x1 - x0, y1 - y0);
}

bool kd_rect_overlaps(kd_rect a, kd_rect b) { return !kd_rect_empty(kd_rect_intersect(a, b)); }

bool kd_rect_contains(kd_rect o, kd_rect i) {
    return !kd_rect_empty(i) && i.x >= o.x && i.y >= o.y &&
           i.x + i.w <= o.x + o.w && i.y + i.h <= o.y + o.h;
}

bool kd_rect_has_point(kd_rect r, int x, int y) {
    return x >= r.x && y >= r.y && x < r.x + r.w && y < r.y + r.h;
}

static inline void mark(kd_fb *fb, unsigned tile) {
    fb->dirty[tile >> 3] |= (uint8_t)(1u << (tile & 7));
}

// Writes one nibble of an on-screen pixel; the caller has clipped.
static inline void put(kd_fb *fb, int x, int y, uint8_t c) {
    uint8_t *p = &fb->px[y * KD_STRIDE + (x >> 1)];
    bool low = (x & 1) != 0;
    if (KD_FAULTY(KD_FAULT_NIBBLE_SWAP)) low = !low;
    uint8_t v = low ? (uint8_t)((*p & 0xF0) | c) : (uint8_t)((*p & 0x0F) | (c << 4));
    if (v != *p) {
        *p = v;
        mark(fb, (unsigned)(y >> 3) * KD_TILE_COLS + (unsigned)(x >> 3));
        fb->stats.changed++;
    }
}

// Pixels x0..x1 inclusive of row y, already clipped.
static void span(kd_fb *fb, int x0, int x1, int y, uint8_t c) {
    fb->stats.pixels += (uint32_t)(x1 - x0 + 1);
    if (x0 & 1) put(fb, x0++, y, c);
    if (x0 <= x1 && !(x1 & 1)) put(fb, x1--, y, c);
    if (x0 > x1) return;
    uint8_t *row = fb->px + y * KD_STRIDE;
    unsigned trow = (unsigned)(y >> 3) * KD_TILE_COLS;
    uint8_t v = (uint8_t)(c | (c << 4));
    for (int b = x0 >> 1, e = x1 >> 1; b <= e; b++) {
        if (row[b] != v) {
            row[b] = v;
            if (!KD_FAULTY(KD_FAULT_SPAN_DIRTY)) mark(fb, trow + (unsigned)(b >> 2));
            fb->stats.changed++;
        }
    }
}

static int clip_x1(const kd_fb *fb) {
    return fb->clip.x + fb->clip.w - 1 + (KD_FAULTY(KD_FAULT_CLIP_RIGHT) ? 1 : 0);
}

static inline bool in_clip(const kd_fb *fb, int x, int y) {
    return x >= fb->clip.x && x <= clip_x1(fb) && x < KD_W &&
           y >= fb->clip.y && y < fb->clip.y + fb->clip.h;
}

void kd_fb_init(kd_fb *fb, uint8_t color) {
    color &= 15;
    memset(fb->px, color | (color << 4), sizeof fb->px);
    kd_fb_mark_dirty_all(fb);
    kd_fb_reset_clip(fb);
    memset(&fb->stats, 0, sizeof fb->stats);
}

void kd_fb_set_clip(kd_fb *fb, kd_rect clip) {
    fb->clip = kd_rect_intersect(clip, kd_rect_make(0, 0, KD_W, KD_H));
}

void kd_fb_reset_clip(kd_fb *fb) { fb->clip = kd_rect_make(0, 0, KD_W, KD_H); }

void kd_fb_pixel(kd_fb *fb, int x, int y, uint8_t color) {
    if (!in_clip(fb, x, y)) return;
    fb->stats.calls++;
    fb->stats.pixels++;
    put(fb, x, y, color & 15);
}

int kd_fb_get(const kd_fb *fb, int x, int y) {
    if (x < 0 || y < 0 || x >= KD_W || y >= KD_H) return -1;
    uint8_t b = fb->px[y * KD_STRIDE + (x >> 1)];
    return (x & 1) ? (b & 15) : (b >> 4);
}

// Clips [x, x+w) x [y, y+h) to the clip rect using 64-bit ends.
static bool clip_box(const kd_fb *fb, int x, int y, int w, int h,
                     int *x0, int *y0, int *x1, int *y1) {
    if (w <= 0 || h <= 0 || kd_rect_empty(fb->clip)) return false;
    int64_t xe = (int64_t)x + w - 1, ye = (int64_t)y + h - 1;
    int cx1 = imin(clip_x1(fb), KD_W - 1), cy1 = fb->clip.y + fb->clip.h - 1;
    *x0 = imax(x, fb->clip.x);
    *y0 = imax(y, fb->clip.y);
    *x1 = (int)(xe < cx1 ? xe : cx1);
    *y1 = (int)(ye < cy1 ? ye : cy1);
    return *x0 <= *x1 && *y0 <= *y1;
}

void kd_fb_fill_rect(kd_fb *fb, int x, int y, int w, int h, uint8_t color) {
    int x0, y0, x1, y1;
    if (!clip_box(fb, x, y, w, h, &x0, &y0, &x1, &y1)) return;
    fb->stats.calls++;
    for (int yy = y0; yy <= y1; yy++) span(fb, x0, x1, yy, color & 15);
}

void kd_fb_hline(kd_fb *fb, int x, int y, int w, uint8_t color) {
    kd_fb_fill_rect(fb, x, y, w, 1, color);
}

void kd_fb_vline(kd_fb *fb, int x, int y, int h, uint8_t color) {
    kd_fb_fill_rect(fb, x, y, 1, h, color);
}

void kd_fb_rect(kd_fb *fb, int x, int y, int w, int h, uint8_t color) {
    if (w <= 0 || h <= 0) return;
    kd_fb_hline(fb, x, y, w, color);
    if (h > 1) kd_fb_hline(fb, x, y + h - 1, w, color);
    if (h > 2) {
        kd_fb_vline(fb, x, y + 1, h - 2, color);
        if (w > 1) kd_fb_vline(fb, x + w - 1, y + 1, h - 2, color);
    }
}

void kd_fb_line(kd_fb *fb, int x0, int y0, int x1, int y1, uint8_t color) {
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, sx = x0 < x1 ? 1 : -1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0, sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    color &= 15;
    fb->stats.calls++;
    for (;;) {
        if (in_clip(fb, x0, y0)) {
            fb->stats.pixels++;
            put(fb, x0, y0, color);
        }
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

void kd_fb_pattern_rect(kd_fb *fb, int x, int y, int w, int h,
                        const uint8_t rows[8], uint8_t c0, uint8_t c1) {
    int x0, y0, x1, y1;
    if (!clip_box(fb, x, y, w, h, &x0, &y0, &x1, &y1)) return;
    fb->stats.calls++;
    c0 &= 15;
    c1 &= 15;
    for (int yy = y0; yy <= y1; yy++) {
        uint8_t p = rows[yy & 7];
        if (p == 0x00 || p == 0xFF || c0 == c1) {
            span(fb, x0, x1, yy, p == 0xFF ? c1 : c0);
            continue;
        }
        fb->stats.pixels += (uint32_t)(x1 - x0 + 1);
        for (int xx = x0; xx <= x1; xx++)
            put(fb, xx, yy, ((p >> (7 - (xx & 7))) & 1) ? c1 : c0);
    }
}

// Four pixels of a 1bpp nibble (MSB left) as four 4-bit masks, left pixel
// in the high nibble.
static const uint16_t nib4[16] = {
    0x0000, 0x000F, 0x00F0, 0x00FF, 0x0F00, 0x0F0F, 0x0FF0, 0x0FFF,
    0xF000, 0xF00F, 0xF0F0, 0xF0FF, 0xFF00, 0xFF0F, 0xFFF0, 0xFFFF,
};

// Pixel mask of up to 8 pixels starting at x as framebuffer nibbles: byte j
// (from x's byte) is (m >> (32 - 8 * j)) & 0xFF.
static uint64_t nibble_mask(uint8_t pixels, bool odd) {
    uint32_t m = (uint32_t)nib4[pixels >> 4] << 16 | nib4[pixels & 15];
    return (uint64_t)m << (odd ? 4 : 8);
}

// Glyphs up to 8 pixels wide (every font of the desktop): each row updates
// the 4 or 5 bytes it touches at once instead of pixel by pixel. Same
// result, statistics and dirty tiles as the general loop.
static void mono8(kd_fb *fb, int x, int y, int w, const uint8_t *bits, uint8_t fg, int bg,
                  int x0, int y0, int x1, int y1) {
    int base = x >= 0 ? x / 2 : -((1 - x) / 2);       // floor(x / 2)
    bool odd = x - 2 * base != 0;
    uint8_t keep = (uint8_t)(0xFFu << (8 - w));       // the glyph's w columns
    uint8_t clip = (uint8_t)(keep & (0xFFu >> (x0 - x)) & (0xFFu << (7 - (x1 - x))));
    uint64_t cm = nibble_mask(clip, odd);
    uint8_t fgp = (uint8_t)(fg * 0x11), bgp = (uint8_t)((bg & 15) * 0x11);
    int b0 = x0 >> 1, b1 = x1 >> 1;
    for (int yy = y0; yy <= y1; yy++) {
        uint8_t ink = bits[yy - y] & clip;
        fb->stats.pixels += (uint32_t)__builtin_popcount(bg != KD_NO_KEY ? clip : ink);
        if (!ink && bg == KD_NO_KEY) continue;
        uint64_t im = nibble_mask(ink, odd);
        uint8_t *row = fb->px + yy * KD_STRIDE;
        unsigned trow = (unsigned)(yy >> 3) * KD_TILE_COLS;
        for (int b = b0; b <= b1; b++) {
            int sh = 32 - 8 * (b - base);
            uint8_t m = (uint8_t)(im >> sh), c = (uint8_t)(cm >> sh);
            uint8_t v = (uint8_t)((row[b] & ~m) | (fgp & m));
            if (bg != KD_NO_KEY) v = (uint8_t)((v & ~(c & ~m)) | (bgp & c & ~m));
            if (v != row[b]) {
                row[b] = v;
                mark(fb, trow + (unsigned)(b >> 2));
                fb->stats.changed++;
            }
        }
    }
}

void kd_fb_mono(kd_fb *fb, int x, int y, int w, int h, const uint8_t *bits,
                uint8_t fg, int bg) {
    int x0, y0, x1, y1;
    if (!clip_box(fb, x, y, w, h, &x0, &y0, &x1, &y1)) return;
    fb->stats.calls++;
    int pitch = (w + 7) / 8;
    fg &= 15;
    if (w <= 8 && !KD_FAULTY(KD_FAULT_NIBBLE_SWAP)) {
        mono8(fb, x, y, w, bits, fg, bg, x0, y0, x1, y1);
        return;
    }
    for (int yy = y0; yy <= y1; yy++) {
        const uint8_t *row = bits + (yy - y) * pitch;
        for (int xx = x0; xx <= x1; xx++) {
            int bx = xx - x;
            if ((row[bx >> 3] >> (7 - (bx & 7))) & 1) {
                fb->stats.pixels++;
                put(fb, xx, yy, fg);
            } else if (bg != KD_NO_KEY) {
                fb->stats.pixels++;
                put(fb, xx, yy, (uint8_t)(bg & 15));
            }
        }
    }
}

static inline int tile4_get(const uint8_t *src, int w, int sx, int sy) {
    uint8_t b = src[((sy >> 3) * (w >> 3) + (sx >> 3)) * 32 + (sy & 7) * 4 + ((sx & 7) >> 1)];
    return (sx & 1) ? (b & 15) : (b >> 4);
}

void kd_fb_blit_tile4(kd_fb *fb, int x, int y, const uint8_t *src, int w, int h,
                      int zoom, int key) {
    int x0, y0, x1, y1;
    if (zoom < 1 || (w & 7) || (h & 7)) return;
    if (!clip_box(fb, x, y, w * zoom, h * zoom, &x0, &y0, &x1, &y1)) return;
    fb->stats.calls++;
    for (int yy = y0; yy <= y1; yy++) {
        int sy = (yy - y) / zoom;
        int run_start = x0, run_color = -1;
        for (int xx = x0; xx <= x1 + 1; xx++) {
            int c = xx <= x1 ? tile4_get(src, w, (xx - x) / zoom, sy) : -2;
            if (c == run_color) continue;
            if (run_color >= 0 && run_color != key) span(fb, run_start, xx - 1, yy, (uint8_t)run_color);
            run_start = xx;
            run_color = c;
        }
    }
}

void kd_fb_mark_dirty_all(kd_fb *fb) {
    memset(fb->dirty, 0xFF, sizeof fb->dirty);
    fb->dirty[sizeof fb->dirty - 1] = (uint8_t)((1u << (KD_TILES - 8 * (sizeof fb->dirty - 1))) - 1);
}

void kd_fb_clear_dirty(kd_fb *fb) { memset(fb->dirty, 0, sizeof fb->dirty); }

unsigned kd_fb_dirty_count(const kd_fb *fb) {
    unsigned n = 0;
    for (unsigned i = 0; i < sizeof fb->dirty; i++)
        for (uint8_t b = fb->dirty[i]; b; b &= (uint8_t)(b - 1)) n++;
    return n;
}
