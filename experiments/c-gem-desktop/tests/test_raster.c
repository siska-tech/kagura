// SPDX-License-Identifier: Apache-2.0
// Layer A tests: packing, clipping, primitives and dirty tiles against an
// independent per-pixel reference model; TILE4 layout, flush, placement;
// damage and region sets; sprites.
#include <stdlib.h>
#include <string.h>

#include "kd_fb.h"
#include "kd_font.h"
#include "kd_gfx.h"
#include "kd_region.h"
#include "kd_sprite.h"
#include "kd_test.h"
#include "kd_tile4.h"

#ifdef KD_HAVE_TILE_FB
#include "tile_fb.h"
#endif

// ---- reference model: one byte per pixel, every rule written per pixel ----

typedef struct {
    uint8_t p[KD_H][KD_W];
    int64_t cx0, cy0, cx1, cy1;   // clip, half open
} ref_fb;

static kd_fb fb, fb2;
static ref_fb ref;

static void ref_init(uint8_t c) {
    memset(ref.p, c, sizeof ref.p);
    ref.cx0 = ref.cy0 = 0;
    ref.cx1 = KD_W;
    ref.cy1 = KD_H;
}

static void ref_clip(int x, int y, int w, int h) {
    // Clip is stored as int16 by kd_fb; mirror that truncation, then intersect.
    kd_rect r = kd_rect_make(x, y, w, h);
    int64_t x0 = r.x, y0 = r.y, x1 = (int64_t)r.x + r.w, y1 = (int64_t)r.y + r.h;
    ref.cx0 = x0 < 0 ? 0 : x0;
    ref.cy0 = y0 < 0 ? 0 : y0;
    ref.cx1 = x1 > KD_W ? KD_W : x1;
    ref.cy1 = y1 > KD_H ? KD_H : y1;
    if (r.w <= 0 || r.h <= 0) ref.cx1 = ref.cx0;
}

static void ref_set(int64_t x, int64_t y, int c) {
    if (x >= ref.cx0 && x < ref.cx1 && y >= ref.cy0 && y < ref.cy1) ref.p[y][x] = (uint8_t)(c & 15);
}

static void ref_fill(int64_t x, int64_t y, int64_t w, int64_t h, int c) {
    for (int py = 0; py < KD_H; py++)
        for (int px = 0; px < KD_W; px++)
            if (px >= x && px < x + w && py >= y && py < y + h) ref_set(px, py, c);
}

static void ref_rect(int64_t x, int64_t y, int64_t w, int64_t h, int c) {
    for (int py = 0; py < KD_H; py++)
        for (int px = 0; px < KD_W; px++)
            if (px >= x && px < x + w && py >= y && py < y + h &&
                (px == x || px == x + w - 1 || py == y || py == y + h - 1))
                ref_set(px, py, c);
}

static void ref_pattern(int64_t x, int64_t y, int64_t w, int64_t h, const uint8_t rows[8], int c0, int c1) {
    for (int py = 0; py < KD_H; py++)
        for (int px = 0; px < KD_W; px++)
            if (px >= x && px < x + w && py >= y && py < y + h)
                ref_set(px, py, (rows[py % 8] >> (7 - px % 8)) & 1 ? c1 : c0);
}

static void ref_blit(int x, int y, const uint8_t *src, int w, int h, int zoom, int key) {
    for (int py = 0; py < KD_H; py++)
        for (int px = 0; px < KD_W; px++) {
            if (px < x || py < y || px >= x + w * zoom || py >= y + h * zoom) continue;
            int c = kd_tile4_ref_get(src, (unsigned)(w / 8), (px - x) / zoom, (py - y) / zoom);
            if (c != key) ref_set(px, py, c);
        }
}

static int diff_count(void) {
    int n = 0;
    for (int y = 0; y < KD_H; y++)
        for (int x = 0; x < KD_W; x++) n += kd_fb_get(&fb, x, y) != ref.p[y][x];
    return n;
}

static int coord(uint32_t *s, int span) {
    switch (kd_rand(s) % 8) {
    case 0: return -kd_rand_range(s, 1, 40);
    case 1: return span + kd_rand_range(s, -8, 40);
    case 2: return kd_rand_range(s, 0, 3);
    case 3: return span - kd_rand_range(s, 1, 4);
    default: return kd_rand_range(s, 0, span - 1);
    }
}

// ---- tests ----

