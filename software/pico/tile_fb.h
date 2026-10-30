// SPDX-License-Identifier: Apache-2.0
// C port of the MicroPython TileFramebuffer (docs/framebuffer.md): a 320x240
// 4bpp plane stored tile-native, one pattern per 40x30 cell (ABI 0.6, 1200
// patterns). Pixel (x,y) lives in tile (y/8)*40+x/8 at byte (y%8)*4+(x%8)/2,
// even X in the high nibble. Drawing only changes RAM and marks a tile dirty
// when its bytes change; tfb_flush() sends dirty runs and confirms each with
// a FENCE. Single owner only: no drawing from interrupts or the other core.
//
// The raster half (tile_fb.c) has no hardware dependency so the PC test can
// compare it with the Python implementation. tile_fb_io.c holds the device
// side and uses kagura_host.h only.
#ifndef TILE_FB_H
#define TILE_FB_H

#include <stdbool.h>
#include <stdint.h>
#include "kagura_host.h"

#define TFB_WIDTH 320
#define TFB_HEIGHT 240
#define TFB_COLUMNS 40
#define TFB_ROWS 30
#define TFB_TILES 1200
#define TFB_BYTES (TFB_TILES * 32)
#define TFB_MAX_GAP 1198

typedef struct {
    uint32_t tiles;           // confirmed by FENCE, gaps included
    uint32_t bytes, runs, writes, fences;  // requested, not proof of delivery
    uint64_t transfer_us;     // kh_vram_write calls, including their error checks
    uint64_t wait_us;         // DONE_TAG read, FENCE, completion and error checks
    uint64_t total_us;        // whole flush including the dirty scan
} tfb_flush_stats;

typedef struct {
    union {                   // words[] gives aligned 8-word tile access
        uint8_t bytes[TFB_BYTES];
        uint32_t words[TFB_BYTES / 4];
    } buffer;
    uint8_t dirty[TFB_TILES]; // 0 clean, 1 dirty; edit via the API or tfb_mark_dirty
    uint8_t palette;          // map palette for every cell, backdrop = palette*16
    bool initialized;
    tfb_flush_stats last_flush;
} tile_fb;

// Clears the plane to colour 0 and marks every tile dirty. No device I/O.
void tfb_reset(tile_fb *fb, uint8_t palette);

// Colours above 15 make the call a no-op. Off-screen pixels are ignored and
// zero or negative widths/heights draw nothing, as in the Python API.
void tfb_pixel(tile_fb *fb, int x, int y, uint8_t color);
int tfb_get_pixel(const tile_fb *fb, int x, int y);   // -1 off screen
void tfb_fill(tile_fb *fb, uint8_t color);
void tfb_fill_rect(tile_fb *fb, int x, int y, int width, int height, uint8_t color);
void tfb_hline(tile_fb *fb, int x, int y, int width, uint8_t color);
void tfb_vline(tile_fb *fb, int x, int y, int height, uint8_t color);
void tfb_rect(tile_fb *fb, int x, int y, int width, int height, uint8_t color);
// Endpoints are not clipped so the Bresenham phase matches Python. The int16
// ranges keep every intermediate value in 32 bits.
void tfb_line(tile_fb *fb, int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint8_t color);
void tfb_circle(tile_fb *fb, int16_t x, int16_t y, uint16_t radius, uint8_t color);
// Required after writing fb->buffer directly; marks the clipped pixel rect.
void tfb_mark_dirty(tile_fb *fb, int x, int y, int width, int height);

// Device side (tile_fb_io.c). tfb_initialize checks ABI 0.6, height 240 and
// PATTERN_COUNT 1200 (KH_BAD_ARGUMENT otherwise), stops the display, writes
// the map, upper-bit table, scroll, raster table and backdrop, uploads all
// patterns and then enables BG when show is true. Palette RGB values are the
// caller's. On failure every tile is dirty and display-off is attempted.
kh_status tfb_initialize(tile_fb *fb, bool show);
// Sends each dirty run (1023/1024 bank split inside) and FENCEs it; a run
// becomes clean only after its FENCE and error check succeed. A failure stops
// the flush and nothing is resent. max_gap 1..1198 also sends clean gaps of at
// most that many tiles between runs, marked dirty before any I/O.
kh_status tfb_flush(tile_fb *fb, unsigned max_gap);

// Microsecond clock for the flush statistics, provided by the firmware
// (time_us_64) or by the PC test.
uint64_t tfb_now_us(void);

#endif
