// SPDX-License-Identifier: Apache-2.0
// Layer A: 320x200 4bpp software framebuffer for the experimental C desktop.
//
// The working buffer is linear and packed: row y starts at y*160 and pixel x
// lives in byte x/2, even x in the high nibble. Each 8-pixel span of a row is
// therefore exactly one 4-byte row of a KAGURA TILE4 pattern, so export is a
// gather (kd_tile4.c), never a per-pixel conversion.
//
// Every drawing call clips against fb->clip (always inside the screen), writes
// a byte only when its value changes and then marks that 8x8 tile dirty. The
// dirty bitmap therefore lists exactly the tiles whose bytes differ from the
// last export. Colour 0 is an ordinary opaque colour here; transparency exists
// only as the explicit key argument of the blit calls.
//
// No allocation, no floating point, no globals: everything lives in kd_fb.
#ifndef KD_FB_H
#define KD_FB_H

#include <stdbool.h>
#include <stdint.h>

#define KD_W 320
#define KD_H 200
#define KD_STRIDE (KD_W / 2)
#define KD_TILE_COLS (KD_W / 8)
#define KD_TILE_ROWS (KD_H / 8)
#define KD_TILES (KD_TILE_COLS * KD_TILE_ROWS)
#define KD_FB_BYTES (KD_H * KD_STRIDE)
#define KD_NO_KEY (-1)

typedef struct {
    int16_t x, y, w, h;   // empty when w <= 0 or h <= 0
} kd_rect;

typedef struct {
    uint32_t pixels;      // pixels processed after clipping
    uint32_t changed;     // bytes whose value changed
    uint32_t calls;       // primitive calls that reached the raster
} kd_fb_stats;

typedef struct {
    uint8_t px[KD_FB_BYTES];
    uint8_t dirty[(KD_TILES + 7) / 8];
    kd_rect clip;
    kd_fb_stats stats;
} kd_fb;

static inline kd_rect kd_rect_make(int x, int y, int w, int h) {
    kd_rect r = {(int16_t)x, (int16_t)y, (int16_t)w, (int16_t)h};
    return r;
}
static inline bool kd_rect_empty(kd_rect r) { return r.w <= 0 || r.h <= 0; }
kd_rect kd_rect_intersect(kd_rect a, kd_rect b);
kd_rect kd_rect_union(kd_rect a, kd_rect b);     // bounding box; empty inputs ignored
bool kd_rect_overlaps(kd_rect a, kd_rect b);
bool kd_rect_contains(kd_rect outer, kd_rect inner);
bool kd_rect_has_point(kd_rect r, int x, int y);
static inline int32_t kd_rect_area(kd_rect r) {
    return kd_rect_empty(r) ? 0 : (int32_t)r.w * r.h;
}

// Fills the screen with colour, marks every tile dirty, resets clip and stats.
void kd_fb_init(kd_fb *fb, uint8_t color);
// Clip is intersected with the screen; an empty result disables drawing.
void kd_fb_set_clip(kd_fb *fb, kd_rect clip);
void kd_fb_reset_clip(kd_fb *fb);

// Colours are masked to 4 bits. Coordinates may be anywhere in int range.
void kd_fb_pixel(kd_fb *fb, int x, int y, uint8_t color);
int kd_fb_get(const kd_fb *fb, int x, int y);   // -1 off screen; ignores clip
void kd_fb_fill_rect(kd_fb *fb, int x, int y, int w, int h, uint8_t color);
void kd_fb_hline(kd_fb *fb, int x, int y, int w, uint8_t color);
void kd_fb_vline(kd_fb *fb, int x, int y, int h, uint8_t color);
void kd_fb_rect(kd_fb *fb, int x, int y, int w, int h, uint8_t color);
// Integer Bresenham including both endpoints; each pixel is clipped.
void kd_fb_line(kd_fb *fb, int x0, int y0, int x1, int y1, uint8_t color);
// 8x8 two-colour pattern: bit (7 - (x & 7)) of rows[y & 7] picks c1, else c0.
// The pattern is anchored to the screen so adjacent fills join seamlessly.
void kd_fb_pattern_rect(kd_fb *fb, int x, int y, int w, int h,
                        const uint8_t rows[8], uint8_t c0, uint8_t c1);
// 1bpp bitmap, rows of (w+7)/8 bytes, MSB is the left pixel. Set bits draw
// fg; clear bits draw bg unless bg is KD_NO_KEY (then they are skipped).
void kd_fb_mono(kd_fb *fb, int x, int y, int w, int h, const uint8_t *bits,
                uint8_t fg, int bg);
// 4bpp source in TILE4 order (8x8 tiles row-major, 32 B per tile, even x in
// the high nibble), w and h multiples of 8. Each source pixel becomes a
// zoom x zoom block. Pixels equal to key are skipped (KD_NO_KEY: opaque).
void kd_fb_blit_tile4(kd_fb *fb, int x, int y, const uint8_t *src, int w, int h,
                      int zoom, int key);

static inline bool kd_fb_tile_dirty(const kd_fb *fb, unsigned tile) {
    return (fb->dirty[tile >> 3] >> (tile & 7)) & 1;
}
static inline void kd_fb_set_tile_dirty(kd_fb *fb, unsigned tile, bool dirty) {
    if (dirty) fb->dirty[tile >> 3] |= (uint8_t)(1u << (tile & 7));
    else fb->dirty[tile >> 3] &= (uint8_t)~(1u << (tile & 7));
}
void kd_fb_mark_dirty_all(kd_fb *fb);
void kd_fb_clear_dirty(kd_fb *fb);
unsigned kd_fb_dirty_count(const kd_fb *fb);

#endif
