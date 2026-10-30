// SPDX-License-Identifier: Apache-2.0
// Pseudo-256-colour quantizer (img_quant.h). Colours are compared with the
// weighted squared distance 2*dR^2 + 4*dG^2 + 3*dB^2 on RGB888. The source is
// re-evaluated instead of stored: 76800 RGB pixels would not fit the RAM.
#include "img_quant.h"

#include <stdbool.h>
#include <string.h>

#define CELLS 1200
#define TILE_PIXELS 64

static uint8_t centre[IQ_PALETTES * IQ_COLOURS][3];   // RGB888 colours while fitting
static uint8_t px[TILE_PIXELS][3];

static inline int dist(const uint8_t *a, const uint8_t *b) {
    int r = a[0] - b[0], g = a[1] - b[1], bl = a[2] - b[2];
    return 2 * r * r + 4 * g * g + 3 * bl * bl;
}

static unsigned nearest(const uint8_t *c, const uint8_t (*set)[3], unsigned n, int *best) {
    unsigned index = 0;
    int d0 = dist(c, set[0]);
    for (unsigned i = 1; i < n; i++) {
        int d = dist(c, set[i]);
        if (d < d0) { d0 = d; index = i; }
    }
    if (best) *best = d0;
    return index;
}

static void load_tile(iq_source source, void *ctx, unsigned tile) {
    unsigned x0 = tile % 40 * 8, y0 = tile / 40 * 8;
    for (unsigned i = 0; i < TILE_PIXELS; i++) source(ctx, x0 + i % 8, y0 + i / 8, px[i]);
}

// k-means of the cell mean colours into IQ_PALETTES groups, seeded by
// farthest-point selection so the result is deterministic.
static void group_cells(const uint8_t (*mean)[3], uint8_t *cell) {
    uint8_t seed[IQ_PALETTES][3];
    uint32_t sum[3] = {0, 0, 0};
    for (unsigned t = 0; t < CELLS; t++) for (unsigned c = 0; c < 3; c++) sum[c] += mean[t][c];
    uint8_t all[3] = {(uint8_t)(sum[0] / CELLS), (uint8_t)(sum[1] / CELLS), (uint8_t)(sum[2] / CELLS)};
    for (unsigned k = 0; k < IQ_PALETTES; k++) {
        unsigned far = 0;
        int far_d = -1;
        for (unsigned t = 0; t < CELLS; t++) {
            int d = k ? 0 : dist(mean[t], all);
            if (k) nearest(mean[t], (const uint8_t (*)[3])seed, k, &d);
            if (d > far_d) { far_d = d; far = t; }
        }
        memcpy(seed[k], mean[far], 3);
    }
    for (unsigned it = 0; it < 12; it++) {
        uint32_t acc[IQ_PALETTES][4];
        memset(acc, 0, sizeof acc);
        for (unsigned t = 0; t < CELLS; t++) {
            unsigned k = nearest(mean[t], (const uint8_t (*)[3])seed, IQ_PALETTES, NULL);
            cell[t] = (uint8_t)k;
            for (unsigned c = 0; c < 3; c++) acc[k][c] += mean[t][c];
            acc[k][3]++;
        }
        for (unsigned k = 0; k < IQ_PALETTES; k++)
            if (acc[k][3]) for (unsigned c = 0; c < 3; c++) seed[k][c] = (uint8_t)(acc[k][c] / acc[k][3]);
    }
}

// Colours 1..15 for the cells of palette p (0 is the shared colour):
// farthest-point seeds over every fourth pixel when seed is set, then
// `iterations` k-means passes.
static void fit_palette(iq_source source, void *ctx, const uint8_t *cell, unsigned p, bool seed,
                        unsigned iterations) {
    uint8_t (*colour)[3] = &centre[p * IQ_COLOURS];
    if (seed) {
        unsigned have = 1;                           // colour 0 is the shared colour
        for (unsigned k = 1; k < IQ_COLOURS; k++) {
            uint8_t far[3] = {0, 0, 0};
            int far_d = -1;
            for (unsigned t = 0; t < CELLS; t++) {
                if (cell[t] != p) continue;
                for (unsigned i = (t * 7u) & 3u; i < TILE_PIXELS; i += 4) {
                    uint8_t c[3];
                    source(ctx, t % 40 * 8 + i % 8, t / 40 * 8 + i / 8, c);
                    int d;
                    nearest(c, (const uint8_t (*)[3])colour, have, &d);
                    if (d > far_d) { far_d = d; memcpy(far, c, 3); }
                }
            }
            if (far_d <= 0) break;                   // fewer than 16 distinct colours
            memcpy(colour[have++], far, 3);
        }
        for (unsigned k = have; k < IQ_COLOURS; k++) memcpy(colour[k], colour[have - 1], 3);
    }
    for (unsigned it = 0; it < iterations; it++) {
        uint32_t acc[IQ_COLOURS][4];
        memset(acc, 0, sizeof acc);
        for (unsigned t = 0; t < CELLS; t++) {
            if (cell[t] != p) continue;
            load_tile(source, ctx, t);
            for (unsigned i = 0; i < TILE_PIXELS; i++) {
                unsigned k = nearest(px[i], (const uint8_t (*)[3])colour, IQ_COLOURS, NULL);
                for (unsigned c = 0; c < 3; c++) acc[k][c] += px[i][c];
                acc[k][3]++;
            }
        }
        for (unsigned k = 1; k < IQ_COLOURS; k++)    // colour 0 stays the shared colour
            if (acc[k][3])
                for (unsigned c = 0; c < 3; c++) colour[k][c] = (uint8_t)((acc[k][c] + acc[k][3] / 2) / acc[k][3]);
    }
}

