// SPDX-License-Identifier: Apache-2.0
// Tests of the retained layer (kagura_desktop/kdm.c) without MicroPython:
// handle lifetimes, atomic failures, pool exhaustion, text compaction,
// minimal invalidation, events, and random sequences after which the
// incremental frame must equal a full recomposition.
#include <string.h>

#include "kd_test.h"
#include "kdm.h"

int kd_test_failed;
int kd_test_quiet;

void kd_test_fail(const char *file, int line, const char *what) {
    kd_test_failed++;
    if (!kd_test_quiet) fprintf(stderr, "  FAIL %s:%d: %s\n", file, line, what);
}

static kdm M;
static uint8_t mirror[KD_TILE4_TOTAL], packed[KD_TILE4_TOTAL];
static uint32_t now;

static bool to_mirror(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    (void)ctx;
    memcpy(mirror + first * KD_TILE4_BYTES, data, count * KD_TILE4_BYTES);
    return true;
}

static int present(void) { return kdm_present(&M, to_mirror, NULL, NULL); }

static uint32_t fb_crc(void) { return kdm_crc32(0, M.desk.fb.px, KD_FB_BYTES); }

static void feed(uint8_t type, int x, int y, uint8_t key, char ch) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.button = KD_BUTTON_LEFT;
    e.x = (int16_t)x;
    e.y = (int16_t)y;
    e.key = key;
    e.ch = ch;
    e.time_ms = now += 500;
    kdm_feed(&M, &e);
}

static void click(int x, int y) {
    feed(KD_EV_POINTER_DOWN, x, y, 0, 0);
    feed(KD_EV_POINTER_UP, x, y, 0, 0);
}

static void drain(void) {
    kdm_event e;
    while (kdm_peek(&M, &e)) kdm_drop(&M);
}

// A full recomposition must not change a single tile: the incremental
// frame already equals what the windows' content says.
static bool equals_full_redraw(void) {
    kd_desktop_invalidate(&M.desk, kd_rect_make(0, 0, KD_W, KD_H));
    kd_desktop_render(&M.desk);
    return kd_fb_dirty_count(&M.desk.fb) == 0;
}

static void t_window_lifetime(void) {
    kdm_init(&M, NULL);
    uint32_t gen = M.generation;
    int a = kdm_window_open(&M, "A", kd_rect_make(10, 20, 100, 80), KD_WF_CLOSE | KD_WF_MOVE, 2);
    int b = kdm_window_open(&M, "B", kd_rect_make(60, 40, 100, 80), KD_WF_CLOSE | KD_WF_MOVE, 2);
    CHECK(a == 0 && b == 1);
    uint32_t sa = M.win[a].serial, sb = M.win[b].serial;
    CHECK(sa != sb);
    CHECK_EQ(kdm_window_check(&M, a, sa), KDM_OK);
    drain();
    CHECK_EQ(kdm_window_close(&M, a), KDM_OK);
    kdm_event e;
    CHECK(!kdm_peek(&M, &e) || e.ev.type != KDM_EV_CLOSE);   // the script asked: no CLOSE event
    CHECK_EQ(kdm_window_check(&M, a, sa), KDM_ESTALE);
    CHECK_EQ(kdm_add_fill(&M, a, 0, 0, 4, 4, 1), KDM_ESTALE);
    CHECK_EQ(kdm_window_close(&M, a), KDM_ESTALE);
    int c = kdm_window_open(&M, "C", kd_rect_make(0, 20, 100, 80), KD_WF_CLOSE, 2);
    CHECK_EQ(c, a);                                          // slot reused...
    CHECK_EQ(kdm_window_check(&M, a, sa), KDM_ESTALE);       // ...the old handle stays dead
    CHECK_EQ(kdm_window_check(&M, c, M.win[c].serial), KDM_OK);
    kdm_init(&M, NULL);
    CHECK_EQ(M.generation, gen + 1);
    CHECK_EQ(kdm_window_check(&M, b, sb), KDM_ESTALE);
    CHECK(M.next_serial > sb);                               // serials never repeat
}

static void t_window_slots_full(void) {
    kdm_init(&M, NULL);
    for (int i = 0; i < KD_MAX_WINDOWS; i++)
        CHECK_EQ(kdm_window_open(&M, "W", kd_rect_make(i * 8, 20 + i * 8, 80, 60), 0, 2), i);
    CHECK_EQ(kdm_window_open(&M, "X", kd_rect_make(0, 20, 80, 60), 0, 2), KDM_ENOWIN);
    CHECK_EQ(M.desk.zn, KD_MAX_WINDOWS);
    CHECK_EQ(kdm_window_open(&M, "bad", kd_rect_make(0, 20, 10, 60), 0, 2), KDM_EINVAL);
}

static void t_item_pool_full_is_atomic(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(0, 20, 200, 150), 0, 2);
    int n = 0;
    while (kdm_add_fill(&M, w, n % 190, n % 130, 4, 4, (uint8_t)(n % 16)) >= 0) n++;
    CHECK_EQ(n, KDM_MAX_ITEMS);
    present();
    uint32_t crc = fb_crc();
    kdm_stats before = M.stats;
    int16_t q[8] = {0, 0, 8, 8, 10, 10, 8, 8};
    CHECK_EQ(kdm_add_fill(&M, w, 0, 0, 8, 8, 3), KDM_ENOITEM);
    CHECK_EQ(kdm_add_text(&M, w, 0, 0, "x", 1, 1, -1, 0), KDM_ENOITEM);
    CHECK_EQ(kdm_add_fills(&M, w, q, 2, 3), KDM_ENOITEM);
    CHECK_EQ(M.desk.damage.n, 0);                            // nothing invalidated
    CHECK_EQ(M.stats.items, before.items);
    CHECK_EQ(M.stats.text, before.text);
    CHECK_EQ(present(), 0);
    CHECK_EQ(fb_crc(), crc);
    // Batched add: all or none.
    kdm_item_remove(&M, w, 0 | M.items[0].serial << KDM_ITEM_BITS);
    CHECK_EQ(kdm_add_fills(&M, w, q, 2, 3), KDM_ENOITEM);
    CHECK_EQ(M.stats.items, KDM_MAX_ITEMS - 1);
    CHECK_EQ(kdm_add_fills(&M, w, q, 1, 3), 1);
    CHECK_EQ(M.stats.items, KDM_MAX_ITEMS);
}

static void t_invalid_arguments(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(0, 20, 200, 150), 0, 2);
    present();
    CHECK_EQ(kdm_add_fill(&M, w, 0, 0, -1, 4, 1), KDM_EINVAL);
    CHECK_EQ(kdm_add_fill(&M, w, 0, 0, 4, 4, 16), KDM_EINVAL);
    CHECK_EQ(kdm_add_text(&M, w, 0, 0, "a\0b", 3, 1, -1, 0), KDM_EINVAL);
    CHECK_EQ(kdm_add_text(&M, w, 0, 0, "abc", 3, 1, -1, 2), KDM_EINVAL);
    char long_text[KDM_TEXT_MAX + 2];
    memset(long_text, 'x', sizeof long_text);
    CHECK_EQ(kdm_add_text(&M, w, 0, 0, long_text, sizeof long_text, 1, -1, 0), KDM_EINVAL);
    CHECK_EQ(kdm_add_sprite(&M, w, 0, 0, 0, 1, -1), KDM_ESTALE);   // no such sprite
    int s = kdm_sprite_alloc(&M, NULL);
    CHECK_EQ(kdm_add_sprite(&M, w, 0, 0, s, 0, -1), KDM_EINVAL);
    CHECK_EQ(kdm_add_sprite(&M, w, 0, 0, s, 17, -1), KDM_EINVAL);
    CHECK_EQ(kdm_sprite_set(&M, s, 16, 0, 1), KDM_EINVAL);
    uint8_t bad[] = {0, 0, 1, 3, 3, 16};
    CHECK_EQ(kdm_sprite_set_many(&M, s, bad, 2), KDM_EINVAL);
    CHECK_EQ(kd_sprite_get(&M.sprites[s].px, 0, 0), 0);   // the valid first triple was not applied
    CHECK_EQ(M.stats.items, 0);
    CHECK_EQ(M.desk.damage.n, 0);
}

static void t_stale_item_ids(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(0, 20, 200, 150), 0, 2);
    int v = kdm_window_open(&M, "V", kd_rect_make(100, 60, 200, 120), 0, 2);
    int id = kdm_add_text(&M, w, 4, 4, "abc", 3, 1, -1, 0);
    CHECK(id >= 0);
    CHECK_EQ(kdm_item_set_text(&M, v, id, "x", 1), KDM_ESTALE);   // another window's item
    CHECK_EQ(kdm_item_remove(&M, w, id), KDM_OK);
    CHECK_EQ(kdm_item_remove(&M, w, id), KDM_ESTALE);
    int id2 = kdm_add_text(&M, w, 4, 4, "abc", 3, 1, -1, 0);
    CHECK_EQ(id2 & ((1 << KDM_ITEM_BITS) - 1), id & ((1 << KDM_ITEM_BITS) - 1));   // same record...
    CHECK(id2 != id);
    CHECK_EQ(kdm_item_set_text(&M, w, id, "x", 1), KDM_ESTALE);   // ...old id still dead
    CHECK_EQ(kdm_item_set_text(&M, w, id2, "x", 1), KDM_OK);
    CHECK_EQ(kdm_item_set_text(&M, w, -5, "x", 1), KDM_ESTALE);
    CHECK_EQ(kdm_item_set_color(&M, w, id2, 7), KDM_OK);
    kdm_window_close(&M, w);
    CHECK_EQ(M.stats.items, 0);   // closing frees the window's records and text
    CHECK_EQ(M.stats.text, 0);
}

static void t_text_compaction(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(0, 12, 320, 188), 0, 2);
    char s[32];
    int ids[200], n = 0, rc;
    for (;;) {
        int len = snprintf(s, sizeof s, "text item %03d.....", n);
        rc = kdm_add_text(&M, w, (n % 3) * 100, (n / 3) % 20 * 8, s, (size_t)len, 1, -1, 0);
        if (rc < 0) break;
        ids[n++] = rc;
    }
    CHECK_EQ(rc, KDM_ENOTEXT);
    CHECK(n > 50);
    uint16_t text = M.stats.text;
    CHECK_EQ(kdm_item_set_text(&M, w, ids[0], "a much longer replacement", 25), KDM_ENOTEXT);
    CHECK_EQ(M.stats.text, text);
    for (int i = 0; i < n; i += 2) CHECK_EQ(kdm_item_remove(&M, w, ids[i]), KDM_OK);
    uint32_t compactions = M.stats.compactions;
    for (int i = 0; i < 20; i++) {
        int len = snprintf(s, sizeof s, "new %02d", i);
        CHECK(kdm_add_text(&M, w, 4, i * 8, s, (size_t)len, 6, 2, i & 1) >= 0);
    }
    for (int i = 1; i < n; i += 4) {
        int len = snprintf(s, sizeof s, "changed %03d", i);
        CHECK_EQ(kdm_item_set_text(&M, w, ids[i], s, (size_t)len), KDM_OK);
    }
    CHECK(M.stats.compactions > compactions);
    present();
    uint32_t crc = fb_crc();
    CHECK(equals_full_redraw());
    // Rebuild the same list without churn: the strings must have survived.
    kdm_init(&M, NULL);
    w = kdm_window_open(&M, "W", kd_rect_make(0, 12, 320, 188), 0, 2);
    for (int i = 1; i < n; i += 2) {
        int len = (i - 1) % 4 == 0 ? snprintf(s, sizeof s, "changed %03d", i) : snprintf(s, sizeof s, "text item %03d.....", i);
        kdm_add_text(&M, w, (i % 3) * 100, (i / 3) % 20 * 8, s, (size_t)len, 1, -1, 0);
    }
    for (int i = 0; i < 20; i++) {
        int len = snprintf(s, sizeof s, "new %02d", i);
        kdm_add_text(&M, w, 4, i * 8, s, (size_t)len, 6, 2, i & 1);
    }
    present();
    CHECK_EQ(fb_crc(), crc);
}