static void test_pack_unpack(void) {
    kd_fb_init(&fb, 0);
    for (int c = 0; c < 16; c++)
        for (int x = 0; x < 4; x++) {
            kd_fb_pixel(&fb, x, c, (uint8_t)c);
            CHECK_EQ(kd_fb_get(&fb, x, c), c);
        }
    kd_fb_init(&fb, 0);
    kd_fb_pixel(&fb, 0, 0, 0xA);
    kd_fb_pixel(&fb, 1, 0, 0x5);
    CHECK_EQ(fb.px[0], 0xA5);
    kd_fb_pixel(&fb, 319, 199, 0x7);
    CHECK_EQ(fb.px[KD_FB_BYTES - 1], 0x07);
    kd_fb_pixel(&fb, 2, 1, 0xF);    // neighbour nibble kept
    kd_fb_pixel(&fb, 3, 1, 0x1);
    kd_fb_pixel(&fb, 2, 1, 0x3);
    CHECK_EQ(fb.px[KD_STRIDE + 1], 0x31);
    kd_fb_pixel(&fb, 5, 5, 0x1F);   // masked to 4 bits
    CHECK_EQ(kd_fb_get(&fb, 5, 5), 0xF);
    CHECK_EQ(kd_fb_get(&fb, -1, 0), -1);
    CHECK_EQ(kd_fb_get(&fb, 320, 0), -1);
    CHECK_EQ(kd_fb_get(&fb, 0, 200), -1);
}

static void test_random_primitives_vs_reference(void) {
    static const uint8_t pat[8] = {0x81, 0x42, 0x24, 0x18, 0xF0, 0x0F, 0xAA, 0x55};
    uint8_t src[4 * 32];
    uint32_t s = 12345;
    for (unsigned i = 0; i < sizeof src; i++) src[i] = (uint8_t)kd_rand(&s);
    for (int round = 0; round < 3; round++) {
        kd_fb_init(&fb, (uint8_t)round);
        ref_init((uint8_t)round);
        for (int op = 0; op < 120; op++) {
            int x = coord(&s, KD_W), y = coord(&s, KD_H);
            int w = kd_rand_range(&s, -2, 340), h = kd_rand_range(&s, -2, 220);
            int c = (int)(kd_rand(&s) & 15);
            if (op % 10 == 0) {
                int cx = coord(&s, KD_W), cy = coord(&s, KD_H);
                int cw = kd_rand_range(&s, -4, 360), ch = kd_rand_range(&s, -4, 240);
                kd_fb_set_clip(&fb, kd_rect_make(cx, cy, cw, ch));
                ref_clip(cx, cy, cw, ch);
            }
            switch (kd_rand(&s) % 7) {
            case 0: kd_fb_fill_rect(&fb, x, y, w, h, (uint8_t)c); ref_fill(x, y, w, h, c); break;
            case 1: kd_fb_rect(&fb, x, y, w, h, (uint8_t)c); ref_rect(x, y, w, h, c); break;
            case 2: kd_fb_pixel(&fb, x, y, (uint8_t)c); ref_set(x, y, c); break;
            case 3: kd_fb_hline(&fb, x, y, w, (uint8_t)c); ref_fill(x, y, w, 1, c); break;
            case 4: kd_fb_vline(&fb, x, y, h, (uint8_t)c); ref_fill(x, y, 1, h, c); break;
            case 5:
                kd_fb_pattern_rect(&fb, x, y, w % 64, h % 64, pat, (uint8_t)c, (uint8_t)(c ^ 5));
                ref_pattern(x, y, w % 64, h % 64, pat, c, c ^ 5);
                break;
            default: {
                int zoom = kd_rand_range(&s, 1, 3), key = (op & 1) ? KD_NO_KEY : c;
                kd_fb_blit_tile4(&fb, x, y, src, 16, 16, zoom, key);
                ref_blit(x, y, src, 16, 16, zoom, key);
            }
            }
        }
        CHECK_EQ(diff_count(), 0);
    }
}

