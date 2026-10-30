// SPDX-License-Identifier: Apache-2.0
// Procedural sunset lake (img_scene.h). Integer per pixel; sinf only fills the
// tables in scene_init. The smooth gradients exercise the dithering and the
// per-cell palettes far more than flat colours would.
#include "img_scene.h"

#include <math.h>

#define WIDTH 320
#define HORIZON 150
#define SUN_X 204
#define SUN_Y 128
#define SUN_R 15

static uint8_t ridge[3][WIDTH];   // top row of the far, middle and near ridge
static int8_t sine[256];          // 127 * sin(2 pi i / 256)

void scene_init(void) {
    for (int i = 0; i < 256; i++) sine[i] = (int8_t)lrintf(127.0f * sinf(6.2831853f * (float)i / 256.0f));
    for (int x = 0; x < WIDTH; x++) {
        float f = (float)x;
        ridge[0][x] = (uint8_t)(108.0f + 10.0f * sinf(0.021f * f + 1.0f) + 6.0f * sinf(0.057f * f + 2.0f) +
                                3.0f * sinf(0.13f * f));
        ridge[1][x] = (uint8_t)(124.0f + 9.0f * sinf(0.030f * f + 4.0f) + 5.0f * sinf(0.083f * f) +
                                2.0f * sinf(0.21f * f + 1.0f));
        ridge[2][x] = (uint8_t)(138.0f + 7.0f * sinf(0.045f * f + 2.5f) + 4.0f * sinf(0.11f * f + 0.3f) +
                                2.0f * sinf(0.31f * f));
    }
}

static uint8_t clamp(int v) { return (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v); }

static void mix(uint8_t c[3], int r, int g, int b, int w) {   // w/256 of the way to (r, g, b)
    c[0] = clamp(c[0] + (r - c[0]) * w / 256);
    c[1] = clamp(c[1] + (g - c[1]) * w / 256);
    c[2] = clamp(c[2] + (b - c[2]) * w / 256);
}

static void sky(unsigned x, unsigned y, uint8_t c[3]) {
    static const int16_t stop[4][4] = {   // row, R, G, B
        {0, 16, 18, 64}, {70, 96, 44, 120}, {118, 222, 96, 92}, {150, 255, 196, 112}};
    unsigned s = 0;
    while (s < 2 && (int)y >= stop[s + 1][0]) s++;
    int span = stop[s + 1][0] - stop[s][0], w = ((int)y - stop[s][0]) * 256 / span;
    for (int k = 0; k < 3; k++) c[k] = clamp(stop[s][k + 1] + (stop[s + 1][k + 1] - stop[s][k + 1]) * w / 256);
    int dx = (int)x - SUN_X, dy = (int)y - SUN_Y, d2 = dx * dx + dy * dy;
    if (d2 <= SUN_R * SUN_R) {
        c[0] = 255, c[1] = 246, c[2] = 214;
        return;
    }
    int glow = 90000 / (d2 + 300);
    c[0] = clamp(c[0] + glow), c[1] = clamp(c[1] + glow * 3 / 4), c[2] = clamp(c[2] + glow * 3 / 8);
    if (y < 64) {   // sparse stars, fading towards the glow
        uint32_t h = x * 73856093u ^ y * 19349663u;
        h ^= h >> 13, h *= 0x5bd1e995u, h ^= h >> 15;
        if ((h & 511u) == 0) {
            int v = (64 - (int)y) * 3;
            c[0] = clamp(c[0] + v), c[1] = clamp(c[1] + v), c[2] = clamp(c[2] + v);
        }
    }
}

static void above(unsigned x, unsigned y, uint8_t c[3]) {   // sky and ridges, y < HORIZON
    sky(x, y, c);
    int rim = 255 - (x > SUN_X ? x - SUN_X : SUN_X - x) * 2;   // ridges catch light near the sun
    if ((int)y >= ridge[0][x]) {
        mix(c, 104, 64, 128, 150);
        if ((int)y - ridge[0][x] < 2 && rim > 0) mix(c, 255, 170, 110, rim / 2);
    }
    if ((int)y >= ridge[1][x]) {
        int depth = (int)y - ridge[1][x];
        c[0] = clamp(62 - depth / 2), c[1] = clamp(38 - depth / 4), c[2] = clamp(92 - depth);
        if (depth < 2 && rim > 0) mix(c, 230, 120, 90, rim / 3);
    }
    if ((int)y >= ridge[2][x]) {
        int depth = (int)y - ridge[2][x];
        c[0] = clamp(30 - depth), c[1] = clamp(20 - depth / 2), c[2] = clamp(50 - depth);
    }
}

void scene_rgb(void *ctx, unsigned x, unsigned y, uint8_t rgb[3]) {
    (void)ctx;
    if (y < HORIZON) {
        above(x, y, rgb);
        return;
    }
    // Lake: the mirrored scene, displaced by ripples that grow towards the viewer.
    int d = (int)y - HORIZON;
    int rx = (int)x + sine[(d * 9 + (int)x * 2) & 255] * (1 + d / 12) / 127;
    rx = rx < 0 ? 0 : rx >= WIDTH ? WIDTH - 1 : rx;
    above((unsigned)rx, (unsigned)(2 * HORIZON - 1 - (int)y), rgb);
    rgb[0] = clamp(rgb[0] * 200 / 256), rgb[1] = clamp(rgb[1] * 210 / 256 + 4), rgb[2] = clamp(rgb[2] * 230 / 256 + 12);
    // Glittering sun path: a band whose width wobbles row by row, lit where a
    // ripple wave along the row peaks.
    int half = (8 + d / 3) * (160 + sine[(d * 37) & 255]) / 256, off = (int)x - SUN_X;
    if (off > -half && off < half) {
        int s = sine[((int)x * 11 + d * 29 + sine[(d * 13) & 255]) & 255];
        if (s > 60) {
            int v = (s - 60) * (half - (off < 0 ? -off : off)) / (half + 1) * (110 - d) / 64;
            rgb[0] = clamp(rgb[0] + v * 2), rgb[1] = clamp(rgb[1] + v * 3 / 2), rgb[2] = clamp(rgb[2] + v / 2);
        }
    }
    mix(rgb, 8, 10, 26, d * 120 / 90);
}