// Changing one sprite pixel exports only the tiles of its zoomed blocks;
// changing a label exports only the changed glyph cells.
static void t_minimal_updates(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(16, 24, 200, 150), 0, 3);
    int s = kdm_sprite_alloc(&M, NULL);
    kdm_add_sprite(&M, w, 8, 8, s, 8, -1);    // one pixel is an 8x8 block: up to 4 tiles
    kdm_add_sprite(&M, w, 150, 8, s, 1, -1);
    int t = kdm_add_text(&M, w, 0, 136, "Hello", 5, 1, 2, 0);
    present();
    CHECK_EQ(kdm_sprite_set(&M, s, 5, 5, 0), 0);   // unchanged pixel: nothing to do
    CHECK_EQ(present(), 0);
    CHECK_EQ(kdm_sprite_set(&M, s, 5, 5, 9), 1);
    int tiles = present();
    CHECK(tiles >= 2 && tiles <= 5);              // one 8x8 block (up to 4 tiles) + one 1x1 pixel
    CHECK_EQ(kdm_item_set_text(&M, w, t, "Help!", 5), KDM_OK);
    tiles = present();
    CHECK(tiles >= 2 && tiles <= 4);              // two glyph cells
    CHECK(equals_full_redraw());
    CHECK_EQ(kdm_item_set_text(&M, w, t, "He", 2), KDM_OK);   // shorter: freed cells are redrawn
    present();
    CHECK(equals_full_redraw());
}

// A line graph across a 4x2 grid of sprites (64x32 pixels), drawn in C.
static int trace_px(const int *sp, int x, int y) {
    return kd_sprite_get(&M.sprites[sp[(y / 16) * 4 + x / 16]].px, x % 16, y % 16);
}

// The picture kdm_sprite_trace must leave on a 64x32 canvas: an independent model.
static bool trace_matches(const int *sp, const int8_t *v, int n, int fg, int bg) {
    int prev = -1;
    for (int x = 0; x < 64; x++) {
        int val = v[x * n / 64];
        if (val < -127) val = -127;
        int y = 16 - val * 15 / 127;
        int a = prev < 0 ? y : prev, lo = a < y ? a : y, hi = a < y ? y : a;
        prev = y;
        for (int yy = 0; yy < 32; yy++)
            if (trace_px(sp, x, yy) != (yy >= lo && yy <= hi ? fg : bg)) return false;
    }
    return true;
}

static void t_sprite_trace(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(16, 24, 200, 150), 0, 2);
    int sp[8];
    for (int i = 0; i < 8; i++) {
        sp[i] = kdm_sprite_alloc(&M, NULL);
        kdm_add_sprite(&M, w, 10 + (i % 4) * 16, 10 + (i / 4) * 16, sp[i], 1, -1);
    }
    present();
    int8_t v[64];
    memset(v, 0, sizeof v);
    CHECK(kdm_sprite_trace(&M, sp, 4, 2, v, 64, 9, 2) > 0);
    for (int x = 0; x < 64; x++)                       // silence: the middle row, nothing else
        for (int y = 0; y < 32; y++) CHECK_EQ(trace_px(sp, x, y), y == 16 ? 9 : 2);
    present();
    CHECK(equals_full_redraw());
    CHECK_EQ(kdm_sprite_trace(&M, sp, 4, 2, v, 64, 9, 2), 0);   // the same picture: nothing changes
    CHECK_EQ(present(), 0);
    // A square wave: top for the first half, bottom for the second, joined.
    int8_t sq[2] = {127, -127};
    CHECK(kdm_sprite_trace(&M, sp, 4, 2, sq, 2, 9, 2) > 0);   // 2 values over 64 columns
    CHECK(trace_matches(sp, sq, 2, 9, 2));
    CHECK_EQ(trace_px(sp, 0, 1), 9);
    CHECK_EQ(trace_px(sp, 31, 1), 9);
    CHECK_EQ(trace_px(sp, 31, 2), 2);
    for (int y = 1; y <= 31; y++) CHECK_EQ(trace_px(sp, 32, y), 9);   // the edge, joined
    CHECK_EQ(trace_px(sp, 63, 31), 9);
    CHECK_EQ(trace_px(sp, 63, 16), 2);
    CHECK_EQ(trace_px(sp, 10, 16), 2);                 // the old line is gone
    present();
    CHECK(equals_full_redraw());
    // A small change redraws a few tiles, not the whole graph.
    int8_t sq2[64];
    for (int i = 0; i < 64; i++) sq2[i] = i < 32 ? 127 : -127;
    kdm_sprite_trace(&M, sp, 4, 2, sq2, 64, 9, 2);
    CHECK(trace_matches(sp, sq2, 64, 9, 2));
    present();
    sq2[40] = -120;                                  // a few pixels: changed one by one
    CHECK(kdm_sprite_trace(&M, sp, 4, 2, sq2, 64, 9, 2) <= 16);
    CHECK(trace_matches(sp, sq2, 64, 9, 2));
    int tiles = present();
    CHECK(tiles >= 1 && tiles <= 4);
    CHECK(equals_full_redraw());
    uint32_t seed = 7;
    int8_t rv[64];
    for (int round = 0; round < 300; round++) {
        for (int i = 0; i < 64; i++) {
            seed = seed * 1664525u + 1013904223u;
            if (round % 3 || (seed >> 28) == 0) rv[i] = (int8_t)(seed >> 24);   // often, change few values
        }
        kdm_sprite_trace(&M, sp, 4, 2, rv, 64, 9, 2);
        CHECK(trace_matches(sp, rv, 64, 9, 2));
    }
    present();
    CHECK(equals_full_redraw());
    // Errors change nothing.
    kd_sprite before[8];
    for (int i = 0; i < 8; i++) before[i] = M.sprites[sp[i]].px;
    int dup[8] = {sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6], sp[0]};
    CHECK_EQ(kdm_sprite_trace(&M, dup, 4, 2, v, 64, 9, 2), KDM_EINVAL);
    CHECK_EQ(kdm_sprite_trace(&M, sp, 4, 3, v, 64, 9, 2), KDM_EINVAL);   // 12 sprites
    CHECK_EQ(kdm_sprite_trace(&M, sp, 4, 2, v, 64, 16, 2), KDM_EINVAL);
    CHECK_EQ(kdm_sprite_trace(&M, sp, 4, 2, v, 0, 9, 2), KDM_EINVAL);
    kdm_sprite_free(&M, sp[5]);
    CHECK_EQ(kdm_sprite_trace(&M, sp, 4, 2, v, 64, 9, 2), KDM_ESTALE);
    for (int i = 0; i < 8; i++)
        if (i != 5) CHECK(!memcmp(&before[i], &M.sprites[sp[i]].px, sizeof before[i]));
    // One row of sprites works too (64x16).
    CHECK(kdm_sprite_trace(&M, sp, 4, 1, v, 64, 1, 0) > 0);
    CHECK_EQ(kd_sprite_get(&M.sprites[sp[0]].px, 0, 8), 1);
}

static void t_events(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(10, 20, 100, 80), KD_WF_CLOSE | KD_WF_MOVE, 2);
    kdm_event e;
    CHECK(kdm_peek(&M, &e) && e.ev.type == KD_EV_FOCUS && e.win == w && e.serial == M.win[w].serial);
    drain();
    for (int i = 0; i < KDM_EVENTS + 5; i++) feed(KD_EV_KEY, 0, 0, KD_KEY_CHAR, (char)('a' + i % 26));
    CHECK_EQ(M.ring_count, KDM_EVENTS);
    CHECK_EQ(M.stats.dropped, 5);
    CHECK(kdm_peek(&M, &e) && e.ev.ch == 'a');   // oldest first; the newest were dropped
    drain();
    kd_rect work = kd_window_work(&M.desk.win[w]);
    click(work.x + 3, work.y + 4);
    CHECK(kdm_peek(&M, &e) && e.ev.type == KD_EV_POINTER_DOWN && e.ev.x == 3 && e.ev.y == 4);
    drain();
    uint32_t serial = M.win[w].serial;
    kdm_add_text(&M, w, 0, 0, "abc", 3, 1, -1, 0);
    kd_rect f = kd_window_frame(&M.desk.win[w]);
    click(f.x + 4, f.y + 4);   // close box
    CHECK(kdm_peek(&M, &e) && e.ev.type == KDM_EV_CLOSE && e.win == w && e.serial == serial);
    CHECK_EQ(kdm_window_check(&M, w, serial), KDM_ESTALE);
    CHECK_EQ(M.stats.items, 0);
    CHECK_EQ(M.stats.text, 0);
}

static void t_menus(void) {
    kdm_menu_def def = {2, {"Desk", "Window"}, {{"About", "-", "Quit"}, {"Close", "Cycle"}}, {3, 2}};
    CHECK_EQ(kdm_init(&M, &def), KDM_OK);
    drain();
    feed(KD_EV_POINTER_DOWN, 60, 4, 0, 0);    // Window: title x 56
    feed(KD_EV_POINTER_MOVE, 62, 25, 0, 0);
    feed(KD_EV_POINTER_UP, 62, 25, 0, 0);     // second item
    kdm_event e;
    CHECK(kdm_peek(&M, &e) && e.ev.type == KDM_EV_MENU && e.ev.key == 1 && e.ev.ch == 1 && e.win == -1);
    kdm_menu_def big = {1, {"M"}, {{0}}, {KDM_MENU_ITEMS + 1}};
    CHECK_EQ(kdm_init(&M, &big), KDM_ENOMENU);
    CHECK(M.menus[0].title == NULL);          // still a working desktop, without menus
}

static void t_sprite_free_removes_records(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(10, 20, 200, 120), 0, 2);
    int s = kdm_sprite_alloc(&M, NULL);
    uint32_t serial = M.sprites[s].serial;
    kdm_sprite_fill(&M, s, 7);
    kdm_add_sprite(&M, w, 0, 0, s, 4, -1);
    kdm_add_sprite(&M, w, 80, 0, s, 1, 0);
    kdm_add_fill(&M, w, 0, 80, 20, 10, 1);
    present();
    CHECK_EQ(kdm_sprite_free(&M, s), KDM_OK);
    CHECK_EQ(M.stats.items, 1);
    CHECK_EQ(kdm_sprite_check(&M, s, serial), KDM_ESTALE);
    CHECK_EQ(kdm_sprite_set(&M, s, 0, 0, 1), KDM_ESTALE);
    present();
    CHECK(equals_full_redraw());
    for (int i = 0; i < KDM_MAX_SPRITES; i++) CHECK(kdm_sprite_alloc(&M, NULL) >= 0);
    CHECK_EQ(kdm_sprite_alloc(&M, NULL), KDM_ENOSPRITE);
}