static void test_clip_all_edges(void) {
    // A full-screen fill clipped to each edge band must stop exactly there.
    const kd_rect clips[] = {
        {0, 0, 1, 200}, {319, 0, 1, 200}, {0, 0, 320, 1}, {0, 199, 320, 1},
        {-5, -5, 10, 10}, {315, 195, 10, 10}, {-100, 50, 101, 1}, {319, 199, 100, 100},
        {7, 7, 1, 1}, {8, 8, 0, 5}, {0, 0, 320, 200},
    };
    for (unsigned i = 0; i < sizeof clips / sizeof clips[0]; i++) {
        kd_rect c = clips[i];
        kd_fb_init(&fb, 1);
        ref_init(1);
        kd_fb_set_clip(&fb, c);
        ref_clip(c.x, c.y, c.w, c.h);
        kd_fb_fill_rect(&fb, -1000, -1000, 4000, 4000, 9);
        ref_fill(-1000, -1000, 4000, 4000, 9);
        kd_fb_line(&fb, -50, -30, 400, 260, 4);
        // Reference line: same Bresenham, per-pixel clip.
        {
            int x0 = -50, y0 = -30, x1 = 400, y1 = 260;
            int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1, dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
            int err = dx + dy;
            for (;;) {
                ref_set(x0, y0, 4);
                if (x0 == x1 && y0 == y1) break;
                int e2 = 2 * err;
                if (e2 >= dy) { err += dy; x0 += sx; }
                if (e2 <= dx) { err += dx; y0 += sy; }
            }
        }
        CHECK_EQ(diff_count(), 0);
    }
    // Extreme coordinates must not overflow.
    kd_fb_init(&fb, 0);
    ref_init(0);
    kd_fb_fill_rect(&fb, -2147483647, 10, 2147483647, 5, 3);
    ref_fill(-2147483647, 10, 2147483647, 5, 3);
    kd_fb_fill_rect(&fb, 300, 20, 2147483647, 5, 6);
    ref_fill(300, 20, 2147483647, 5, 6);
    CHECK_EQ(diff_count(), 0);
}

static void test_dirty_is_exact(void) {
    static uint8_t before[KD_FB_BYTES];
    uint32_t s = 99;
    kd_fb_init(&fb, 0);
    for (int op = 0; op < 400; op++) {
        memcpy(before, fb.px, sizeof before);
        kd_fb_clear_dirty(&fb);
        int x = coord(&s, KD_W), y = coord(&s, KD_H);
        int w = kd_rand_range(&s, 1, 30), h = kd_rand_range(&s, 1, 30);
        uint8_t c = (uint8_t)(kd_rand(&s) % 3);   // few colours: many no-op writes
        if (op & 1) kd_fb_fill_rect(&fb, x, y, w, h, c);
        else kd_fb_pixel(&fb, x, y, c);
        for (unsigned t = 0; t < KD_TILES; t++) {
            bool changed = false;
            unsigned base = (t / KD_TILE_COLS) * 8 * KD_STRIDE + (t % KD_TILE_COLS) * 4;
            for (int r = 0; r < 8; r++)
                changed |= memcmp(before + base + r * KD_STRIDE, fb.px + base + r * KD_STRIDE, 4) != 0;
            CHECK_EQ(kd_fb_tile_dirty(&fb, t), changed);
        }
    }
    kd_fb_init(&fb, 0);
    CHECK_EQ(kd_fb_dirty_count(&fb), KD_TILES);
}

static void test_tile4_layout(void) {
    static uint8_t out[KD_TILE4_TOTAL];
    kd_fb_init(&fb, 0);
    kd_fb_pixel(&fb, 0, 0, 0xA);
    kd_fb_pixel(&fb, 1, 0, 0x5);
    kd_fb_pixel(&fb, 7, 7, 0x3);
    kd_fb_pixel(&fb, 8, 0, 0xC);
    kd_fb_pixel(&fb, 0, 8, 0xE);
    kd_fb_pixel(&fb, 319, 199, 0x9);
    kd_fb_pixel(&fb, 2, 1, 0x6);
    kd_tile4_pack_all(&fb, out);
    CHECK_EQ(out[0], 0xA5);                      // tile 0, row 0, even x high
    CHECK_EQ(out[31], 0x03);                     // tile 0, row 7, x 6..7
    CHECK_EQ(out[1 * 32], 0xC0);                 // tile 1 starts at x 8
    CHECK_EQ(out[40 * 32], 0xE0);                // tile 40 starts at y 8
    CHECK_EQ(out[4 + 1], 0x60);                  // row 1 at byte 4, x 2 in byte 1
    CHECK_EQ(out[999 * 32 + 31], 0x09);          // last tile, last nibble
    uint32_t s = 7;
    for (int i = 0; i < 3000; i++)
        kd_fb_pixel(&fb, kd_rand_range(&s, 0, 319), kd_rand_range(&s, 0, 199), (uint8_t)kd_rand(&s));
    kd_tile4_pack_all(&fb, out);
    for (int y = 0; y < KD_H; y++)
        for (int x = 0; x < KD_W; x++) CHECK_EQ(kd_tile4_ref_get(out, KD_TILE_COLS, x, y), kd_fb_get(&fb, x, y));
    // Unpack into a different buffer reproduces every pixel and marks dirt.
    kd_fb_init(&fb2, 3);
    kd_fb_clear_dirty(&fb2);
    for (unsigned t = 0; t < KD_TILES; t++) kd_tile4_unpack_tile(&fb2, t, out + t * 32);
    CHECK(memcmp(fb.px, fb2.px, KD_FB_BYTES) == 0);
    CHECK(kd_fb_dirty_count(&fb2) > 900);
}

