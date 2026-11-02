// SPDX-License-Identifier: Apache-2.0
// TILE4 export: the desktop framebuffer as KAGURA-9 8x8 4bpp patterns.
//
// Tile t = (y/8)*40 + x/8 covers pixels (8*(t%40).., 8*(t/40)..). Pattern
// byte (y%8)*4 + (x%8)/2 holds two pixels, even x in the high nibble. The
// 1,000 tiles of 320x200 take 32,000 bytes; tile t is exported as pattern
// base+t. A tile row is the same 4 bytes as the linear row, so packing is a
// gather of eight 32-bit words.
//
// Hardware colour 0 is transparent and shows BACKDROP. The desktop keeps 0
// opaque by having the transport set BACKDROP to palette*16+0 (as the SDK's
// TileFramebuffer does); the exported bytes are unchanged.
#ifndef KD_TILE4_H
#define KD_TILE4_H

#include "kd_fb.h"

#define KD_TILE4_BYTES 32
#define KD_TILE4_TOTAL (KD_TILES * KD_TILE4_BYTES)

void kd_tile4_pack_tile(const kd_fb *fb, unsigned tile, uint8_t out[KD_TILE4_BYTES]);
void kd_tile4_pack_all(const kd_fb *fb, uint8_t out[KD_TILE4_TOTAL]);
// Writes a tile back (round-trip tests, imports); marks it dirty if changed.
void kd_tile4_unpack_tile(kd_fb *fb, unsigned tile, const uint8_t in[KD_TILE4_BYTES]);
// Reads pixel (x,y) of a TILE4 image that is cols tiles wide, by the formula
// alone. Used as the independent reference in the tests.
int kd_tile4_ref_get(const uint8_t *tiles, unsigned cols, int x, int y);

// Receives one run of consecutive dirty tiles: patterns first..first+count-1.
// Returns false on a transport failure; the run then stays dirty.
typedef bool (*kd_tile4_sink)(void *ctx, unsigned first, unsigned count, const uint8_t *data);

typedef struct {
    uint32_t runs, tiles, bytes;   // accepted by the sink, gap tiles included
    uint32_t gap_tiles;            // clean tiles sent to join runs (max_gap)
} kd_tile4_stats;

// Packs dirty tiles into staging (staging_tiles * 32 bytes, at least one
// tile) and hands runs to sink in ascending order. A run is split when it
// fills the staging buffer. Clean gaps of at most max_gap tiles between dirty
// tiles are sent too (fewer, longer transfers). Tiles become clean only after
// the sink accepted them; the first failure stops the flush.
bool kd_tile4_flush(kd_fb *fb, unsigned max_gap, uint8_t *staging, unsigned staging_tiles,
                    kd_tile4_sink sink, void *ctx, kd_tile4_stats *stats);

// Placement inside KAGURA-9's 320x240 mode (BG map 64x32 cells, SCROLL_Y
// modulo 256). The plane occupies patterns 0..999 and pattern 1000 must be
// all colour 0 (it shows BACKDROP); the other 199 patterns are not touched.
typedef enum {
    KD_PLACE_TOP,      // desktop on lines 0..199, 40 border lines below, SCROLL_Y 0
    KD_PLACE_CENTER,   // 20 border lines above and below, SCROLL_Y 236
} kd_placement;

#define KD_BLANK_PATTERN KD_TILES

// Pattern index for BG map cell (col 0..63, row 0..31).
unsigned kd_kagura_map_pattern(kd_placement p, unsigned col, unsigned row);
unsigned kd_kagura_scroll_y(kd_placement p);
// Desktop y of a 320x240 output line, or -1 when the line is border.
int kd_kagura_line_to_desktop(kd_placement p, int line);

#endif