// Random scripts of every kind of call; after each present the mirror must
// equal the packed screen and a full recomposition must change nothing.
static void random_run(uint32_t seed) {
    uint32_t r = seed;
    kdm_menu_def def = {1, {"Desk"}, {{"One", "Two"}}, {2}};
    kdm_init(&M, &def);
    memset(mirror, 0, sizeof mirror);
    int ids[KD_MAX_WINDOWS][24];
    int nid[KD_MAX_WINDOWS] = {0};
    int sprite = kdm_sprite_alloc(&M, NULL);
    static const char *const words[] = {"", "a", "Hello", "MicroPython", "kd", "0123456789", "Window title"};
    for (int step = 0; step < 700; step++) {
        int slot = kd_rand_range(&r, 0, KD_MAX_WINDOWS - 1);
        bool open = M.win[slot].open;
        int kind = kd_rand_range(&r, 0, 17);
        int x = kd_rand_range(&r, -20, 200), y = kd_rand_range(&r, -20, 140);
        uint8_t c = (uint8_t)kd_rand_range(&r, 0, 15);
        const char *word = words[kd_rand(&r) % 7];
        int id = open && nid[slot] ? ids[slot][kd_rand(&r) % nid[slot]] : -1;
        int rc = 0;
        switch (kind) {
        case 0:
            if (!open) {
                rc = kdm_window_open(&M, word, kd_rect_make(x, y + 12, kd_rand_range(&r, 32, 220), kd_rand_range(&r, 24, 150)),
                                     KD_WF_CLOSE | KD_WF_MOVE, c);
                if (rc >= 0) nid[rc] = 0;
            }
            break;
        case 1: if (open && kd_rand(&r) % 3 == 0) kdm_window_close(&M, slot); break;
        case 2: kdm_window_activate(&M, slot); break;
        case 3: kdm_window_move(&M, slot, x, y); break;
        case 4: case 5: rc = kdm_add_fill(&M, slot, x / 2, y / 2, kd_rand_range(&r, 0, 80), kd_rand_range(&r, 0, 60), c); break;
        case 6: rc = kdm_add_rect(&M, slot, x / 2, y / 2, kd_rand_range(&r, 0, 80), kd_rand_range(&r, 0, 60), c); break;
        case 7: rc = kdm_add_text(&M, slot, x / 2, y / 2, word, strlen(word), c, (int)(kd_rand(&r) % 17) - 1, (int)(kd_rand(&r) % 2)); break;
        case 8: rc = kdm_add_sprite(&M, slot, x / 2, y / 2, sprite, kd_rand_range(&r, 1, 4), (int)(kd_rand(&r) % 3) - 1); break;
        case 9: rc = kdm_add_button(&M, slot, x / 2, y / 2, kd_rand_range(&r, 16, 60), 14, word, strlen(word), c & 3); break;
        case 10: if (id >= 0) kdm_item_set_text(&M, slot, id, word, strlen(word)); break;
        case 11: if (id >= 0) kdm_item_move(&M, slot, id, x / 2, y / 2); break;
        case 12: if (id >= 0) kdm_item_set_color(&M, slot, id, c); break;
        case 13: if (id >= 0 && kdm_item_remove(&M, slot, id) == KDM_OK) {
                for (int k = 0; k < nid[slot]; k++)
                    if (ids[slot][k] == id) ids[slot][k] = ids[slot][--nid[slot]];
            }
            break;
        case 14: kdm_sprite_set(&M, sprite, kd_rand_range(&r, 0, 15), kd_rand_range(&r, 0, 15), c); break;
        case 15:
            if (kd_rand(&r) % 8 == 0) kdm_window_clear(&M, slot, c), nid[slot] = 0;
            else kdm_sprite_fill(&M, sprite, c);
            break;
        case 16: feed((uint8_t)kd_rand_range(&r, KD_EV_POINTER_MOVE, KD_EV_POINTER_UP), x + 60, y + 50, 0, 0); break;
        default: feed(KD_EV_KEY, 0, 0, (uint8_t)kd_rand_range(&r, KD_KEY_CHAR, KD_KEY_F10), 'q'); break;
        }
        if (kind >= 4 && kind <= 9 && rc >= 0 && open && nid[slot] < 24) ids[slot][nid[slot]++] = rc;
        drain();   // closed windows lose their ids
        for (int s = 0; s < KD_MAX_WINDOWS; s++)
            if (!M.win[s].open) nid[s] = 0;
        present();
        kd_tile4_pack_all(&M.desk.fb, packed);
        if (memcmp(packed, mirror, sizeof packed) != 0 || !equals_full_redraw()) {
            if (!kd_test_quiet)
                fprintf(stderr, "  seed %lu step %d op %d slot %d rc %d\n", (unsigned long)seed, step, kind, slot, rc);
            CHECK(false);
        }
    }
}

static void t_random_seed_1(void) { random_run(1); }
static void t_random_seed_2(void) { random_run(0xC0FFEE); }
static void t_random_seed_3(void) { random_run(20261102); }

// ---- fields, focus and keyboard navigation ----

static void key(uint8_t k, char ch, uint8_t mods) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = KD_EV_KEY;
    e.key = k;
    e.ch = ch;
    e.mods = mods;
    e.time_ms = now += 50;
    kdm_feed(&M, &e);
}

static void type(const char *s) {
    for (; *s; s++) key(KD_KEY_CHAR, *s, 0);
}

static bool field_is(int w, int id, const char *s) {
    const char *t;
    size_t n;
    return kdm_item_get_text(&M, w, id, &t, &n) == KDM_OK && n == strlen(s) && !memcmp(t, s, n);
}

// Counts queued events of a type for record id (and drops everything).
static int count_events(int type, int id) {
    kdm_event e;
    int n = 0;
    while (kdm_peek(&M, &e)) {
        if (e.ev.type == type && (id < 0 || (int)e.ev.reserved == id)) n++;
        kdm_drop(&M);
    }
    return n;
}

static int px(int x, int y) { return kd_fb_get(&M.desk.fb, x, y); }

static void t_field_typing(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(16, 24, 200, 100), KD_WF_CLOSE | KD_WF_MOVE, 2);
    int f = kdm_add_field(&M, w, 8, 8, 100, "ab", 2, 0);
    CHECK(f >= 0);
    CHECK_EQ(kdm_focused(&M, w), f);   // the first focusable control takes the focus
    present();
    drain();
    kd_rect work = kd_window_work(&M.desk.win[w]);
    // Caret after "ab": column 8 + 2 + 16, on the padding row above the glyphs.
    CHECK_EQ(px(work.x + 26, work.y + 9), KD_C_BLACK);
    type("cd");
    CHECK(field_is(w, f, "abcd"));
    CHECK_EQ(count_events(KDM_EV_CHANGE, f), 2);
    int tiles = present();
    CHECK(tiles >= 1 && tiles <= 6);   // two glyph cells and the old and new caret columns
    CHECK_EQ(px(work.x + 26, work.y + 9), KD_C_WHITE);
    CHECK_EQ(px(work.x + 42, work.y + 9), KD_C_BLACK);
    CHECK(equals_full_redraw());
    CHECK_EQ(present(), 0);            // idle frame: nothing to send
    key(KD_KEY_BACKSPACE, 0, 0);
    key(KD_KEY_HOME, 0, 0);
    key(KD_KEY_DELETE, 0, 0);
    CHECK(field_is(w, f, "bc"));
    key(KD_KEY_END, 0, KD_MOD_SHIFT);  // select "bc"
    const kd_edit *e = kdm_field_editor(&M, w, f);
    CHECK(e && e->anchor == 0 && e->caret == 2);
    present();
    CHECK(equals_full_redraw());
    type("X");                          // replaces the selection
    CHECK(field_is(w, f, "X"));
    present();
    CHECK(equals_full_redraw());
    // Pure motions: the old caret must be erased.
    type("YZ");
    present();
    key(KD_KEY_HOME, 0, 0);
    CHECK(present() >= 1);
    CHECK(equals_full_redraw());
    key(KD_KEY_RIGHT, 0, 0);
    key(KD_KEY_END, 0, KD_MOD_SHIFT);
    present();
    CHECK(equals_full_redraw());
    key(KD_KEY_LEFT, 0, 0);             // collapses the selection to its start
    present();
    CHECK(equals_full_redraw());
    // Keys the field does not use are queued for the application.
    drain();
    key(KD_KEY_ESCAPE, 0, 0);
    key(KD_KEY_ENTER, 0, 0);
    key(KD_KEY_DOWN, 0, 0);
    key(KD_KEY_CHAR, 'c', KD_MOD_CTRL);   // Ctrl+C is never an editing key
    CHECK_EQ(count_events(KD_EV_KEY, -1), 4);
    CHECK(field_is(w, f, "XYZ"));
    // Programmatic changes do not queue CHANGE.
    CHECK_EQ(kdm_item_set_text(&M, w, f, "new", 3), KDM_OK);
    CHECK_EQ(count_events(KDM_EV_CHANGE, -1), 0);
    present();
    CHECK(equals_full_redraw());
}

static void t_field_utf8_input(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(16, 24, 200, 100), 0, 2);
    CHECK_EQ(kdm_text_input(&M, "x", 1), 0);   // no field: nothing takes the text
    int f = kdm_add_field(&M, w, 8, 8, 120, "", 0, 0);
    drain();
    CHECK_EQ(kdm_text_input(&M, "神楽", 6), 1);
    CHECK_EQ(kdm_text_input(&M, "!", 1), 1);
    CHECK(field_is(w, f, "神楽!"));
    CHECK_EQ(count_events(KDM_EV_CHANGE, f), 2);
    key(KD_KEY_LEFT, 0, 0);
    key(KD_KEY_LEFT, 0, 0);
    key(KD_KEY_BACKSPACE, 0, 0);       // removes 神, all three bytes
    CHECK(field_is(w, f, "楽!"));
    present();
    CHECK(equals_full_redraw());
    // Invalid input, line breaks and overflow change nothing.
    uint32_t crc = fb_crc();
    CHECK_EQ(kdm_text_input(&M, "\xE7\xA5", 2), KDM_EINVAL);
    CHECK_EQ(kdm_text_input(&M, "a\nb", 3), KDM_EINVAL);
    char big[KDM_FIELD_BYTES];
    memset(big, 'z', sizeof big);
    CHECK_EQ(kdm_text_input(&M, big, KDM_FIELD_BYTES - 4), KDM_ETOOLONG);   // 4 + 60 > 63
    CHECK_EQ(kdm_text_input(&M, big, KDM_FIELD_BYTES - 5), 1);              // exactly full
    CHECK_EQ(kdm_text_input(&M, "a", 1), KDM_ETOOLONG);
    type("q");                                                               // a full field ignores keys
    const char *t;
    size_t n;
    CHECK_EQ(kdm_item_get_text(&M, w, f, &t, &n), KDM_OK);
    CHECK_EQ(n, KDM_FIELD_BYTES - 1);
    CHECK(fb_crc() == crc);   // nothing rendered yet
    present();
    CHECK(equals_full_redraw());
    CHECK_EQ(kdm_item_set_text(&M, w, f, big, KDM_FIELD_BYTES), KDM_ETOOLONG);
    CHECK_EQ(kdm_item_set_text(&M, w, f, "\xFF", 1), KDM_EINVAL);
    CHECK_EQ(kdm_add_field(&M, w, 0, 30, 50, "a\r\n", 3, 0), KDM_EINVAL);
    CHECK_EQ(kdm_add_field(&M, w, 0, 30, 50, big, KDM_FIELD_BYTES, 0), KDM_ETOOLONG);
    CHECK_EQ(kdm_add_field(&M, w, 0, 30, 4, "", 0, 0), KDM_EINVAL);
    CHECK_EQ(kdm_add_field(&M, w, 0, 30, 50, "", 0, 2), KDM_EINVAL);
}

