// SPDX-License-Identifier: Apache-2.0
// Pure-C side of the stage 3A comparison: the workloads of bench_binding.py
// driven through kdm directly (same scene, same records, same present into a
// TILE4 mirror), so the difference to the MicroPython run is the cost of the
// VM and the binding. Each workload prints its p50/p90/max per-iteration time
// (op + present) and the framebuffer and mirror CRCs, which the MicroPython
// run must reproduce.
//   kdm_bench [--quick]
#define _POSIX_C_SOURCE 199309L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "kdm.h"

static const char *const HEX[2] = {
    "00000000000000000000001100001188000118dd00118ddd0018dd210018dd11"
    "000000000000000011000000dd110000dddd1000ddddd100dd21dd10dd11dd10"
    "018ddddd018ddd6d018dddd60188dddd00188888000111110000000000000000"
    "ddddddd1ddd6ddd1666dddd1dddddd8188888810111111000000000000000000",
    "0000000000111000016661001666661016626661162666661666666616666666"
    "0000000000111000016661001666661066666610666666106666661066666610"
    "0166666600166666000166660000166600000166000000160000000100000000"
    "6666610066661000666100006610000061000000100000000000000000000000",
};

static kdm M;
static uint8_t vram[KD_TILE4_TOTAL];
static int g, s2, rw, spr, label, panel, button, rects_n;
static uint8_t sprite_data[2][KD_SPRITE_BYTES];
static int16_t quads[256 * 4];
static uint32_t events_seen[32], tick;
static bool batched;

static bool to_vram(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    (void)ctx;
    memcpy(vram + first * KD_TILE4_BYTES, data, count * KD_TILE4_BYTES);
    return true;
}

static void present(void) { kdm_present(&M, to_vram, NULL, NULL); }

static void gallery_content(int value) {
    char s[4];
    snprintf(s, sizeof s, "%d", value);
    label = kdm_add_text(&M, g, 8, 8, s, strlen(s), 1, 2, 0);
    panel = kdm_add_fill(&M, g, 100, 40, 32, 32, 4);
    button = kdm_add_button(&M, g, 8, 40, 40, 14, "GO", 2, 0);
    for (int k = 0; k < 6; k++) {
        char item[2] = {(char)('A' + k), 0};
        kdm_add_text(&M, g, 140, 8 + k * 10, item, 1, 1, -1, 0);
    }
}

static void scene(void) {
    kdm_menu_def def = {2, {"Desk", "Window"}, {{"About demo", "-", "Quit"}, {"Close", "Cycle"}}, {3, 2}};
    kdm_init(&M, &def);
    kd_desktop_set_cursor(&M.desk, true);
    g = kdm_window_open(&M, "Gallery", kd_rect_make(8, 16, 200, 120), KD_WF_CLOSE | KD_WF_MOVE, 2);
    gallery_content(0);
    spr = kdm_sprite_alloc(&M, sprite_data[1]);
    s2 = kdm_window_open(&M, "Sprite", kd_rect_make(120, 40, 190, 150), KD_WF_CLOSE | KD_WF_MOVE, 3);
    kdm_add_sprite(&M, s2, 4, 4, spr, 6, -1);
    kdm_add_sprite(&M, s2, 108, 4, spr, 1, -1);
    kdm_add_sprite(&M, s2, 108, 24, spr, 2, 0);
    for (int i = 0; i < 16; i++) kdm_add_fill(&M, s2, 108 + i % 4 * 14, 60 + i / 4 * 10, 12, 8, (uint8_t)i);
    kdm_add_text(&M, s2, 100, 102, "COLOUR 6", 8, 1, 3, 0);
    memset(vram, 0, sizeof vram);
    present();
    kdm_event e;
    while (kdm_peek(&M, &e)) kdm_drop(&M);
}

// ---- operations (i is the iteration, from -4 for warm-up) ----