// Each cell moves to the palette with the least summed error over its pixels.
static void reassign(iq_source source, void *ctx, uint8_t *cell) {
    for (unsigned t = 0; t < CELLS; t++) {
        load_tile(source, ctx, t);
        unsigned best_p = cell[t];
        int64_t best = INT64_MAX;
        for (unsigned p = 0; p < IQ_PALETTES; p++) {
            int64_t err = 0;
            for (unsigned i = 0; i < TILE_PIXELS && err < best; i++) {
                int d;
                nearest(px[i], (const uint8_t (*)[3])&centre[p * IQ_COLOURS], IQ_COLOURS, &d);
                err += d;
            }
            if (err < best) { best = err; best_p = p; }
        }
        cell[t] = (uint8_t)best_p;
    }
}

int iq_quantize(iq_source source, void *ctx, unsigned rounds, iq_image *out, uint8_t *pixels,
                void (*progress)(const char *stage)) {
    // The cell means borrow the start of pixels, which the dither stage
    // overwrites last; no heap is needed.
    uint8_t (*mean)[3] = (uint8_t (*)[3])pixels;
    if (progress) progress("cell means");
    for (unsigned t = 0; t < CELLS; t++) {
        load_tile(source, ctx, t);
        uint32_t sum[3] = {0, 0, 0};
        for (unsigned i = 0; i < TILE_PIXELS; i++) for (unsigned c = 0; c < 3; c++) sum[c] += px[i][c];
        for (unsigned c = 0; c < 3; c++) mean[t][c] = (uint8_t)((sum[c] + 32) / 64);
    }
    if (progress) progress("group cells");
    group_cells((const uint8_t (*)[3])mean, out->cell);
    // Pixel value 0 is transparent and shows BACKDROP (palette 0 colour 0),
    // so colour 0 must be one colour in every palette: the darkest cell mean.
    unsigned dark = 0;
    for (unsigned t = 1; t < CELLS; t++)
        if (2 * mean[t][0] + 5 * mean[t][1] + mean[t][2] < 2 * mean[dark][0] + 5 * mean[dark][1] + mean[dark][2])
            dark = t;
    for (unsigned p = 0; p < IQ_PALETTES; p++) memcpy(centre[p * IQ_COLOURS], mean[dark], 3);
    if (progress) progress("fit palettes");
    for (unsigned p = 0; p < IQ_PALETTES; p++) fit_palette(source, ctx, out->cell, p, true, 6);
    for (unsigned r = 0; r < rounds; r++) {
        if (progress) progress("reassign cells");
        reassign(source, ctx, out->cell);
        if (progress) progress("refit palettes");
        for (unsigned p = 0; p < IQ_PALETTES; p++) fit_palette(source, ctx, out->cell, p, false, 4);
    }
    // RGB444 for the device; dithering compares against the rounded colours.
    for (unsigned i = 0; i < IQ_PALETTES * IQ_COLOURS; i++) {
        unsigned q[3];
        for (unsigned c = 0; c < 3; c++) {
            q[c] = (centre[i][c] * 15u + 127u) / 255u;
            centre[i][c] = (uint8_t)(q[c] * 17u);
        }
        out->palette[i] = (uint16_t)(q[0] << 8 | q[1] << 4 | q[2]);
    }
    if (progress) progress("dither");
    static const int8_t bayer[16] = {0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5};
    for (unsigned t = 0; t < CELLS; t++) {
        load_tile(source, ctx, t);
        const uint8_t (*colour)[3] = (const uint8_t (*)[3])&centre[out->cell[t] * IQ_COLOURS];
        for (unsigned i = 0; i < TILE_PIXELS; i++) {
            unsigned x = i % 8, y = i / 8;
            int offset = (bayer[(y & 3) * 4 + (x & 3)] * 2 - 15) * 17 / 32;   // within half an RGB444 step
            uint8_t c[3];
            for (unsigned k = 0; k < 3; k++) {
                int v = px[i][k] + offset;
                c[k] = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
            }
            unsigned index = nearest(c, colour, IQ_COLOURS, NULL);
            uint8_t *b = &pixels[t * 32 + y * 4 + x / 2];
            *b = (uint8_t)(x & 1 ? (*b & 0xf0) | index : (*b & 0x0f) | index << 4);
        }
    }
    return 0;
}
