// SPDX-License-Identifier: Apache-2.0
// Raster half of the C TileFramebuffer; no device I/O (see tile_fb.h).
#include "tile_fb.h"

#include <string.h>

void tfb_reset(tile_fb *fb, uint8_t palette) {
    memset(fb->buffer.bytes, 0, sizeof fb->buffer.bytes);
    memset(fb->dirty, 1, sizeof fb->dirty);
    memset(&fb->last_flush, 0, sizeof fb->last_flush);
    fb->palette = palette & 15u;
    fb->initialized = false;
}

static inline void put(tile_fb *fb, int x, int y, unsigned color) {
    if ((unsigned)x >= TFB_WIDTH || (unsigned)y >= TFB_HEIGHT) return;
    unsigned tile = (unsigned)(y >> 3) * TFB_COLUMNS + (unsigned)(x >> 3);
    uint8_t *p = &fb->buffer.bytes[tile * 32u + (unsigned)(y & 7) * 4u + (unsigned)((x & 7) >> 1)];
    uint8_t old = *p;
    uint8_t value = (x & 1) ? (uint8_t)((old & 0xf0u) | color) : (uint8_t)((old & 0x0fu) | color << 4);
    if (value != old) {
        *p = value;
        fb->dirty[tile] = 1;
    }
}

// Clips to [0,320)x[0,240); false when nothing is left. 64-bit ends so that
// huge widths cannot wrap.
static bool clip(int *x, int *y, int width, int height, int *right, int *bottom) {
    if (width <= 0 || height <= 0) return false;
    int64_t r = (int64_t)*x + width, b = (int64_t)*y + height;
    *right = r > TFB_WIDTH ? TFB_WIDTH : (int)r;
    *bottom = b > TFB_HEIGHT ? TFB_HEIGHT : (int)b;
    if (*x < 0) *x = 0;
    if (*y < 0) *y = 0;
    return *x < *right && *y < *bottom;
}

void tfb_pixel(tile_fb *fb, int x, int y, uint8_t color) {
    if (color <= 15u) put(fb, x, y, color);
}

int tfb_get_pixel(const tile_fb *fb, int x, int y) {
    if ((unsigned)x >= TFB_WIDTH || (unsigned)y >= TFB_HEIGHT) return -1;
    unsigned tile = (unsigned)(y >> 3) * TFB_COLUMNS + (unsigned)(x >> 3);
    uint8_t b = fb->buffer.bytes[tile * 32u + (unsigned)(y & 7) * 4u + (unsigned)((x & 7) >> 1)];
    return (x & 1) ? b & 15 : b >> 4;
}

void tfb_fill_rect(tile_fb *fb, int x, int y, int width, int height, uint8_t color) {
    int right, bottom;
    if (color > 15u || !clip(&x, &y, width, height, &right, &bottom)) return;
    const uint8_t fill_byte = (uint8_t)(color * 17u);
    const uint32_t fill_word = fill_byte * 0x01010101u;
    for (int ty = y >> 3; ty <= (bottom - 1) >> 3; ty++) {
        int r0 = y > ty * 8 ? y - ty * 8 : 0;
        int r1 = bottom - ty * 8 < 8 ? bottom - ty * 8 : 8;
        for (int tx = x >> 3; tx <= (right - 1) >> 3; tx++) {
            int c0 = x > tx * 8 ? x - tx * 8 : 0;
            int c1 = right - tx * 8 < 8 ? right - tx * 8 : 8;
            unsigned tile = (unsigned)ty * TFB_COLUMNS + (unsigned)tx;
            bool changed = false;
            if (c0 == 0 && c1 == 8) {
                // Whole tile rows: one aligned word per row.
                uint32_t *w = &fb->buffer.words[tile * 8u];
                for (int r = r0; r < r1; r++)
                    if (w[r] != fill_word) { w[r] = fill_word; changed = true; }
            } else {
                // Edge tile: whole bytes where both nibbles are covered,
                // otherwise keep the neighbouring nibble.
                uint8_t *row = &fb->buffer.bytes[tile * 32u + (unsigned)r0 * 4u];
                for (int r = r0; r < r1; r++, row += 4) {
                    for (int cx = c0; cx < c1;) {
                        uint8_t *p = &row[cx >> 1], old = *p, value;
                        if (!(cx & 1) && cx + 1 < c1) { value = fill_byte; cx += 2; }
                        else if (cx & 1) { value = (uint8_t)((old & 0xf0u) | color); cx++; }
                        else { value = (uint8_t)((old & 0x0fu) | color << 4); cx++; }
                        if (value != old) { *p = value; changed = true; }
                    }
                }
            }
            if (changed) fb->dirty[tile] = 1;
        }
    }
}

void tfb_fill(tile_fb *fb, uint8_t color) { tfb_fill_rect(fb, 0, 0, TFB_WIDTH, TFB_HEIGHT, color); }
void tfb_hline(tile_fb *fb, int x, int y, int width, uint8_t color) { tfb_fill_rect(fb, x, y, width, 1, color); }
void tfb_vline(tile_fb *fb, int x, int y, int height, uint8_t color) { tfb_fill_rect(fb, x, y, 1, height, color); }

void tfb_rect(tile_fb *fb, int x, int y, int width, int height, uint8_t color) {
    if (width <= 0 || height <= 0) return;
    tfb_hline(fb, x, y, width, color);
    tfb_hline(fb, x, (int)((int64_t)y + height - 1), width, color);
    tfb_vline(fb, x, y, height, color);
    tfb_vline(fb, (int)((int64_t)x + width - 1), y, height, color);
}

void tfb_line(tile_fb *fb, int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint8_t color) {
    if (color > 15u) return;
    if ((x0 > x1 ? x0 : x1) < 0 || (x0 < x1 ? x0 : x1) >= TFB_WIDTH ||
        (y0 > y1 ? y0 : y1) < 0 || (y0 < y1 ? y0 : y1) >= TFB_HEIGHT) return;
    int x = x0, y = y0;
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, dy = -(y1 > y0 ? y1 - y0 : y0 - y1);
    int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    int error = dx + dy;
    for (;;) {
        put(fb, x, y, color);
        if (x == x1 && y == y1) break;
        int twice = error * 2;
        if (twice >= dy) { error += dy; x += sx; }
        if (twice <= dx) { error += dx; y += sy; }
    }
}

void tfb_circle(tile_fb *fb, int16_t x, int16_t y, uint16_t radius, uint8_t color) {
    int r = radius;
    if (color > 15u || x + r < 0 || x - r >= TFB_WIDTH || y + r < 0 || y - r >= TFB_HEIGHT) return;
    int a = r, b = 0, decision = 1 - r;
    while (b <= a) {
        put(fb, x + a, y + b, color); put(fb, x + b, y + a, color);
        put(fb, x - b, y + a, color); put(fb, x - a, y + b, color);
        put(fb, x - a, y - b, color); put(fb, x - b, y - a, color);
        put(fb, x + b, y - a, color); put(fb, x + a, y - b, color);
        b++;
        if (decision < 0) decision += b * 2 + 1;
        else { a--; decision += (b - a) * 2 + 1; }
    }
}

void tfb_mark_dirty(tile_fb *fb, int x, int y, int width, int height) {
    int right, bottom;
    if (!clip(&x, &y, width, height, &right, &bottom)) return;
    for (int row = y >> 3; row <= (bottom - 1) >> 3; row++)
        memset(&fb->dirty[row * TFB_COLUMNS + (x >> 3)], 1, (size_t)(((right - 1) >> 3) - (x >> 3) + 1));
}