static void op_idle(int i) { (void)i; }
static void op_full(int i) { (void)i; kd_desktop_invalidate(&M.desk, kd_rect_make(0, 0, KD_W, KD_H)); }
static void op_label(int i) {
    char s[2] = {(char)('0' + (i + 10) % 10), 0};
    kdm_item_set_text(&M, g, label, s, 1);
}
static void op_button(int i) { kdm_item_set_flags(&M, g, button, (i & 1) ? KD_BTN_PRESSED : 0); }
static void op_panel(int i) { kdm_item_move(&M, g, panel, 100 + (i & 1) * 4, 40); }
static void op_pixel(int i) { kdm_sprite_set(&M, spr, 5, 6, (i & 1) ? 9 : 3); }
static void op_pixels16(int i) {
    uint8_t xyc[48];
    for (int x = 0; x < 16; x++) {
        xyc[3 * x] = (uint8_t)x;
        xyc[3 * x + 1] = (uint8_t)((i + 16) % 16);
        xyc[3 * x + 2] = (uint8_t)((i + 15) % 15 + 1);
    }
    if (batched) {
        kdm_sprite_set_many(&M, spr, xyc, 16);
    } else {
        for (int x = 0; x < 16; x++) kdm_sprite_set(&M, spr, xyc[3 * x], xyc[3 * x + 1], xyc[3 * x + 2]);
    }
}
static void op_import(int i) { kdm_sprite_load(&M, spr, sprite_data[i & 1]); }
static void op_activate(int i) { kdm_window_activate(&M, (i & 1) ? g : s2); }
static void op_move(int i) { kdm_window_move(&M, s2, 120 + (i & 1) * 8, 40); }
static void op_open_close(int i) {
    (void)i;
    int w = kdm_window_open(&M, "Tmp", kd_rect_make(60, 50, 120, 80), KD_WF_CLOSE | KD_WF_MOVE, 2);
    kdm_add_text(&M, w, 4, 4, "temporary", 9, 1, -1, 0);
    kdm_add_fill(&M, w, 4, 20, 60, 20, 5);
    present();
    kdm_window_close(&M, w);
}
static void op_rects(int i) {
    kdm_window_clear(&M, rw, -1);
    for (int k = 0; k < rects_n; k++) quads[4 * k + 0] = (int16_t)((k * 37 + i * 8 + 800) % 260);
    if (batched) {
        kdm_add_fills(&M, rw, quads, rects_n, (uint8_t)((i + 16) % 16));
    } else {
        for (int k = 0; k < rects_n; k++)
            kdm_add_fill(&M, rw, quads[4 * k], quads[4 * k + 1], quads[4 * k + 2], quads[4 * k + 3], (uint8_t)((i + 16) % 16));
    }
}
static void op_rebuild(int i) {
    kdm_window_clear(&M, g, -1);
    gallery_content((i + 10) % 10);
}
static void op_events(int i) {
    kd_rect w = kd_window_work(&M.desk.win[g]);
    kd_event e;
    memset(&e, 0, sizeof e);
    e.button = KD_BUTTON_LEFT;
    e.x = (int16_t)(w.x + 60 + (i & 1));
    e.y = (int16_t)(w.y + 80);
    e.type = KD_EV_POINTER_DOWN;
    e.time_ms = tick += 1000;
    kdm_feed(&M, &e);
    e.type = KD_EV_POINTER_UP;
    e.time_ms = tick += 100;
    kdm_feed(&M, &e);
    e.type = KD_EV_KEY;
    e.key = KD_KEY_CHAR;
    e.ch = 'a';
    e.time_ms = tick += 100;
    kdm_feed(&M, &e);
    kdm_event ev;
    while (kdm_peek(&M, &ev)) {   // dispatch: count by type and window
        events_seen[ev.ev.type & 31] += (unsigned)ev.win + 1;
        kdm_drop(&M);
    }
}

typedef struct {
    const char *name;
    void (*op)(int);
    int iterations;
    int rects;      // rects workloads: count; 0 otherwise
    bool batched;
} workload;