static void t_field_scrolling_and_clipping(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(40, 30, 120, 80), KD_WF_MOVE, 2);
    // 44 px: 39 caret columns, about four system-font characters.
    int f = kdm_add_field(&M, w, 4, 4, 44, "", 0, 0);
    // A second field runs past the right edge of the work area.
    int g = kdm_add_field(&M, w, 80, 30, 100, "clipped text", 12, 1);
    CHECK(f >= 0 && g >= 0);
    present();
    for (int i = 0; i < 12; i++) {
        key(KD_KEY_CHAR, (char)('a' + i), 0);
        present();
        CHECK(equals_full_redraw());
    }
    kdm_text_input(&M, "日本語", 9);
    present();
    CHECK(equals_full_redraw());
    const kdm_field *fd = &M.fields[M.items[f & ((1 << KDM_ITEM_BITS) - 1)].aux];
    int cx = kd_edit_x(&fd->ed, fd->ed.caret, NULL, NULL);   // scalars
    CHECK(cx == 15 && fd->scroll > 0);
    kd_rect work = kd_window_work(&M.desk.win[w]);
    // Scrolled so that the caret is in the last caret column (w - 5 = 39),
    // one pixel inside the right padding and border.
    CHECK_EQ(fd->scroll, 15 * 8 - 39);
    CHECK_EQ(px(work.x + 4 + 2 + 39, work.y + 5), KD_C_BLACK);
    CHECK_EQ(px(work.x + 4 + 44 - 1, work.y + 5), KD_C_BLACK);   // border
    CHECK_EQ(px(work.x + 4 + 44 - 2, work.y + 5), KD_C_WHITE);   // padding
    key(KD_KEY_HOME, 0, 0);
    present();
    CHECK_EQ(fd->scroll, 0);
    CHECK(equals_full_redraw());
    key(KD_KEY_END, 0, 0);
    while (fd->ed.len) key(KD_KEY_BACKSPACE, 0, 0);
    CHECK_EQ(fd->scroll, 0);   // no blank space left of the text
    present();
    CHECK(equals_full_redraw());
    // Nothing outside the window frame changed: the desk to the right is plain.
    kd_rect fr = kd_window_frame(&M.desk.win[w]);
    for (int y = fr.y; y < fr.y + fr.h; y++) CHECK_EQ(px(fr.x + fr.w + 1, y), KD_C_DESK);
    // Moving the window moves the clipped field with it.
    kdm_window_move(&M, w, 150, 100);
    present();
    CHECK(equals_full_redraw());
}

static void t_focus_navigation(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "Dialog", kd_rect_make(16, 24, 220, 120), KD_WF_CLOSE, 2);
    int a = kdm_add_field(&M, w, 8, 8, 100, "a", 1, 0);
    int b = kdm_add_field(&M, w, 8, 28, 100, "b", 1, 0);
    int ok = kdm_add_button(&M, w, 8, 60, 50, 16, "OK", 2, KD_BTN_DEFAULT);
    int cancel = kdm_add_button(&M, w, 70, 60, 50, 16, "Cancel", 6, 0);
    int plain = kdm_add_button(&M, w, 130, 60, 50, 16, "Plain", 5, 0);   // not focusable
    CHECK_EQ(kdm_item_set_focusable(&M, w, ok, true), KDM_OK);
    CHECK_EQ(kdm_item_set_focusable(&M, w, cancel, true), KDM_OK);
    CHECK_EQ(kdm_item_set_focusable(&M, w, a, true), KDM_EINVAL);   // fields always are
    CHECK_EQ(kdm_focused(&M, w), a);
    present();
    drain();
    key(KD_KEY_TAB, 0, 0);
    CHECK_EQ(kdm_focused(&M, w), b);
    key(KD_KEY_TAB, 0, 0);
    CHECK_EQ(kdm_focused(&M, w), ok);
    key(KD_KEY_TAB, 0, 0);
    CHECK_EQ(kdm_focused(&M, w), cancel);
    key(KD_KEY_TAB, 0, 0);
    CHECK_EQ(kdm_focused(&M, w), a);                 // wraps, skipping "Plain"
    key(KD_KEY_TAB, 0, KD_MOD_SHIFT);
    CHECK_EQ(kdm_focused(&M, w), cancel);
    CHECK_EQ(count_events(KD_EV_KEY, -1), 0);        // Tab is consumed
    present();
    CHECK(equals_full_redraw());
    // Enter or Space on a focused button activates it.
    key(KD_KEY_ENTER, 0, 0);
    key(KD_KEY_CHAR, ' ', 0);
    CHECK_EQ(count_events(KDM_EV_ACTIVATE, cancel), 2);
    // Enter in a field activates the default button.
    CHECK_EQ(kdm_focus(&M, w, b), KDM_OK);
    key(KD_KEY_ENTER, 0, 0);
    CHECK_EQ(count_events(KDM_EV_ACTIVATE, ok), 1);
    // A disabled default button is not activated: Enter is queued instead.
    kdm_item_set_flags(&M, w, ok, KD_BTN_DEFAULT | KD_BTN_DISABLED);
    key(KD_KEY_ENTER, 0, 0);
    CHECK_EQ(count_events(KD_EV_KEY, -1), 1);
    CHECK_EQ(kdm_focus(&M, w, plain), KDM_EINVAL);
    CHECK_EQ(kdm_focus(&M, w, -1), KDM_OK);
    CHECK_EQ(kdm_focused(&M, w), KDM_ENONE);
    // Removing the focused control passes the focus on.
    kdm_focus(&M, w, b);
    kdm_item_remove(&M, w, b);
    CHECK_EQ(kdm_focused(&M, w), ok);
    CHECK_EQ(kdm_focus(&M, w, b), KDM_ESTALE);
    present();
    CHECK(equals_full_redraw());
    // A click focuses a field and places the caret.
    kd_rect work = kd_window_work(&M.desk.win[w]);
    click(work.x + 8 + 2 + 4, work.y + 12);          // middle of "a": before it
    CHECK_EQ(kdm_focused(&M, w), a);
    CHECK_EQ(kdm_field_editor(&M, w, a)->caret, 0);
    present();
    CHECK(equals_full_redraw());
    // A window without focusable controls queues Tab, as before.
    int v = kdm_window_open(&M, "Plain", kd_rect_make(100, 100, 100, 60), 0, 2);
    kdm_add_text(&M, v, 0, 0, "x", 1, 1, -1, 0);
    drain();
    key(KD_KEY_TAB, 0, 0);
    kdm_event e;
    CHECK(kdm_peek(&M, &e) && e.ev.type == KD_EV_KEY && e.ev.key == KD_KEY_TAB && e.win == v);
}

static void t_keyboard_menus_and_windows(void) {
    kdm_menu_def def = {2, {"File", "Edit"}, {{"Open", "-", "Quit"}, {"Copy", "Paste"}}, {3, 2}};
    kdm_init(&M, &def);
    int w1 = kdm_window_open(&M, "One", kd_rect_make(10, 20, 150, 80), KD_WF_CLOSE | KD_WF_MOVE, 2);
    int f1 = kdm_add_field(&M, w1, 4, 4, 100, "", 0, 0);
    int w2 = kdm_window_open(&M, "Two", kd_rect_make(60, 60, 150, 80), KD_WF_CLOSE | KD_WF_MOVE, 2);
    int f2 = kdm_add_field(&M, w2, 4, 4, 100, "", 0, 0);
    present();
    drain();
    // F10, Right, Down, Enter: Edit > Paste, with the field untouched.
    key(KD_KEY_F10, 0, 0);
    type("zz");
    CHECK_EQ(kdm_text_input(&M, "x", 1), 0);         // menus open: no text input
    key(KD_KEY_RIGHT, 0, 0);
    key(KD_KEY_DOWN, 0, 0);
    key(KD_KEY_ENTER, 0, 0);
    kdm_event e;
    bool menu = false;
    while (kdm_peek(&M, &e)) {
        if (e.ev.type == KDM_EV_MENU) menu = e.ev.key == 1 && e.ev.ch == 1;
        kdm_drop(&M);
    }
    CHECK(menu);
    CHECK(field_is(w2, f2, ""));
    key(KD_KEY_F10, 0, 0);
    key(KD_KEY_ESCAPE, 0, 0);
    CHECK_EQ(M.desk.menu_open, -1);
    present();
    CHECK(equals_full_redraw());
    // F6 switches windows; typing follows the active window.
    type("2");
    key(KD_KEY_F6, 0, 0);
    CHECK(kd_window_is_active(&M.desk.win[w1]));
    type("1");
    kdm_text_input(&M, "一", 3);
    CHECK(field_is(w1, f1, "1一") && field_is(w2, f2, "2"));
    present();
    CHECK(equals_full_redraw());
    // The inactive window's field shows no caret.
    kd_rect work2 = kd_window_work(&M.desk.win[w2]);
    key(KD_KEY_F6, 0, 0);
    present();
    CHECK_EQ(px(work2.x + 4 + 2 + 8, work2.y + 5), KD_C_BLACK);
    key(KD_KEY_F6, 0, 0);
    present();
    CHECK_EQ(px(work2.x + 4 + 2 + 8, work2.y + 5), KD_C_WHITE);
    CHECK(equals_full_redraw());
    // Ctrl+W closes the active window; the focus goes to the other one.
    key(KD_KEY_CHAR, 'w', KD_MOD_CTRL);
    CHECK_EQ(kdm_item_get_text(&M, w1, f1, &(const char *){0}, &(size_t){0}), KDM_ESTALE);
    CHECK(kd_window_is_active(&M.desk.win[w2]));
    type("!");
    CHECK(field_is(w2, f2, "2!"));
    present();
    CHECK(equals_full_redraw());
    // Field slots are released with their window.
    kdm_window_close(&M, w2);
    int w3 = kdm_window_open(&M, "Three", kd_rect_make(10, 20, 150, 150), 0, 2);
    for (int i = 0; i < KDM_FIELDS; i++) CHECK(kdm_add_field(&M, w3, 0, i * 14, 60, "", 0, 0) >= 0);
    uint16_t items = M.stats.items;
    CHECK_EQ(kdm_add_field(&M, w3, 0, 0, 60, "", 0, 0), KDM_ENOFIELD);
    CHECK_EQ(M.stats.items, items);   // atomic
}

