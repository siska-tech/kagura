// SPDX-License-Identifier: Apache-2.0
// Benchmark workloads shared by kd_bench (host timing) and kd_count (Cortex-M0+
// instruction counts under qemu-arm). Each workload: setup once, then per
// sample an optional untimed pre-step and the measured op; render and TILE4
// export follow every step.
#ifndef KD_WORKLOADS_H
#define KD_WORKLOADS_H

#include <string.h>

#include "kd_shell.h"
#include "kd_tile4.h"

static kd_shell S;
static uint8_t vram[KD_TILE4_TOTAL];
static uint8_t staging[KD_TILE_COLS * KD_TILE4_BYTES];
static char sample_hex[KD_SAMPLE_SPRITES][KD_SPRITE_HEX + 1];

static bool to_vram(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    (void)ctx;
    memcpy(vram + first * KD_TILE4_BYTES, data, count * KD_TILE4_BYTES);
    return true;
}

static void flush(kd_tile4_stats *st) {
    kd_tile4_flush(&S.desk.fb, 0, staging, KD_TILE_COLS, to_vram, NULL, st);
}

static void workloads_init(void) {
    for (int i = 0; i < KD_SAMPLE_SPRITES; i++) kd_sample_sprite_hex(i, sample_hex[i]);
}

static void post_event(uint8_t type, int x, int y, uint8_t key, char ch) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.button = KD_BUTTON_LEFT;
    e.key = key;
    e.ch = ch;
    e.x = (int16_t)x;
    e.y = (int16_t)y;
    kd_desktop_event(&S.desk, &e);
}

// ---- workloads ----

static kd_rect title_point(kd_window *w) { return kd_frame_title(w->frame); }

static void setup_scene(void) { kd_shell_demo_scene(&S); }
static void setup_about(void) {
    kd_shell_demo_scene(&S);
    kd_shell_open_about(&S);
}
static void setup_three(void) {
    kd_shell_demo_scene(&S);
    kd_shell_open_about(&S);
    kd_desktop_move(&S.desk, S.about.win, 90, 70);
}
static void setup_painter(void) {
    setup_three();
    S.desk.painter = true;
}
static void setup_cursor(void) {
    kd_shell_demo_scene(&S);
    kd_desktop_set_cursor(&S.desk, true);
    post_event(KD_EV_POINTER_MOVE, 290, 120, 0, 0);
}
static void setup_live_drag(void) {
    kd_shell_demo_scene(&S);
    kd_rect t = title_point(S.studio.win);
    post_event(KD_EV_POINTER_DOWN, t.x + 60, t.y + 4, 0, 0);
}
static void setup_outline_drag(void) {
    kd_shell_demo_scene(&S);
    S.desk.outline_drag = true;
    kd_rect t = title_point(S.studio.win);
    post_event(KD_EV_POINTER_DOWN, t.x + 60, t.y + 4, 0, 0);
}
static void setup_outline_drop(void) {
    kd_shell_demo_scene(&S);
    S.desk.outline_drag = true;
}

static void op_none(int i) { (void)i; }
static void op_export_all(int i) {
    (void)i;
    kd_fb_mark_dirty_all(&S.desk.fb);   // resend every pattern (mode switch, resync)
}
static void op_full(int i) {
    (void)i;
    kd_desktop_invalidate(&S.desk, kd_rect_make(0, 0, KD_W, KD_H));
}
static void op_button(int i) {
    kd_rect ok = kd_about_ok_rect(), w = kd_window_work(S.about.win);
    if (i & 1) post_event(KD_EV_POINTER_UP, w.x + ok.x - 20, w.y + ok.y + 5, 0, 0);   // release outside
    else post_event(KD_EV_POINTER_DOWN, w.x + ok.x + 10, w.y + ok.y + 5, 0, 0);
}
static void pre_menu_closed(int i) {
    (void)i;
    kd_desktop_close_menu(&S.desk);
}
static void op_menu_open(int i) {
    (void)i;
    int x = kd_menu_title_x(S.desk.menus, KD_MENU_FILE) + 4;
    post_event(KD_EV_POINTER_DOWN, x, 4, 0, 0);
    post_event(KD_EV_POINTER_UP, x, 4, 0, 0);
}
static void pre_menu_open(int i) {
    (void)i;
    kd_desktop_open_menu(&S.desk, KD_MENU_FILE);
}
static void op_menu_close(int i) {
    (void)i;
    post_event(KD_EV_KEY, 0, 0, KD_KEY_ESCAPE, 0);
}
static void op_activate(int i) {
    (void)i;
    kd_desktop_activate(&S.desk, &S.desk.win[S.desk.z[0]]);
}
static void op_drag_move(int i) {
    int base_x = 118 + 60 + 1, base_y = 60 + 1 + 4;   // grab point of setup_*_drag
    post_event(KD_EV_POINTER_MOVE, base_x + ((i & 1) ? 0 : -8), base_y + ((i & 1) ? 0 : -8), 0, 0);
}
static void pre_outline_drag(int i) {
    kd_rect t = title_point(S.studio.win);
    post_event(KD_EV_POINTER_DOWN, t.x + 60, t.y + 4, 0, 0);
    post_event(KD_EV_POINTER_MOVE, t.x + 60 + ((i & 1) ? 8 : -8), t.y + 4 + ((i & 1) ? 8 : -8), 0, 0);
}
static void op_outline_drop(int i) {
    (void)i;
    kd_desktop *d = &S.desk;
    post_event(KD_EV_POINTER_UP, d->px, d->py, 0, 0);
}
static void op_label(int i) {
    kd_label_set(&S.desk, S.studio.win, &S.studio.pos_label, (i & 1) ? "X03 Y04" : "X03 Y05");
}
static void op_pixel(int i) { kd_studio_put(&S.studio, 5, 6, (i & 1) ? 9 : 3); }
static void op_import(int i) { kd_studio_import_hex(&S.studio, sample_hex[i & 1]); }
static void op_recompose(int i) {
    (void)i;
    kd_desktop_invalidate(&S.desk, kd_rect_make(100, 40, 160, 120));
}
static void op_cursor(int i) { post_event(KD_EV_POINTER_MOVE, 290 + ((i & 1) ? 4 : 0), 120 + ((i & 1) ? 4 : 0), 0, 0); }