#ifdef KD_HAVE_TILE_FB
// The repository's C TileFramebuffer (software/pico/tile_fb.c) uses the same
// tile formula for 320x240; its first 1,000 patterns are our 320x200 plane.
static tile_fb tfb;
static void test_tile4_matches_existing_tile_fb(void) {
    uint32_t s = 4242;
    kd_fb_init(&fb, 0);
    tfb_reset(&tfb, 0);
    for (int op = 0; op < 300; op++) {
        int x = coord(&s, KD_W), y = kd_rand_range(&s, -20, 230);
        int w = kd_rand_range(&s, -1, 90), h = kd_rand_range(&s, -1, 60);
        uint8_t c = (uint8_t)(kd_rand(&s) & 15);
        switch (op % 4) {
        case 0: kd_fb_fill_rect(&fb, x, y, w, h, c); tfb_fill_rect(&tfb, x, y, w, h, c); break;
        case 1: kd_fb_hline(&fb, x, y, w, c); tfb_hline(&tfb, x, y, w, c); break;
        case 2: kd_fb_vline(&fb, x, y, h, c); tfb_vline(&tfb, x, y, h, c); break;
        default: kd_fb_pixel(&fb, x, y, c); tfb_pixel(&tfb, x, y, c); break;
        }
    }
    static uint8_t out[KD_TILE4_TOTAL];
    kd_tile4_pack_all(&fb, out);
    CHECK(memcmp(out, tfb.buffer.bytes, KD_TILE4_TOTAL) == 0);
    for (int y = 0; y < KD_H; y++)
        for (int x = 0; x < KD_W; x++) CHECK_EQ(tfb_get_pixel(&tfb, x, y), kd_fb_get(&fb, x, y));
}
#endif

typedef struct {
    int calls, fail_at;
    unsigned first[64], count[64];
    uint8_t data[KD_TILE4_TOTAL];
} sink_log;

static bool record(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    sink_log *l = ctx;
    if (l->calls == l->fail_at) return false;
    if (l->calls < 64) {
        l->first[l->calls] = first;
        l->count[l->calls] = count;
    }
    memcpy(l->data + first * 32, data, count * 32);
    l->calls++;
    return true;
}