static const workload workloads[] = {
    {"idle", op_idle, 200, 0, false},
    {"full_redraw", op_full, 100, 0, false},
    {"label_one_char", op_label, 200, 0, false},
    {"button_press", op_button, 200, 0, false},
    {"panel_move_4px", op_panel, 200, 0, false},
    {"window_rebuild", op_rebuild, 200, 0, false},
    {"sprite_pixel", op_pixel, 200, 0, false},
    {"sprite_16px_calls", op_pixels16, 200, 0, false},
    {"sprite_16px_batched", op_pixels16, 200, 0, true},
    {"sprite_import", op_import, 100, 0, false},
    {"window_activate", op_activate, 100, 0, false},
    {"window_move_8px", op_move, 100, 0, false},
    {"window_open_close", op_open_close, 100, 0, false},
    {"events_3", op_events, 200, 0, false},
    {"rects_1_calls", op_rects, 200, 1, false},
    {"rects_16_calls", op_rects, 200, 16, false},
    {"rects_256_calls", op_rects, 50, 256, false},
    {"rects_16_batched", op_rects, 200, 16, true},
    {"rects_256_batched", op_rects, 50, 256, true},
};

static double now_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e6 + ts.tv_nsec / 1e3;
}

static int cmp_double(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return x < y ? -1 : x > y;
}

int main(int argc, char **argv) {
    bool quick = argc > 1 && strcmp(argv[1], "--quick") == 0;
    for (int k = 0; k < 2; k++) kd_sprite_import_hex((kd_sprite *)sprite_data[k], HEX[k], NULL);
    for (int k = 0; k < 256; k++) {
        quads[4 * k + 1] = (int16_t)((k * 23) % 140);
        quads[4 * k + 2] = (int16_t)(12 + (k % 5) * 4);
        quads[4 * k + 3] = (int16_t)(8 + (k % 3) * 4);
    }
    printf("# kdm_bench: pure C through kdm (op + present into a TILE4 mirror), per iteration\n");
    printf("| workload | mean us | p50 us | p90 us | max us | tiles | fb crc | vram crc |\n"
           "|---|---:|---:|---:|---:|---:|---:|---:|\n");
    static double t[200];
    for (unsigned w = 0; w < sizeof workloads / sizeof workloads[0]; w++) {
        const workload *wl = &workloads[w];
        int n = quick ? 8 : wl->iterations;
        rects_n = wl->rects;
        batched = wl->batched;
        double mean = 0;
        uint32_t tiles = 0;
        for (int pass = 0; pass < 2; pass++) {   // as bench_binding.py: whole-loop mean, then per iteration
            uint32_t tick_start = tick;
            scene();
            if (wl->rects) {
                rw = kdm_window_open(&M, "Rects", kd_rect_make(4, 14, 312, 184), KD_WF_CLOSE | KD_WF_MOVE, 2);
                present();
            }
            if (pass == 0) {
                for (int i = -4; i < 0; i++) wl->op(i), present();
                double t0 = now_us();
                for (int i = 0; i < n; i++) wl->op(i), present();
                mean = (now_us() - t0) / n;
                tick = tick_start;
                continue;
            }
            for (int i = -4; i < n; i++) {
                double t0 = now_us();
                wl->op(i);
                int k = kdm_present(&M, to_vram, NULL, NULL);
                double t1 = now_us();
                if (i >= 0) {
                    t[i] = t1 - t0;
                    tiles += (uint32_t)k;
                }
            }
        }
        qsort(t, (size_t)n, sizeof t[0], cmp_double);
        printf("| %s | %.2f | %.2f | %.2f | %.2f | %.1f | %08lx | %08lx |\n", wl->name, mean, t[n / 2],
               t[(n - 1) * 9 / 10], t[n - 1], (double)tiles / n,
               (unsigned long)kdm_crc32(0, M.desk.fb.px, KD_FB_BYTES), (unsigned long)kdm_crc32(0, vram, sizeof vram));
    }
    printf("# sizeof(kdm) %zu, kd_desktop %zu, records %zu, text %zu, sprites %zu, events %zu\n", sizeof M,
           sizeof M.desk, sizeof M.items, sizeof M.text, sizeof M.sprites, sizeof M.ring);
    return 0;
}