static void t_clipboard(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(16, 24, 200, 100), 0, 2);
    int f = kdm_add_field(&M, w, 8, 8, 150, "神楽 desk", 11, 0);
    int g = kdm_add_field(&M, w, 8, 30, 150, "", 0, 0);
    drain();
    key(KD_KEY_HOME, 0, 0);
    key(KD_KEY_RIGHT, 0, KD_MOD_SHIFT);
    key(KD_KEY_RIGHT, 0, KD_MOD_SHIFT);
    key(KD_KEY_INSERT, 0, KD_MOD_CTRL);              // copy 神楽
    CHECK(M.clip_len == 6 && !memcmp(M.clip, "神楽", 6));
    key(KD_KEY_DELETE, 0, KD_MOD_SHIFT);             // cut
    CHECK(field_is(w, f, " desk"));
    key(KD_KEY_TAB, 0, 0);
    key(KD_KEY_INSERT, 0, KD_MOD_SHIFT);             // paste into the second field
    key(KD_KEY_INSERT, 0, KD_MOD_SHIFT);
    CHECK(field_is(w, g, "神楽神楽"));
    key(KD_KEY_CHAR, 'a', KD_MOD_CTRL);              // select all
    CHECK_EQ(kdm_edit(&M, w, g, KDM_EDIT_CUT), 1);   // the menu path
    CHECK(field_is(w, g, "") && M.clip_len == 12);
    CHECK_EQ(kdm_edit(&M, w, g, KDM_EDIT_COPY), 0);  // nothing selected: clipboard kept
    CHECK_EQ(M.clip_len, 12);
    CHECK_EQ(kdm_edit(&M, w, g, KDM_EDIT_PASTE), 1);
    CHECK_EQ(kdm_edit(&M, w, g, 9), KDM_EINVAL);
    CHECK_EQ(kdm_set_clipboard(&M, "a\r\nb", 4), KDM_OK);
    CHECK(M.clip_len == 3 && !memcmp(M.clip, "a\nb", 3));
    CHECK_EQ(kdm_edit(&M, w, g, KDM_EDIT_PASTE), 0); // a line break does not fit a field
    CHECK_EQ(kdm_set_clipboard(&M, "\xC3", 1), KDM_EINVAL);
    present();
    CHECK(equals_full_redraw());
}

// Typing into a covered field sends nothing until the field is revealed.
static void t_field_hidden_updates(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "Below", kd_rect_make(20, 30, 160, 80), KD_WF_MOVE, 2);
    int f = kdm_add_field(&M, w, 8, 8, 120, "", 0, 0);
    int top = kdm_window_open(&M, "Above", kd_rect_make(10, 20, 200, 120), KD_WF_MOVE, 3);
    (void)top;
    present();
    CHECK_EQ(kdm_item_set_text(&M, w, f, "hidden 隠れ", 13), KDM_OK);
    CHECK_EQ(present(), 0);
    CHECK_EQ(kdm_window_activate(&M, w), KDM_OK);
    CHECK(present() > 0);
    CHECK(equals_full_redraw());
}

static void t_field_random(void) {
    uint32_t r = 4242;
    kdm_menu_def def = {1, {"M"}, {{"A", "B"}}, {2}};
    kdm_init(&M, &def);
    int w[3], f[3];
    for (int i = 0; i < 3; i++) {
        w[i] = kdm_window_open(&M, "W", kd_rect_make(10 + i * 40, 20 + i * 30, 160, 80), KD_WF_MOVE, 2);
        f[i] = kdm_add_field(&M, w[i], 4, 4 + i * 6, 90 + i * 20, "", 0, i == 2);
        kdm_add_button(&M, w[i], 4, 40, 40, 16, "B", 1, 0);
    }
    static const char *const words[] = {"a", "神", "楽", "é", "xyz", "😀", "日本語テキスト"};
    static const uint8_t keys[] = {KD_KEY_LEFT, KD_KEY_RIGHT, KD_KEY_HOME, KD_KEY_END, KD_KEY_BACKSPACE,
                                   KD_KEY_DELETE, KD_KEY_TAB, KD_KEY_INSERT, KD_KEY_F6, KD_KEY_ESCAPE};
    for (int step = 0; step < 3000; step++) {
        int op = kd_rand_range(&r, 0, 9);
        if (op <= 2) {
            const char *s = words[kd_rand_range(&r, 0, 6)];
            kdm_text_input(&M, s, strlen(s));
        } else if (op <= 4) {
            key(KD_KEY_CHAR, (char)kd_rand_range(&r, 0x20, 0x7E), 0);
        } else if (op <= 7) {
            uint8_t mods = (uint8_t)kd_rand_range(&r, 0, 3) & (KD_MOD_SHIFT | KD_MOD_CTRL);
            key(keys[kd_rand_range(&r, 0, 9)], 0, mods);
        } else if (op == 8) {
            int i = kd_rand_range(&r, 0, 2);
            kdm_window_move(&M, w[i], kd_rand_range(&r, -40, 260), kd_rand_range(&r, 0, 160));
        } else if (kd_rand_range(&r, 0, 9) == 0) {
            key(KD_KEY_F10, 0, 0);   // and the next keys may navigate it
        }
        drain();
        if (step % 50 == 0) {
            present();
            if (!equals_full_redraw()) {
                char msg[48];
                snprintf(msg, sizeof msg, "frame differs at step %d", step);
                kd_test_fail(__FILE__, __LINE__, msg);
                return;
            }
            for (int i = 0; i < 3; i++) CHECK(kd_edit_valid(kdm_field_editor(&M, w[i], f[i])));
        }
    }
}

// ---- the multiline editor ----

static const kdm_field *editor_state(void) { return &M.fields[KDM_FIELDS]; }

static bool editor_view_ok(void) {
    const kdm_field *f = editor_state();
    const kdm_item *it = &M.items[f->item];
    size_t rows = (size_t)(it->h - 4) / KDM_LINE_H, lines = 1, line = 0;
    for (size_t i = 0; i < f->ed.len; i++) lines += f->ed.buf[i] == '\n';
    for (size_t i = 0; i < f->ed.caret; i++) line += f->ed.buf[i] == '\n';
    size_t off = 0;
    for (size_t l = 0; l < f->top; l++) off = kd_edit_line_end(&f->ed, off) + 1;
    return f->lines == lines && f->top_off == off && line >= f->top && line < f->top + rows &&
           kd_edit_valid(&f->ed);
}

static void t_editor_lines(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(10, 20, 280, 150), KD_WF_CLOSE | KD_WF_MOVE, 2);
    int ed = kdm_add_editor(&M, w, 4, 4, 260, 104, "", 0, 0);
    int ok = kdm_add_button(&M, w, 4, 112, 40, 14, "OK", 2, KD_BTN_DEFAULT);
    kdm_item_set_focusable(&M, w, ok, true);
    CHECK(ed >= 0 && kdm_focused(&M, w) == ed);
    present();
    drain();
    type("abc");
    key(KD_KEY_ENTER, 0, 0);            // a line break, not the default button
    kdm_text_input(&M, "神楽\n", 7);
    CHECK(field_is(w, ed, "abc\n神楽\n"));
    CHECK_EQ(count_events(KDM_EV_ACTIVATE, -1), 0);
    present();
    CHECK(equals_full_redraw() && editor_view_ok());
    // Up and Down keep the visual column: 神楽| is x 16, which is "ab|" above.
    key(KD_KEY_UP, 0, 0);
    key(KD_KEY_END, 0, 0);
    CHECK_EQ(kdm_field_editor(&M, w, ed)->caret, 10);
    key(KD_KEY_UP, 0, 0);
    CHECK_EQ(kdm_field_editor(&M, w, ed)->caret, 2);
    key(KD_KEY_DOWN, 0, KD_MOD_SHIFT);  // select down to 神楽 end
    const kd_edit *e = kdm_field_editor(&M, w, ed);
    CHECK(e->anchor == 2 && e->caret == 10);
    present();
    CHECK(equals_full_redraw());
    CHECK_EQ(count_events(KD_EV_KEY, -1), 0);   // all consumed by the editor
    // Typing over a selection that spans a line break joins the lines.
    type("X");
    CHECK(field_is(w, ed, "abX\n"));
    present();
    CHECK(equals_full_redraw() && editor_view_ok());
    // Backspace at a line start joins it with the line above.
    kdm_text_input(&M, "1\n2\n3", 5);
    key(KD_KEY_HOME, 0, 0);
    key(KD_KEY_BACKSPACE, 0, 0);
    CHECK(field_is(w, ed, "abX1\n23\n"));
    present();
    CHECK(equals_full_redraw() && editor_view_ok());
    key(KD_KEY_HOME, 0, KD_MOD_CTRL);
    CHECK_EQ(kdm_field_editor(&M, w, ed)->caret, 0);
    key(KD_KEY_END, 0, KD_MOD_CTRL | KD_MOD_SHIFT);
    CHECK(kdm_field_editor(&M, w, ed)->caret == 8 && kdm_field_editor(&M, w, ed)->anchor == 0);
    present();
    CHECK(equals_full_redraw());
    // Inserting a line break in the middle moves every line below.
    kdm_field_select(&M, w, ed, 2, 2);
    present();
    key(KD_KEY_ENTER, 0, 0);
    CHECK(field_is(w, ed, "ab\nX1\n23\n"));
    present();
    CHECK(equals_full_redraw() && editor_view_ok());
    // Caret pixel: row 1, after nothing: column 4 + 2, rows start 4 + 2 + 10.
    kd_rect work = kd_window_work(&M.desk.win[w]);
    CHECK_EQ(px(work.x + 6, work.y + 16), KD_C_BLACK);
    // A click places the caret on the clicked line.
    click(work.x + 4 + 2 + 9, work.y + 4 + 2 + 2 * KDM_LINE_H + 3);   // line 2, after "2"
    CHECK_EQ(kdm_field_editor(&M, w, ed)->caret, 7);
    present();
    CHECK(equals_full_redraw() && editor_view_ok());
}

static void t_editor_scrolling(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(10, 20, 200, 120), KD_WF_MOVE, 2);
    char doc[1024];
    size_t n = 0;
    for (int i = 0; i < 40; i++) n += (size_t)snprintf(doc + n, sizeof doc - n, "line %02d\n", i);
    int ed = kdm_add_editor(&M, w, 2, 2, 120, 64, doc, n, 0);   // 6 rows
    const kdm_field *f = editor_state();
    CHECK(f->lines == 41 && f->top == 0);
    present();
    key(KD_KEY_END, 0, KD_MOD_CTRL);
    CHECK(f->top == 41 - 6 && editor_view_ok());
    present();
    CHECK(equals_full_redraw());
    key(KD_KEY_PGUP, 0, 0);
    CHECK(kd_edit_line_index(&f->ed, f->ed.caret) == 35 && editor_view_ok());
    key(KD_KEY_PGUP, 0, 0);
    key(KD_KEY_PGUP, 0, 0);
    CHECK(kd_edit_line_index(&f->ed, f->ed.caret) == 25 && f->top == 25 && editor_view_ok());
    present();
    CHECK(equals_full_redraw());
    key(KD_KEY_PGDN, 0, KD_MOD_SHIFT);
    CHECK(kd_edit_line_index(&f->ed, f->ed.caret) == 30 && editor_view_ok());
    present();
    CHECK(equals_full_redraw());
    // A long line scrolls sideways; moving to a short line scrolls back.
    key(KD_KEY_HOME, 0, KD_MOD_CTRL);
    key(KD_KEY_END, 0, 0);
    type(" and a lot more text on the first line");
    CHECK(f->scroll > 0);
    present();
    CHECK(equals_full_redraw());
    key(KD_KEY_DOWN, 0, 0);
    CHECK(f->scroll == 0 && editor_view_ok());
    present();
    CHECK(equals_full_redraw());
    // Deleting lines near the end pulls the view down: no empty rows.
    kdm_field_select(&M, w, ed, 0, 0);
    key(KD_KEY_END, 0, KD_MOD_CTRL);
    for (int i = 0; i < 9 * 10; i++) key(KD_KEY_BACKSPACE, 0, 0);
    CHECK(f->top == f->lines - 6 && editor_view_ok());
    present();
    CHECK(equals_full_redraw());
}