static void test_tile4_flush(void) {
    static sink_log log;
    uint8_t staging[3 * 32];
    kd_tile4_stats st;
    kd_fb_init(&fb, 0);
    kd_fb_clear_dirty(&fb);
    // Dirty tiles 0,1, 3, 10..17, 999.
    kd_fb_fill_rect(&fb, 0, 0, 16, 1, 5);
    kd_fb_pixel(&fb, 24, 0, 5);
    kd_fb_fill_rect(&fb, 80, 0, 64, 1, 5);
    kd_fb_pixel(&fb, 319, 199, 5);
    CHECK_EQ(kd_fb_dirty_count(&fb), 12);
    memset(&log, 0, sizeof log);
    log.fail_at = -1;
    CHECK(kd_tile4_flush(&fb, 0, staging, 3, record, &log, &st));
    // staging of 3 splits 10..17 into 10-12, 13-15, 16-17.
    CHECK_EQ(log.calls, 6);
    CHECK_EQ(st.tiles, 12);
    CHECK_EQ(st.bytes, 12 * 32);
    CHECK_EQ(st.gap_tiles, 0);
    CHECK_EQ(log.first[0], 0);
    CHECK_EQ(log.count[0], 2);
    CHECK_EQ(log.first[1], 3);
    CHECK_EQ(log.first[2], 10);
    CHECK_EQ(log.count[2], 3);
    CHECK_EQ(log.first[5], 999);
    CHECK_EQ(kd_fb_dirty_count(&fb), 0);
    uint8_t tile[32];
    kd_tile4_pack_tile(&fb, 13, tile);
    CHECK(memcmp(log.data + 13 * 32, tile, 32) == 0);
    // max_gap 1 joins 0,1,(2),3 into one run of 4 (staging 4 now).
    uint8_t staging4[8 * 32];
    kd_fb_mark_dirty_all(&fb);
    kd_fb_clear_dirty(&fb);
    kd_fb_fill_rect(&fb, 0, 0, 16, 1, 6);
    kd_fb_pixel(&fb, 24, 0, 6);
    memset(&log, 0, sizeof log);
    log.fail_at = -1;
    CHECK(kd_tile4_flush(&fb, 1, staging4, 8, record, &log, &st));
    CHECK_EQ(log.calls, 1);
    CHECK_EQ(st.tiles, 4);
    CHECK_EQ(st.gap_tiles, 1);
    // A failing sink leaves its run and everything after it dirty.
    kd_fb_fill_rect(&fb, 0, 0, 8, 1, 7);
    kd_fb_fill_rect(&fb, 160, 0, 8, 1, 7);
    memset(&log, 0, sizeof log);
    log.fail_at = 1;
    CHECK(!kd_tile4_flush(&fb, 0, staging4, 8, record, &log, &st));
    CHECK(!kd_fb_tile_dirty(&fb, 0));
    CHECK(kd_fb_tile_dirty(&fb, 20));
    CHECK_EQ(st.tiles, 1);
}

static void test_kagura_placement(void) {
    static uint8_t out[KD_TILE4_TOTAL];
    uint32_t s = 3;
    kd_fb_init(&fb, 0);
    for (int i = 0; i < 500; i++)
        kd_fb_fill_rect(&fb, kd_rand_range(&s, 0, 319), kd_rand_range(&s, 0, 199), 9, 7, (uint8_t)kd_rand(&s));
    kd_tile4_pack_all(&fb, out);
    for (int p = 0; p < 2; p++) {
        kd_placement pl = p ? KD_PLACE_CENTER : KD_PLACE_TOP;
        int first = p ? 20 : 0;
        for (int line = 0; line < 240; line++) {
            int dy = kd_kagura_line_to_desktop(pl, line);
            CHECK_EQ(dy, (line >= first && line < first + 200) ? line - first : -1);
            // Rebuild the output line from map + scroll + patterns, as the VDP does.
            int map_line = (line + (int)kd_kagura_scroll_y(pl)) & 255;
            for (int x = 0; x < KD_W; x += 3) {
                unsigned pat = kd_kagura_map_pattern(pl, (unsigned)x / 8, (unsigned)map_line / 8);
                if (dy < 0) {
                    CHECK_EQ(pat, KD_BLANK_PATTERN);
                    continue;
                }
                CHECK(pat < KD_TILES);
                uint8_t b = out[pat * 32 + (map_line % 8) * 4 + (x % 8) / 2];
                CHECK_EQ((x & 1) ? (b & 15) : (b >> 4), kd_fb_get(&fb, x, dy));
            }
        }
        for (unsigned row = 0; row < 32; row++)
            for (unsigned col = 0; col < 64; col++)
                CHECK_EQ(kd_kagura_map_pattern(pl, col, row),
                         (col < 40 && row < 25) ? row * 40 + col : KD_BLANK_PATTERN);
    }
    CHECK_EQ(kd_kagura_scroll_y(KD_PLACE_CENTER), 236);
}

// Pixels covered by a set of rects.
static void cover(uint8_t *map, const kd_rect *r, int n, int add) {
    for (int i = 0; i < n; i++)
        for (int y = r[i].y; y < r[i].y + r[i].h; y++)
            for (int x = r[i].x; x < r[i].x + r[i].w; x++)
                if (x >= 0 && y >= 0 && x < KD_W && y < KD_H) map[y * KD_W + x] = (uint8_t)(map[y * KD_W + x] + add);
}

