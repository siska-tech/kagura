// SPDX-License-Identifier: Apache-2.0
#include "kd_tile4.h"

#include <string.h>

#include "kd_fault.h"

void kd_tile4_pack_tile(const kd_fb *fb, unsigned tile, uint8_t out[KD_TILE4_BYTES]) {
    const uint8_t *src = fb->px + (tile / KD_TILE_COLS) * 8 * KD_STRIDE + (tile % KD_TILE_COLS) * 4;
    for (int row = 0; row < 8; row++) {
        int dst = KD_FAULTY(KD_FAULT_TILE4_ROWS) ? 7 - row : row;
        memcpy(out + dst * 4, src + row * KD_STRIDE, 4);
    }
}

void kd_tile4_pack_all(const kd_fb *fb, uint8_t out[KD_TILE4_TOTAL]) {
    for (unsigned t = 0; t < KD_TILES; t++) kd_tile4_pack_tile(fb, t, out + t * KD_TILE4_BYTES);
}

void kd_tile4_unpack_tile(kd_fb *fb, unsigned tile, const uint8_t in[KD_TILE4_BYTES]) {
    uint8_t *dst = fb->px + (tile / KD_TILE_COLS) * 8 * KD_STRIDE + (tile % KD_TILE_COLS) * 4;
    for (int row = 0; row < 8; row++) {
        if (memcmp(dst + row * KD_STRIDE, in + row * 4, 4) != 0) {
            memcpy(dst + row * KD_STRIDE, in + row * 4, 4);
            fb->dirty[tile >> 3] |= (uint8_t)(1u << (tile & 7));
        }
    }
}

int kd_tile4_ref_get(const uint8_t *tiles, unsigned cols, int x, int y) {
    unsigned tile = (unsigned)(y / 8) * cols + (unsigned)(x / 8);
    uint8_t b = tiles[tile * 32 + (unsigned)(y % 8) * 4 + (unsigned)(x % 8) / 2];
    return (x % 2 == 0) ? b >> 4 : b & 15;
}

static void clear_run(kd_fb *fb, unsigned first, unsigned count) {
    for (unsigned t = first; t < first + count; t++)
        fb->dirty[t >> 3] &= (uint8_t)~(1u << (t & 7));
}

bool kd_tile4_flush(kd_fb *fb, unsigned max_gap, uint8_t *staging, unsigned staging_tiles,
                    kd_tile4_sink sink, void *ctx, kd_tile4_stats *stats) {
    kd_tile4_stats s = {0};
    bool ok = true;
    unsigned t = 0;
    while (t < KD_TILES && staging_tiles > 0) {
        if (!kd_fb_tile_dirty(fb, t)) { t++; continue; }
        // Extend the run over dirty tiles and short clean gaps.
        unsigned first = t, last = t, u = t + 1;
        while (u < KD_TILES && u - first < staging_tiles) {
            if (kd_fb_tile_dirty(fb, u)) { last = u++; continue; }
            unsigned g = 0;
            while (u + g < KD_TILES && !kd_fb_tile_dirty(fb, u + g)) g++;
            // Stop at a long or trailing gap, or when the next dirty tile
            // would not fit in staging.
            if (g > max_gap || u + g >= KD_TILES || u + g - first >= staging_tiles) break;
            u += g;
        }
        unsigned count = last - first + 1;
        unsigned run_gap = 0;
        for (unsigned v = first; v <= last; v++) {
            if (!kd_fb_tile_dirty(fb, v)) run_gap++;
            kd_tile4_pack_tile(fb, v, staging + (v - first) * KD_TILE4_BYTES);
        }
        if (!sink(ctx, first, count, staging)) {
            ok = false;
            if (KD_FAULTY(KD_FAULT_FLUSH_CLEAN)) clear_run(fb, first, count);
            break;
        }
        clear_run(fb, first, count);
        s.runs++;
        s.tiles += count;
        s.bytes += count * KD_TILE4_BYTES;
        s.gap_tiles += run_gap;
        t = last + 1;
    }
    if (stats) *stats = s;
    return ok;
}

unsigned kd_kagura_scroll_y(kd_placement p) {
    return p == KD_PLACE_CENTER ? 256 - 20 : 0;
}

// Map row r holds desktop tile row r for r < 25. CENTER scrolls by -20 lines:
// output line L shows map line (L + 236) mod 256, so desktop line 0 appears
// on output line 20 and rows 25..31 (wrapping) form the border.
unsigned kd_kagura_map_pattern(kd_placement p, unsigned col, unsigned row) {
    (void)p;
    if (col < KD_TILE_COLS && row < KD_TILE_ROWS) return row * KD_TILE_COLS + col;
    return KD_BLANK_PATTERN;
}

int kd_kagura_line_to_desktop(kd_placement p, int line) {
    if (line < 0 || line >= 240) return -1;
    int map_line = (line + (int)kd_kagura_scroll_y(p)) & 255;
    return map_line < KD_H ? map_line : -1;
}