static void t_editor_capacity(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(10, 20, 200, 120), 0, 2);
    static char big[KDM_DOC_BYTES + 1];
    memset(big, 'x', sizeof big);
    for (size_t i = 79; i < sizeof big; i += 80) big[i] = '\n';
    CHECK_EQ(kdm_add_editor(&M, w, 0, 0, 180, 80, big, KDM_DOC_BYTES, 0), KDM_ETOOLONG);
    CHECK_EQ(kdm_add_editor(&M, w, 0, 0, 180, 80, "\xE7\xA5", 2, 0), KDM_EINVAL);
    CHECK_EQ(kdm_add_editor(&M, w, 0, 0, 180, 10, "", 0, 0), KDM_EINVAL);
    int ed = kdm_add_editor(&M, w, 0, 0, 180, 80, big, KDM_DOC_BYTES - 1, 0);
    CHECK(ed >= 0 && editor_view_ok());
    CHECK_EQ(kdm_add_editor(&M, w, 0, 90, 180, 20, "", 0, 0), KDM_ENOFIELD);   // one per desktop
    present();
    key(KD_KEY_END, 0, KD_MOD_CTRL);
    type("y");                                        // full: nothing changes
    kdm_text_input(&M, "\n", 1);
    CHECK_EQ(kdm_field_editor(&M, w, ed)->len, KDM_DOC_BYTES - 1);
    CHECK_EQ(kdm_text_input(&M, "z", 1), KDM_ETOOLONG);
    key(KD_KEY_BACKSPACE, 0, 0);
    CHECK_EQ(kdm_text_input(&M, "\r\n", 2), 1);       // CRLF stored as LF
    present();
    CHECK(equals_full_redraw() && editor_view_ok());
    // CRLF documents load as LF.
    CHECK_EQ(kdm_item_set_text(&M, w, ed, "a\r\nb\r\n", 6), KDM_OK);
    CHECK(field_is(w, ed, "a\nb\n") && editor_state()->lines == 3 && editor_state()->ed.caret == 0);
    present();
    CHECK(equals_full_redraw());
    // The editor's slot comes back with its window.
    kdm_window_close(&M, w);
    int v = kdm_window_open(&M, "Again", kd_rect_make(10, 20, 200, 120), 0, 2);
    CHECK(kdm_add_editor(&M, v, 0, 0, 180, 80, "ok", 2, 0) >= 0);
}

static void t_editor_random(void) {
    uint32_t r = 777;
    kdm_menu_def def = {1, {"M"}, {{"A", "B"}}, {2}};
    kdm_init(&M, &def);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(8, 16, 220, 140), KD_WF_MOVE, 2);
    int ed = kdm_add_editor(&M, w, 2, 2, 200, 94, "", 0, 0);
    int f = kdm_add_field(&M, w, 2, 100, 120, "", 0, 0);
    int v = kdm_window_open(&M, "Over", kd_rect_make(150, 100, 120, 70), KD_WF_MOVE, 3);
    kdm_add_field(&M, v, 2, 2, 100, "", 0, 0);
    (void)f;
    kdm_window_activate(&M, w);
    static const char *const words[] = {"a", "神", "é", "word ", "\n", "x\ny", "長い行のテキストです", "😀", "\r\n"};
    static const uint8_t keys[] = {KD_KEY_LEFT, KD_KEY_RIGHT, KD_KEY_UP, KD_KEY_DOWN, KD_KEY_HOME, KD_KEY_END,
                                   KD_KEY_PGUP, KD_KEY_PGDN, KD_KEY_BACKSPACE, KD_KEY_DELETE, KD_KEY_ENTER,
                                   KD_KEY_TAB, KD_KEY_INSERT, KD_KEY_F6};
    for (int step = 0; step < 4000; step++) {
        int op = kd_rand_range(&r, 0, 9);
        if (op <= 3) {
            const char *s = words[kd_rand_range(&r, 0, 8)];
            kdm_text_input(&M, s, strlen(s));
        } else if (op <= 4) {
            key(KD_KEY_CHAR, (char)kd_rand_range(&r, 0x20, 0x7E), 0);
        } else if (op <= 8) {
            uint8_t mods = (uint8_t)(kd_rand_range(&r, 0, 3) & (KD_MOD_SHIFT | KD_MOD_CTRL));
            key(keys[kd_rand_range(&r, 0, 13)], 0, mods);
        } else if (kd_rand_range(&r, 0, 3) == 0) {
            kdm_window_move(&M, kd_rand_range(&r, 0, 1) ? w : v, kd_rand_range(&r, -30, 250), kd_rand_range(&r, 0, 150));
        }
        drain();
        if (step % 25 == 0) {
            present();
            if (!equals_full_redraw() || !editor_view_ok()) {
                char msg[48];
                snprintf(msg, sizeof msg, "editor differs at step %d", step);
                kd_test_fail(__FILE__, __LINE__, msg);
                return;
            }
        }
    }
    CHECK(kdm_field_editor(&M, w, ed) != NULL);
}

// kd_fb_mono's byte-wise path for glyphs up to 8 px against the pixel-by-
// pixel definition: same pixels, same dirty tiles, at any position and clip.
static kd_fb FA, FB;

static void t_mono_matches_pixels(void) {
    uint32_t r = 99;
    for (int n = 0; n < 20000; n++) {
        for (size_t i = 0; i < sizeof FA.px; i += 97) FA.px[i] = (uint8_t)kd_rand(&r);
        if (n % 64 == 0)
            for (size_t i = 0; i < sizeof FA.px; i++) FA.px[i] = (uint8_t)kd_rand(&r);
        memset(FA.dirty, 0, sizeof FA.dirty);
        int w = kd_rand_range(&r, 1, 8), h = kd_rand_range(&r, 1, 8);
        int x = kd_rand_range(&r, -10, KD_W + 2), y = kd_rand_range(&r, -10, KD_H + 2);
        kd_rect clip = kd_rect_make(kd_rand_range(&r, -5, KD_W), kd_rand_range(&r, -5, KD_H),
                                    kd_rand_range(&r, 0, 40), kd_rand_range(&r, 0, 30));
        if (n % 3 == 0) clip = kd_rect_make(x - 3, y - 3, 20, 20);
        uint8_t bits[8];
        for (int i = 0; i < 8; i++) bits[i] = (uint8_t)kd_rand(&r);
        uint8_t fg = (uint8_t)kd_rand_range(&r, 0, 15);
        int bg = kd_rand_range(&r, 0, 2) ? KD_NO_KEY : kd_rand_range(&r, 0, 15);
        FB = FA;
        kd_fb_set_clip(&FA, clip);
        kd_fb_set_clip(&FB, clip);
        kd_fb_mono(&FA, x, y, w, h, bits, fg, bg);
        for (int yy = 0; yy < h; yy++)
            for (int xx = 0; xx < w; xx++) {
                bool ink = (bits[yy] >> (7 - xx)) & 1;
                if (ink) kd_fb_pixel(&FB, x + xx, y + yy, fg);
                else if (bg != KD_NO_KEY) kd_fb_pixel(&FB, x + xx, y + yy, (uint8_t)bg);
            }
        if (memcmp(FA.px, FB.px, sizeof FA.px) || memcmp(FA.dirty, FB.dirty, sizeof FA.dirty)) {
            char msg[96];
            snprintf(msg, sizeof msg, "case %d: x %d y %d w %d clip %d,%d %dx%d bg %d", n, x, y, w,
                     clip.x, clip.y, clip.w, clip.h, bg);
            kd_test_fail(__FILE__, __LINE__, msg);
            return;
        }
    }
}

// ---- input method preedit ----

static void t_preedit_field(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(10, 20, 220, 100), KD_WF_MOVE, 2);
    int f = kdm_add_field(&M, w, 8, 8, 200, "abcd", 4, 0);
    kdm_field_select(&M, w, f, 2, 2);
    present();
    uint32_t crc0 = fb_crc();
    uint32_t v = kdm_field_editor(&M, w, f)->version;
    kd_rect work = kd_window_work(&M.desk.win[w]);
    int x, y, h;
    CHECK_EQ(kdm_caret_xy(&M, w, f, &x, &y, &h), KDM_OK);
    CHECK(x == work.x + 8 + 2 + 16 && y == work.y + 9 && h == 10);
    CHECK_EQ(kdm_set_preedit(&M, w, f, "▽かな", 9, -1, -1), KDM_OK);   // 3 glyphs, 24 px
    present();
    CHECK(equals_full_redraw());
    CHECK(field_is(w, f, "abcd") && kdm_field_editor(&M, w, f)->version == v);   // the text is untouched
    CHECK_EQ(kdm_caret_xy(&M, w, f, &x, &y, &h), KDM_OK);
    CHECK_EQ(x, work.x + 8 + 2 + 16 + 24);                // the caret follows the preedit
    CHECK_EQ(px(x, work.y + 10), KD_C_BLACK);
    CHECK_EQ(px(work.x + 8 + 2 + 16 + 3, work.y + 18), KD_C_BLACK);   // underline (glyph row + 8)
    // Highlight: ▼漢字 with 漢字 inverted.
    CHECK_EQ(kdm_set_preedit(&M, w, f, "▼漢字", 9, 3, 9), KDM_OK);
    present();
    CHECK(equals_full_redraw());
    CHECK_EQ(px(work.x + 8 + 2 + 16 + 8, work.y + 9), KD_C_BLACK);    // inverted background
    CHECK_EQ(px(work.x + 8 + 2 + 16 + 2, work.y + 9), KD_C_WHITE);    // ▼ not inverted
    // Clearing leaves no trace.
    CHECK_EQ(kdm_set_preedit(&M, w, f, "", 0, -1, -1), KDM_OK);
    present();
    CHECK_EQ(fb_crc(), crc0);
    // Invalid input changes nothing.
    CHECK_EQ(kdm_set_preedit(&M, w, f, "a\nb", 3, -1, -1), KDM_EINVAL);
    CHECK_EQ(kdm_set_preedit(&M, w, f, "\xE7\xA5", 2, -1, -1), KDM_EINVAL);
    CHECK_EQ(kdm_set_preedit(&M, w, f, "▼漢字", 9, 3, 5), KDM_EINVAL);   // inside 漢
    CHECK_EQ(kdm_set_preedit(&M, w, f, "▼漢字", 9, 6, 3), KDM_EINVAL);
    static char big[KDM_PREEDIT_BYTES];
    memset(big, 'x', sizeof big);
    CHECK_EQ(kdm_set_preedit(&M, w, f, big, sizeof big, -1, -1), KDM_ETOOLONG);
    int t = kdm_add_text(&M, w, 0, 40, "label", 5, 1, -1, 0);
    CHECK_EQ(kdm_set_preedit(&M, w, t, "x", 1, -1, -1), KDM_EINVAL);   // not editable
    CHECK(present() <= 6);                                 // only the label was drawn
    CHECK(equals_full_redraw());
}

