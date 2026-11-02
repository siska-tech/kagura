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

static const kd_test_case tests[] = {
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