typedef struct {
    const char *name, *what;
    void (*setup)(void);
    void (*pre)(int);
    void (*op)(int);
} workload;

static const workload workloads[] = {
    {"idle", "no change: render returns at once", setup_scene, NULL, op_none},
    {"full_redraw", "invalidate 320x200, 3 windows, region compose", setup_three, NULL, op_full},
    {"full_redraw_painter", "same, painter's algorithm", setup_painter, NULL, op_full},
    {"full_export", "export all 1,000 tiles (32,000 B), no drawing", setup_scene, NULL, op_export_all},
    {"button_press", "About OK pressed / released (pointer)", setup_about, NULL, op_button},
    {"menu_open", "click File title: dropdown over windows", setup_scene, pre_menu_closed, op_menu_open},
    {"menu_close", "Escape: recompose windows under dropdown", setup_scene, pre_menu_open, op_menu_close},
    {"window_activate", "raise the bottom of two overlapping windows", setup_scene, NULL, op_activate},
    {"window_move_live", "drag Studio 8 px diagonally, live", setup_live_drag, NULL, op_drag_move},
    {"window_move_outline", "drag outline 8 px diagonally", setup_outline_drag, NULL, op_drag_move},
    {"window_drop_outline", "release outline: window moves 8 px", setup_outline_drop, pre_outline_drag, op_outline_drop},
    {"label_one_char", "Studio position label, one glyph", setup_scene, NULL, op_label},
    {"sprite_pixel", "Studio: one sprite pixel", setup_scene, NULL, op_pixel},
    {"sprite_import", "Studio: import a full 16x16 sprite", setup_scene, NULL, op_import},
    {"recompose_overlap", "invalidate 160x120 across 3 windows", setup_three, NULL, op_recompose},
    {"recompose_overlap_painter", "same, painter's algorithm", setup_painter, NULL, op_recompose},
    {"pointer_move", "software cursor 4 px over desktop", setup_cursor, NULL, op_cursor},
};

#define KD_WORKLOAD_COUNT (sizeof workloads / sizeof workloads[0])

static inline uint32_t crc32_update(uint32_t c, const uint8_t *p, size_t n) {
    c = ~c;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1)));
    }
    return ~c;
}

// Deterministic correctness pass shared by every platform: setup, then k
// samples of (pre, render, export, op, render, export). Returns the CRC32 of
// the framebuffer followed by the exported VRAM copy; the RP2040 build must
// print the same value as the PC (kd_bench --crc).
static inline uint32_t workload_crc(const workload *w, int k) {
    kd_tile4_stats st;
    memset(vram, 0, sizeof vram);
    w->setup();
    kd_desktop_render(&S.desk);
    flush(&st);
    for (int i = 0; i < k; i++) {
        if (w->pre) {
            w->pre(i);
            kd_desktop_render(&S.desk);
            flush(&st);
        }
        w->op(i);
        kd_desktop_render(&S.desk);
        flush(&st);
    }
    return crc32_update(crc32_update(0, S.desk.fb.px, KD_FB_BYTES), vram, sizeof vram);
}

#endif