static void t_preedit_editor_and_targets(void) {
    kdm_menu_def def = {1, {"M"}, {{"A", "B"}}, {2}};
    kdm_init(&M, &def);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(0, 11, 320, 189), 0, 2);
    static const char doc[] = "line one\nline two\nline three";
    int ed = kdm_add_editor(&M, w, 2, 2, 314, 154, doc, sizeof doc - 1, 0);
    int fw = kdm_window_open(&M, "Dlg", kd_rect_make(60, 60, 200, 60), 0, 2);
    int fl = kdm_add_field(&M, fw, 4, 4, 180, "", 0, 0);
    int ok = kdm_add_button(&M, fw, 4, 24, 40, 14, "OK", 2, 0);
    kdm_item_set_focusable(&M, fw, ok, true);
    int slot = -1;
    CHECK_EQ(kdm_input_target(&M, &slot), fl);            // the dialog's field
    CHECK_EQ(slot, fw);
    kdm_focus(&M, fw, ok);
    CHECK_EQ(kdm_input_target(&M, &slot), KDM_ENONE);     // a button has the focus
    kdm_window_activate(&M, w);
    CHECK(kdm_input_target(&M, &slot) == ed && slot == w);
    key(KD_KEY_F10, 0, 0);
    CHECK_EQ(kdm_input_target(&M, &slot), KDM_ENONE);     // menus open
    key(KD_KEY_ESCAPE, 0, 0);
    drain();
    kdm_field_select(&M, w, ed, 14, 14);                  // line two, after "line "
    present();
    uint32_t crc0 = fb_crc();
    CHECK_EQ(kdm_set_preedit(&M, w, ed, "▽にほんご", 15, -1, -1), KDM_OK);
    present();
    CHECK(equals_full_redraw());
    int x, y, h;
    kdm_caret_xy(&M, w, ed, &x, &y, &h);
    kd_rect work = kd_window_work(&M.desk.win[w]);
    CHECK(x == work.x + 2 + 2 + 5 * 8 + 5 * 8 && y == work.y + 2 + 2 + KDM_LINE_H && h == KDM_LINE_H);
    CHECK(field_is(w, ed, "line one\nline two\nline three"));
    // The preedit moves to another record: the editor is restored exactly.
    kdm_window_activate(&M, fw);
    kdm_focus(&M, fw, fl);
    CHECK_EQ(kdm_set_preedit(&M, fw, fl, "▼日本語", 12, 3, 12), KDM_OK);
    present();
    CHECK(equals_full_redraw());
    kdm_window_activate(&M, w);
    kdm_window_activate(&M, fw);
    CHECK_EQ(kdm_set_preedit(&M, fw, fl, "", 0, -1, -1), KDM_OK);
    kdm_window_close(&M, fw);
    present();
    CHECK_EQ(fb_crc(), crc0);
    // A long preedit at the right edge scrolls the editor; clearing it is exact.
    kdm_field_select(&M, w, ed, 28, 28);
    present();
    static const char long_pre[] = "▽ながいながいながいながいながいながいながいながいながいながい";   // 31 glyphs, 93 bytes
    int rc = kdm_set_preedit(&M, w, ed, long_pre, sizeof long_pre - 1, -1, -1);
    CHECK_EQ(rc, KDM_OK);
    CHECK(M.fields[KDM_FIELDS].scroll > 0);
    present();
    CHECK(equals_full_redraw());
    // Closing the window drops the preedit.
    kdm_window_close(&M, w);
    CHECK_EQ(M.preedit_item, KDM_NONE);
    present();
    CHECK(equals_full_redraw());
}

static void t_preedit_random(void) {
    uint32_t r = 31337;
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(0, 11, 300, 160), KD_WF_MOVE, 2);
    int ed = kdm_add_editor(&M, w, 2, 2, 200, 94, "", 0, 0);
    int fl = kdm_add_field(&M, w, 2, 110, 150, "", 0, 0);
    static const char *const pre[] = {"", "k", "▽か", "▽かんじ", "▼漢字", "▽ながいよみがなのれい", "▼候補"};
    static const char *const words[] = {"a", "神", "abc ", "\n", "日本語の文章"};
    for (int step = 0; step < 3000; step++) {
        int target = kd_rand_range(&r, 0, 1) ? ed : fl;
        int op = kd_rand_range(&r, 0, 9);
        if (op <= 3) {
            const char *s = pre[kd_rand_range(&r, 0, 6)];
            int hl = s[0] && !strncmp(s, "▼", 3);
            kdm_focus(&M, w, target);
            kdm_set_preedit(&M, w, target, s, strlen(s), hl ? 3 : -1, hl ? (int)strlen(s) : -1);
        } else if (op <= 6) {
            kdm_set_preedit(&M, w, target, "", 0, -1, -1);   // the IME clears before committing
            const char *s = words[kd_rand_range(&r, 0, 4)];
            kdm_text_input(&M, s, strlen(s));
        } else if (op == 7) {
            static const uint8_t keys[] = {KD_KEY_LEFT, KD_KEY_RIGHT, KD_KEY_UP, KD_KEY_END, KD_KEY_BACKSPACE};
            key(keys[kd_rand_range(&r, 0, 4)], 0, 0);
        } else if (op == 8) {
            kdm_window_move(&M, w, kd_rand_range(&r, -20, 60), kd_rand_range(&r, 0, 50));
        } else {
            kdm_focus(&M, w, kd_rand_range(&r, 0, 1) ? ed : fl);
        }
        drain();
        if (step % 20 == 0) {
            present();
            if (!equals_full_redraw()) {
                char msg[48];
                snprintf(msg, sizeof msg, "preedit frame differs at step %d", step);
                kd_test_fail(__FILE__, __LINE__, msg);
                return;
            }
        }
    }
}

// F10 on a desktop without menus read menus[-1] (found by the preedit tests).
static void t_f10_without_menus(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(10, 20, 100, 60), 0, 2);
    (void)w;
    key(KD_KEY_F10, 0, 0);
    CHECK_EQ(M.desk.menu_open, -1);
    key(KD_KEY_RIGHT, 0, 0);
    key(KD_KEY_ENTER, 0, 0);
    CHECK_EQ(M.desk.menu_open, -1);
    present();
    CHECK(equals_full_redraw());
}

// ---- input method candidate popup and status ----

static const char *const CANDS[] = {"候補", "校", "公", "高等学校", "考"};

static int cands(int w, int id, int n, int sel, const char *foot) {
    size_t lens[KDM_CAND_ITEMS];
    for (int i = 0; i < n; i++) lens[i] = strlen(CANDS[i]);
    return kdm_set_candidates(&M, w, id, CANDS, lens, n, sel, foot, strlen(foot));
}

static bool popup_is(kd_rect r) {
    kd_rect p = M.desk.popup;
    return p.x == r.x && p.y == r.y && p.w == r.w && p.h == r.h;
}

// The popup is on screen, below the menu bar, inside the work area
// horizontally, and never on the caret's row: below it, or above it.
static bool popup_placed(int w, int id) {
    kd_rect p = M.desk.popup, work = kd_window_work(&M.desk.win[w]);
    int x, y, h;
    if (kd_rect_empty(p) || kdm_caret_xy(&M, w, id, &x, &y, &h) != KDM_OK) return false;
    if (p.x < 0 || p.x + p.w > KD_W || p.y < KD_MENU_H || p.y + p.h > KD_H) return false;
    if (p.x < work.x || p.x + p.w > work.x + work.w) return false;
    return p.y >= y + h || p.y + p.h <= y;
}

static void t_cand_corners(void) {
    static const struct { int x, y; bool right, above; } corner[] = {
        {0, 11, false, false}, {160, 11, true, false}, {0, 120, false, true}, {160, 120, true, true}};
    for (int c = 0; c < 4; c++) {
        kdm_init(&M, NULL);
        int w = kdm_window_open(&M, "W", kd_rect_make(corner[c].x, corner[c].y, 160, 80), KD_WF_MOVE, 2);
        int f = kdm_add_field(&M, w, 2, 50, 150, "abcdefghijklmnopq", 17, 0);
        int at = corner[c].right ? 17 : 0;
        kdm_field_select(&M, w, f, at, at);
        present();
        uint32_t crc0 = fb_crc();
        CHECK_EQ(cands(w, f, 5, 0, "1/3"), KDM_OK);
        present();
        CHECK(popup_placed(w, f));
        CHECK(equals_full_redraw());
        kd_rect p = M.desk.popup, work = kd_window_work(&M.desk.win[w]);
        int x, y, h;
        kdm_caret_xy(&M, w, f, &x, &y, &h);
        CHECK_EQ(p.y >= y + h, !corner[c].above);         // flipped above near the bottom
        if (corner[c].right) CHECK_EQ(p.x + p.w, work.x + work.w);   // clamped at the right
        else CHECK_EQ(p.x, work.x);                       // clamped at the left (x - 14 < 0)
        CHECK_EQ(px(p.x, p.y), KD_C_BLACK);               // border
        CHECK_EQ(px(p.x + 1, p.y + 3), KD_C_BLACK);       // the first row is selected
        CHECK_EQ(cands(w, f, 0, -1, ""), KDM_OK);         // hidden: no trace
        CHECK(kd_rect_empty(M.desk.popup));
        present();
        CHECK_EQ(fb_crc(), crc0);
    }
}

static void t_cand_anchor(void) {
    kdm_menu_def def = {1, {"M"}, {{"A", "B"}}, {2}};
    kdm_init(&M, &def);
    kdm_window_open(&M, "Low", kd_rect_make(0, 100, 320, 100), 0, 3);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(20, 20, 200, 100), KD_WF_MOVE, 2);
    static const char doc[] = "日本語の文章と abc の行\n二行目\n三\n四\n五\n六\n七\n八\n九\n十";
    int ed = kdm_add_editor(&M, w, 2, 2, 190, 74, doc, sizeof doc - 1, 0);
    kdm_field_select(&M, w, ed, 6, 6);                    // after 日本 (full width)
    present();
    CHECK_EQ(kdm_set_preedit(&M, w, ed, "▼語", 6, 3, 6), KDM_OK);
    CHECK_EQ(cands(w, ed, 5, 0, ""), KDM_OK);
    present();
    int x, y, h;
    kdm_caret_xy(&M, w, ed, &x, &y, &h);
    kd_rect work = kd_window_work(&M.desk.win[w]);
    CHECK_EQ(M.desk.popup.x, work.x + 2 + 2 + 16 - 14);   // the text under the preedit's start
    CHECK_EQ(M.desk.popup.y, y + h + 1);
    CHECK(M.desk.popup.y + M.desk.popup.h > 100);         // over the lower window too
    CHECK(equals_full_redraw());
    // The window moves: the popup follows at the next render.
    kd_rect before = M.desk.popup;
    kdm_window_move(&M, w, 60, 40);
    present();
    CHECK(M.desk.popup.x == before.x + 40 && M.desk.popup.y == before.y + 20);
    CHECK(equals_full_redraw());
    kdm_window_move(&M, w, 20, 20);
    // The view scrolls down to the last line: the popup follows the caret's row.
    kdm_set_preedit(&M, w, ed, "", 0, -1, -1);
    cands(w, ed, 0, -1, "");
    kdm_field_select(&M, w, ed, (int)sizeof doc - 1, (int)sizeof doc - 1);
    CHECK_EQ(kdm_set_preedit(&M, w, ed, "▼語", 6, 3, 6), KDM_OK);
    CHECK_EQ(cands(w, ed, 3, 1, "2/2"), KDM_OK);
    present();
    CHECK(popup_placed(w, ed));
    CHECK(equals_full_redraw());
    // A dialog takes the focus: the popup hides.
    kd_rect shown = M.desk.popup;
    int dlg = kdm_window_open(&M, "Dlg", kd_rect_make(80, 60, 160, 50), 0, 2);
    int fl = kdm_add_field(&M, dlg, 4, 4, 140, "", 0, 0);
    present();
    CHECK(kd_rect_empty(M.desk.popup));
    CHECK(equals_full_redraw());
    // The dialog's own field: the popup is above the dialog.
    CHECK_EQ(cands(dlg, fl, 2, 0, ""), KDM_OK);
    present();
    CHECK(popup_placed(dlg, fl));
    CHECK(equals_full_redraw());
    CHECK_EQ(cands(dlg, fl, 0, -1, ""), KDM_OK);
    kdm_window_close(&M, dlg);
    CHECK_EQ(cands(w, ed, 3, 1, "2/2"), KDM_OK);
    present();
    CHECK(popup_is(shown));
    // A menu opens over the popup and closes exactly.
    uint32_t crc1 = fb_crc();
    key(KD_KEY_F10, 0, 0);
    present();
    CHECK(equals_full_redraw());
    key(KD_KEY_ESCAPE, 0, 0);
    drain();
    present();
    CHECK_EQ(fb_crc(), crc1);
    // Closing the window drops the popup.
    kdm_window_close(&M, w);
    CHECK_EQ(M.cand.item, KDM_NONE);
    present();
    CHECK(kd_rect_empty(M.desk.popup));
    CHECK(equals_full_redraw());
}