static void test_damage_merge_rules(void) {
    kd_damage d;
    kd_damage_clear(&d);
    kd_damage_add(&d, kd_rect_make(0, 20, 10, 10));
    kd_damage_add(&d, kd_rect_make(10, 20, 10, 10));     // shares an edge, no waste
    CHECK_EQ(d.n, 1);
    CHECK_EQ(d.r[0].w, 20);
    kd_damage_add(&d, kd_rect_make(20, 30, 10, 10));     // corner only
    CHECK_EQ(d.n, 2);
    kd_damage_add(&d, kd_rect_make(2, 22, 3, 3));        // contained
    CHECK_EQ(d.n, 2);
    kd_damage_add(&d, kd_rect_make(100, 100, 50, 2));
    kd_damage_add(&d, kd_rect_make(100, 102, 2, 50));    // L shape would waste area
    CHECK_EQ(d.n, 4);
    kd_damage_add(&d, kd_rect_make(-10, -10, 5, 5));     // off screen
    CHECK_EQ(d.n, 4);
    kd_damage_add(&d, kd_rect_make(310, 190, 50, 50));   // clipped
    CHECK_EQ(d.r[d.n - 1].w, 10);
}

static void test_damage_coverage_property(void) {
    static uint8_t want[KD_W * KD_H], got[KD_W * KD_H];
    uint32_t s = 77;
    for (int round = 0; round < 40; round++) {
        kd_damage d;
        kd_damage_clear(&d);
        memset(want, 0, sizeof want);
        memset(got, 0, sizeof got);
        int n = kd_rand_range(&s, 1, 40);
        for (int i = 0; i < n; i++) {
            kd_rect r = kd_rect_make(kd_rand_range(&s, -20, 330), kd_rand_range(&s, -20, 210),
                                     kd_rand_range(&s, 1, 40), kd_rand_range(&s, 1, 30));
            kd_damage_add(&d, r);
            cover(want, &r, 1, 1);
        }
        CHECK(d.n <= KD_DAMAGE_MAX);
        cover(got, d.r, d.n, 1);
        for (int i = 0; i < KD_W * KD_H; i++)
            if (want[i]) CHECK(got[i]);
    }
}

static void test_region_subtract_exact(void) {
    static uint8_t want[KD_W * KD_H], got[KD_W * KD_H];
    uint32_t s = 5;
    for (int round = 0; round < 200; round++) {
        kd_rect a = kd_rect_make(kd_rand_range(&s, 0, 200), kd_rand_range(&s, 0, 120),
                                 kd_rand_range(&s, 1, 120), kd_rand_range(&s, 1, 80));
        kd_region g;
        kd_region_init(&g, a);
        memset(want, 0, sizeof want);
        cover(want, &a, 1, 1);
        int cuts = kd_rand_range(&s, 1, 8);
        for (int c = 0; c < cuts; c++) {
            kd_rect cut = kd_rect_make(kd_rand_range(&s, -10, 300), kd_rand_range(&s, -10, 190),
                                       kd_rand_range(&s, 1, 80), kd_rand_range(&s, 1, 60));
            kd_region_subtract(&g, cut);
            for (int y = 0; y < KD_H; y++)
                for (int x = 0; x < KD_W; x++)
                    if (kd_rect_has_point(cut, x, y)) want[y * KD_W + x] = 0;
        }
        memset(got, 0, sizeof got);
        cover(got, g.r, g.n, 1);
        for (int i = 0; i < KD_W * KD_H; i++) {
            if (g.overflow) CHECK(!want[i] || got[i]);
            else CHECK_EQ(got[i], want[i]);   // exact and disjoint (no 2s)
        }
    }
}