static void t_cand_minimal(void) {
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "W", kd_rect_make(10, 20, 220, 100), 0, 2);
    int f = kdm_add_field(&M, w, 8, 8, 200, "", 0, 0);
    CHECK_EQ(cands(w, f, 5, 0, "1/2"), KDM_OK);
    present();
    kd_rect p = M.desk.popup;
    int row = (p.w - 2) * 10;
    CHECK_EQ(cands(w, f, 5, 1, "1/2"), KDM_OK);           // the selection moves: two rows
    present();
    CHECK_EQ(M.desk.stats.last_area, 2 * row);
    CHECK(equals_full_redraw());
    CHECK_EQ(cands(w, f, 5, 1, "1/2"), KDM_OK);           // nothing changed: nothing drawn
    CHECK_EQ(present(), 0);
    CHECK_EQ(cands(w, f, 5, 1, "2/2"), KDM_OK);           // the footer alone
    present();
    CHECK(M.desk.stats.last_area > 0 && M.desk.stats.last_area <= (p.w - 2) * 12);   // separator and row
    CHECK(equals_full_redraw());
    // Invalid lists change nothing.
    static const char *const six[] = {"a", "b", "c", "d", "e", "f"};
    size_t lens[6] = {1, 1, 1, 1, 1, 1};
    CHECK_EQ(kdm_set_candidates(&M, w, f, six, lens, 6, 0, "", 0), KDM_EINVAL);
    CHECK_EQ(cands(w, f, 2, 2, ""), KDM_EINVAL);
    static const char *const nl[] = {"a\nb"};
    size_t nll = 3;
    CHECK_EQ(kdm_set_candidates(&M, w, f, nl, &nll, 1, 0, "", 0), KDM_EINVAL);
    int t = kdm_add_text(&M, w, 0, 40, "label", 5, 1, -1, 0);
    CHECK_EQ(cands(w, t, 1, 0, ""), KDM_EINVAL);
    CHECK(popup_is(p));
    // A footer alone (候補なし) still shows.
    static const char none[] = "候補なし";
    CHECK_EQ(kdm_set_candidates(&M, w, f, NULL, NULL, 0, -1, none, sizeof none - 1), KDM_OK);
    present();
    CHECK(!kd_rect_empty(M.desk.popup));
    CHECK(equals_full_redraw());
}

static void t_status_indicator(void) {
    kdm_menu_def def = {3, {"ファイル", "編集", "表示"}, {{"A"}, {"B"}, {"C"}}, {1, 1, 1}};
    kdm_init(&M, &def);
    kdm_window_open(&M, "W", kd_rect_make(10, 20, 220, 100), 0, 2);
    present();
    uint32_t crc0 = fb_crc();
    int menus_end = kd_menu_title_x(M.desk.menus, 2) + kd_menu_title_w(M.desk.menus, 2);
    static const char *const labels[] = {"A 直接", "あ かな", "ア カナ", "▽ 読み", "▼ 変換"};
    for (int i = 0; i < 5; i++) {
        kd_rect old = kd_desktop_status_box(&M.desk);
        CHECK_EQ(kdm_set_status(&M, labels[i], strlen(labels[i])), KDM_OK);
        kd_rect now = kd_desktop_status_box(&M.desk);
        present();
        CHECK(now.x > menus_end && now.x + now.w == KD_W - 2 && now.y == 0 && now.h == KD_MENU_H - 1);
        CHECK(M.desk.stats.last_area <= old.w * old.h + now.w * now.h);   // only the indicator
        CHECK(equals_full_redraw());
    }
    // Too long: clipped, never over the menus.
    static const char lng[] = "あいうえおかきくけこさしすせそ";
    CHECK_EQ(kdm_set_status(&M, lng, sizeof lng - 1), KDM_OK);
    present();
    CHECK(kd_desktop_status_box(&M.desk).x > menus_end);
    CHECK(equals_full_redraw());
    CHECK_EQ(kdm_set_status(&M, "\xE7\xA5", 2), KDM_EINVAL);
    CHECK_EQ(kdm_set_status(&M, "", 0), KDM_OK);
    present();
    CHECK_EQ(fb_crc(), crc0);
}

static void t_cand_random(void) {
    uint32_t r = 4242;
    kdm_menu_def def = {2, {"ファイル", "編集"}, {{"A", "B"}, {"C"}}, {2, 1}};
    kdm_init(&M, &def);
    int low = kdm_window_open(&M, "Low", kd_rect_make(100, 60, 200, 120), KD_WF_MOVE, 3);
    int w = kdm_window_open(&M, "Doc", kd_rect_make(0, 11, 260, 150), KD_WF_MOVE, 2);
    int ed = kdm_add_editor(&M, w, 2, 2, 200, 94, "", 0, 0);
    int fl = kdm_add_field(&M, w, 2, 110, 150, "", 0, 0);
    static const char *const words[] = {"a", "神", "abc ", "\n", "日本語の文章"};
    static const char *const st[] = {"A 直接", "あ かな", "ア カナ", "▽ 読み", "▼ 変換"};
    for (int step = 0; step < 3000; step++) {
        int target = kd_rand_range(&r, 0, 1) ? ed : fl;
        int op = kd_rand_range(&r, 0, 11);
        if (op <= 3) {
            kdm_focus(&M, w, target);
            kdm_set_preedit(&M, w, target, "▼漢字", 9, 3, 9);
            int n = kd_rand_range(&r, 0, 5);
            cands(w, target, n, n ? kd_rand_range(&r, -1, n - 1) : -1, kd_rand_range(&r, 0, 1) ? "1/3" : "");
        } else if (op <= 5) {
            kdm_set_preedit(&M, w, target, "", 0, -1, -1);
            cands(w, target, 0, -1, "");
            const char *s = words[kd_rand_range(&r, 0, 4)];
            kdm_text_input(&M, s, strlen(s));
        } else if (op == 6) {
            static const uint8_t keys[] = {KD_KEY_LEFT, KD_KEY_RIGHT, KD_KEY_UP, KD_KEY_DOWN, KD_KEY_END};
            key(keys[kd_rand_range(&r, 0, 4)], 0, 0);
        } else if (op == 7) {
            kdm_window_move(&M, kd_rand_range(&r, 0, 1) ? w : low, kd_rand_range(&r, -40, 120),
                            kd_rand_range(&r, 0, 120));
        } else if (op == 8) {
            kdm_window_activate(&M, kd_rand_range(&r, 0, 1) ? w : low);
        } else if (op == 9) {
            const char *s = st[kd_rand_range(&r, 0, 4)];
            kdm_set_status(&M, s, strlen(s));
        } else if (op == 10) {
            key(KD_KEY_F10, 0, 0);
        } else {
            key(KD_KEY_ESCAPE, 0, 0);
        }
        drain();
        if (step % 10 == 0) {
            present();
            if (!equals_full_redraw()) {
                char msg[48];
                snprintf(msg, sizeof msg, "popup frame differs at step %d", step);
                kd_test_fail(__FILE__, __LINE__, msg);
                return;
            }
        }
    }
}

static const kd_test_case tests[] = {
    {"cand_corners", t_cand_corners},
    {"cand_anchor", t_cand_anchor},
    {"cand_minimal", t_cand_minimal},
    {"status_indicator", t_status_indicator},
    {"cand_random", t_cand_random},
    {"f10_without_menus", t_f10_without_menus},
    {"preedit_field", t_preedit_field},
    {"preedit_editor_and_targets", t_preedit_editor_and_targets},
    {"preedit_random", t_preedit_random},
    {"mono_matches_pixels", t_mono_matches_pixels},
    {"editor_lines", t_editor_lines},
    {"editor_scrolling", t_editor_scrolling},
    {"editor_capacity", t_editor_capacity},
    {"editor_random", t_editor_random},
    {"field_typing", t_field_typing},
    {"field_utf8_input", t_field_utf8_input},
    {"field_scrolling_and_clipping", t_field_scrolling_and_clipping},
    {"focus_navigation", t_focus_navigation},
    {"keyboard_menus_and_windows", t_keyboard_menus_and_windows},
    {"clipboard", t_clipboard},
    {"field_hidden_updates", t_field_hidden_updates},
    {"field_random", t_field_random},
    {"window_lifetime", t_window_lifetime},
    {"window_slots_full", t_window_slots_full},
    {"item_pool_full_is_atomic", t_item_pool_full_is_atomic},
    {"invalid_arguments", t_invalid_arguments},
    {"stale_item_ids", t_stale_item_ids},
    {"text_compaction", t_text_compaction},
    {"minimal_updates", t_minimal_updates},
    {"events", t_events},
    {"menus", t_menus},
    {"sprite_free_removes_records", t_sprite_free_removes_records},
    {"sprite_trace", t_sprite_trace},
    {"random_seed_1", t_random_seed_1},
    {"random_seed_2", t_random_seed_2},
    {"random_seed_3", t_random_seed_3},
    {NULL, NULL},
};

int main(int argc, char **argv) {
    const char *only = argc > 1 ? argv[1] : NULL;
    int run = 0, failed = 0;
    for (const kd_test_case *t = tests; t->name; t++) {
        if (only && !strstr(t->name, only)) continue;
        kd_test_failed = 0;
        t->fn();
        run++;
        if (kd_test_failed) failed++;
        printf("%-4s %s\n", kd_test_failed ? "FAIL" : "ok", t->name);
    }
    printf("%d tests, %d failed\n", run, failed);
    return failed ? 1 : 0;
}