static void test_sprite_layout_and_hex(void) {
    kd_sprite sp;
    memset(&sp, 0, sizeof sp);
    CHECK(kd_sprite_set(&sp, 0, 0, 0xA));
    CHECK(!kd_sprite_set(&sp, 0, 0, 0xA));       // unchanged
    CHECK(kd_sprite_set(&sp, 1, 0, 0x5));
    CHECK(kd_sprite_set(&sp, 8, 0, 0x1));        // top-right tile
    CHECK(kd_sprite_set(&sp, 0, 8, 0x2));        // bottom-left tile
    CHECK(kd_sprite_set(&sp, 15, 15, 0x3));      // bottom-right tile, last nibble
    CHECK(!kd_sprite_set(&sp, 16, 0, 1));
    CHECK(!kd_sprite_set(&sp, 0, 0, 16));
    CHECK_EQ(sp.data[0], 0xA5);
    CHECK_EQ(sp.data[32], 0x10);
    CHECK_EQ(sp.data[64], 0x20);
    CHECK_EQ(sp.data[127], 0x03);
    uint32_t s = 11;
    for (int i = 0; i < 300; i++) kd_sprite_set(&sp, kd_rand_range(&s, 0, 15), kd_rand_range(&s, 0, 15), kd_rand_range(&s, 0, 15));
    char hex[KD_SPRITE_HEX + 1];
    kd_sprite_export_hex(&sp, hex);
    CHECK_EQ(strlen(hex), 256);
    kd_sprite back;
    memset(&back, 0, sizeof back);
    int changed = -1;
    CHECK(kd_sprite_import_hex(&back, hex, &changed));
    CHECK(memcmp(&back, &sp, sizeof sp) == 0);
    CHECK(changed > 0);
    CHECK(kd_sprite_import_hex(&back, hex, &changed));
    CHECK_EQ(changed, 0);
    char bad[KD_SPRITE_HEX + 2];
    memcpy(bad, hex, sizeof hex);
    bad[10] = 'g';
    CHECK(!kd_sprite_import_hex(&back, bad, NULL));
    bad[10] = hex[10];
    bad[255] = 0;
    CHECK(!kd_sprite_import_hex(&back, bad, NULL));
    memcpy(bad, hex, 256);
    bad[256] = '0';
    bad[257] = 0;
    CHECK(!kd_sprite_import_hex(&back, bad, NULL));
    CHECK(memcmp(&back, &sp, sizeof sp) == 0);
    // Blitting the sprite tile-aligned at zoom 1 produces the same four patterns.
    kd_fb_init(&fb, 0);
    kd_fb_blit_tile4(&fb, 8, 8, sp.data, 16, 16, 1, KD_NO_KEY);
    uint8_t tile[32];
    const unsigned tiles[4] = {41, 42, 81, 82};
    for (int t = 0; t < 4; t++) {
        kd_tile4_pack_tile(&fb, tiles[t], tile);
        CHECK(memcmp(tile, sp.data + t * 32, 32) == 0);
    }
    for (int y = 0; y < 16; y++)
        for (int x = 0; x < 16; x++) CHECK_EQ(kd_fb_get(&fb, 8 + x, 8 + y), kd_sprite_get(&sp, x, y));
}

static void test_font_and_art(void) {
    kd_fb_init(&fb, 2);
    int end = kd_text(&fb, &kd_font_system, 4, 4, "Ag~", 1, KD_NO_KEY);
    CHECK_EQ(end, 4 + 3 * 8);
    CHECK_EQ(kd_text_width(&kd_font_small, "README.TXT"), 40);
    // 'A' row 0 from the Misaki full-width glyph is 0x10 (column 3).
    CHECK_EQ(kd_fb_get(&fb, 4 + 3, 4), 1);
    CHECK_EQ(kd_fb_get(&fb, 4 + 2, 4), 2);
    const kd_art *arts[] = {&kd_art_cursor, &kd_art_folder, &kd_art_file, &kd_art_drive,
                            &kd_art_trash, &kd_art_studio, &kd_art_app, &kd_art_text};
    for (unsigned i = 0; i < sizeof arts / sizeof arts[0]; i++)
        for (int y = 0; y < arts[i]->h; y++) CHECK_EQ(strlen(arts[i]->rows[y]), arts[i]->w);
}

const kd_test_case kd_raster_tests[] = {
    {"pack_unpack", test_pack_unpack},
    {"primitives_vs_reference", test_random_primitives_vs_reference},
    {"clip_all_edges", test_clip_all_edges},
    {"dirty_tiles_exact", test_dirty_is_exact},
    {"tile4_layout", test_tile4_layout},
#ifdef KD_HAVE_TILE_FB
    {"tile4_matches_existing_tile_fb", test_tile4_matches_existing_tile_fb},
#endif
    {"tile4_flush", test_tile4_flush},
    {"kagura_320x240_placement", test_kagura_placement},
    {"damage_merge_rules", test_damage_merge_rules},
    {"damage_coverage", test_damage_coverage_property},
    {"region_subtract_exact", test_region_subtract_exact},
    {"sprite_layout_hex", test_sprite_layout_and_hex},
    {"font_and_art", test_font_and_art},
    {NULL, NULL},
};
