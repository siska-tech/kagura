// SPDX-License-Identifier: Apache-2.0
// Native C reference for demo/demo.py: the same windows, content, input and
// application logic, written directly against kd_app.h. It uses neither kdm
// nor MicroPython: window content is drawn by hand-written draw callbacks
// and events are handled synchronously in the window classes. Any change
// simply invalidates the whole window (the compositor's exact dirty map
// makes the export independent of how much was invalidated).
//
// Prints the same STEP lines as the demo; tests/run_tests.sh compares them.
#include <stdio.h>
#include <string.h>

#include "kd_desktop.h"
#include "kd_tile4.h"

static const char *const FACE =
    "00000000000000000000001100001188000118dd00118ddd0018dd210018dd11"
    "000000000000000011000000dd110000dddd1000ddddd100dd21dd10dd11dd10"
    "018ddddd018ddd6d018dddd60188dddd00188888000111110000000000000000"
    "ddddddd1ddd6ddd1666dddd1dddddd8188888810111111000000000000000000";
static const char *const HEART =
    "0000000000111000016661001666661016626661162666661666666616666666"
    "0000000000111000016661001666661066666610666666106666661066666610"
    "0166666600166666000166660000166600000166000000160000000100000000"
    "6666610066661000666100006610000061000000100000000000000000000000";

enum { GRID_X = 4, GRID_Y = 4, ZOOM = 6, SWATCH_X = 108, SWATCH_Y = 60 };
static const kd_rect OK_BOX = {100, 4, 56, 14};

static const kd_menu_item desk_items[] = {{"About demo", false, false}, {"-", false, false}, {"Quit", false, false}, {NULL, false, false}};
static const kd_menu_item window_items[] = {{"Close", false, false}, {"Cycle", false, false}, {NULL, false, false}};
static const kd_menu menus[] = {{"Desk", desk_items}, {"Window", window_items}, {NULL, NULL}};

static kd_desktop desk;
static kd_window *notes, *paint;
static kd_sprite spr;
static char hello[16] = "Hello", typed[16], status[24] = "status: -", colour_label[16] = "COLOUR 6";
static bool pressed;
static int colour = 6;
static uint32_t t;
static uint8_t vram[KD_TILE4_TOTAL], staging[KD_TILE_COLS * KD_TILE4_BYTES];

static uint32_t crc32(uint32_t c, const uint8_t *p, size_t n) {
    c = ~c;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1)));
    }
    return ~c;
}

static void changed(kd_window *w) {
    if (w && w->open) kd_window_invalidate_all(&desk, w);
}

static void draw_notes(kd_window *w, const kd_draw *d) {
    (void)w;
    kd_draw_fill(d, 0, 0, d->w, d->h, KD_C_WHITE);
    kd_draw_fill(d, 4, 4, 60, 20, 12);
    kd_draw_rect(d, 4, 4, 60, 20, 1);
    kd_draw_text(d, &kd_font_system, 8, 10, hello, 1, KD_NO_KEY);
    kd_draw_text(d, &kd_font_system, 4, 30, "Typed:", 1, KD_NO_KEY);
    kd_draw_text(d, &kd_font_system, 56, 30, typed, 5, KD_NO_KEY);
    kd_draw_text(d, &kd_font_small, 4, 44, status, 4, KD_NO_KEY);
    kd_draw_button(d, OK_BOX, "OK", pressed ? KD_BTN_PRESSED : 0);
    kd_draw_hline(d, 4, 60, 152, 4);
}

static void draw_paint(kd_window *w, const kd_draw *d) {
    (void)w;
    kd_draw_fill(d, 0, 0, d->w, d->h, KD_C_LGREY);
    kd_draw_sprite(d, GRID_X, GRID_Y, &spr, ZOOM, KD_NO_KEY);
    kd_draw_sprite(d, 108, 4, &spr, 1, KD_NO_KEY);
    kd_draw_sprite(d, 108, 24, &spr, 2, 0);
    for (int i = 0; i < 16; i++) kd_draw_fill(d, SWATCH_X + i % 4 * 14, SWATCH_Y + i / 4 * 10, 12, 8, (uint8_t)i);
    kd_draw_text(d, &kd_font_system, 100, 102, colour_label, 1, 3);
}

static void set_status(kd_window *focused) {
    snprintf(status, sizeof status, "status: %s", focused == notes ? "Notes" : "Sprite");
    changed(notes);
}

static bool notes_event(kd_window *w, const kd_event *ev) {
    bool inside = kd_rect_has_point(OK_BOX, ev->x, ev->y);
    if (ev->type == KD_EV_FOCUS) {
        set_status(w);
    } else if (ev->type == KD_EV_KEY) {
        size_t n = strlen(typed);
        if (ev->key == KD_KEY_CHAR && n + 1 < sizeof typed) typed[n] = ev->ch;
        else if (ev->key == KD_KEY_BACKSPACE && n) typed[n - 1] = 0;
    } else if (ev->type == KD_EV_POINTER_DOWN && inside) {
        pressed = true;
    } else if (ev->type == KD_EV_POINTER_UP && pressed) {
        pressed = false;
        if (inside) strcpy(hello, "Clicked");
    }
    changed(w);
    return true;
}

static bool paint_event(kd_window *w, const kd_event *ev) {
    if (ev->type == KD_EV_FOCUS) {
        set_status(w);
    } else if (ev->type == KD_EV_POINTER_DOWN || ev->type == KD_EV_POINTER_MOVE) {
        int x = ev->x - GRID_X, y = ev->y - GRID_Y;
        if (x >= 0 && x < 16 * ZOOM && y >= 0 && y < 16 * ZOOM) {
            kd_sprite_set(&spr, x / ZOOM, y / ZOOM, colour);
        } else if (ev->type == KD_EV_POINTER_DOWN && ev->x >= SWATCH_X && ev->y >= SWATCH_Y) {
            int sx = (ev->x - SWATCH_X) / 14, sy = (ev->y - SWATCH_Y) / 10;
            if (sx < 4 && sy < 4) {
                colour = sy * 4 + sx;
                snprintf(colour_label, sizeof colour_label, "COLOUR %d", colour);
            }
        }
    }
    changed(w);
    return true;
}

static void paint_closed(kd_window *w) {
    (void)w;
    memset(&spr, 0, sizeof spr);   // the demo frees its sprite
}

static const kd_window_class notes_class = {draw_notes, notes_event, NULL};
static const kd_window_class paint_class = {draw_paint, paint_event, paint_closed};

static void menu_hook(kd_desktop *d, int menu, int item, void *ctx) {
    (void)ctx;
    kd_window *top = kd_desktop_top(d);
    if (menu == 1 && item == 0 && top) kd_window_close(d, top);
}

static void ev(uint8_t type, int x, int y) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.button = KD_BUTTON_LEFT;
    e.x = (int16_t)x;
    e.y = (int16_t)y;
    e.time_ms = t += 250;
    kd_desktop_event(&desk, &e);
}

static void click(int x, int y) {
    ev(KD_EV_POINTER_DOWN, x, y);
    ev(KD_EV_POINTER_UP, x, y);
}

static void key(uint8_t k, char ch) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = KD_EV_KEY;
    e.key = k;
    e.ch = ch;
    e.time_ms = t += 250;
    kd_desktop_event(&desk, &e);
}

static void drag(int x, int y, int dx, int dy, int steps) {
    ev(KD_EV_POINTER_DOWN, x, y);
    for (int i = 1; i <= steps; i++) ev(KD_EV_POINTER_MOVE, x + dx * i / steps, y + dy * i / steps);
    ev(KD_EV_POINTER_UP, x + dx, y + dy);
}

static bool to_vram(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    (void)ctx;
    memcpy(vram + first * KD_TILE4_BYTES, data, count * KD_TILE4_BYTES);
    return true;
}

static void step(const char *name) {
    kd_tile4_stats st;
    kd_desktop_render(&desk);
    kd_tile4_flush(&desk.fb, 0, staging, KD_TILE_COLS, to_vram, NULL, &st);
    printf("STEP %s %08lx %08lx %lu\n", name, (unsigned long)crc32(0, desk.fb.px, KD_FB_BYTES),
           (unsigned long)crc32(0, vram, sizeof vram), (unsigned long)st.tiles);
}

int main(void) {
    kd_shell_hooks hooks = {menu_hook, NULL, NULL};
    kd_desktop_init(&desk, menus, NULL, 0, hooks);
    kd_desktop_set_cursor(&desk, true);
    kd_sprite_import_hex(&spr, HEART, NULL);
    notes = kd_window_open(&desk, &notes_class, NULL, "Notes", kd_rect_make(12, 20, 168, 100), KD_WF_CLOSE | KD_WF_MOVE);
    paint = kd_window_open(&desk, &paint_class, NULL, "Sprite", kd_rect_make(128, 60, 180, 128), KD_WF_CLOSE | KD_WF_MOVE);

    step("open");
    click(40, 24);
    step("focus");
    key(KD_KEY_CHAR, 'H');
    key(KD_KEY_CHAR, 'i');
    key(KD_KEY_CHAR, '!');
    key(KD_KEY_BACKSPACE, 0);
    key(KD_KEY_CHAR, '?');
    step("typing");
    kd_rect nw = kd_window_work(notes);
    ev(KD_EV_POINTER_DOWN, nw.x + 120, nw.y + 10);
    step("press");
    ev(KD_EV_POINTER_UP, nw.x + 120, nw.y + 10);
    step("release");
    click(250, 64);
    kd_rect pw = kd_window_work(paint);
    click(pw.x + SWATCH_X + 2 * 14 + 6, pw.y + SWATCH_Y + 3 * 10 + 4);
    drag(pw.x + GRID_X + 3 * ZOOM + 3, pw.y + GRID_Y + 5 * ZOOM + 3, 7 * ZOOM, 0, 7);
    step("paint");
    kd_sprite_import_hex(&spr, FACE, NULL);
    changed(paint);
    step("import");
    drag(40, 24, 24, 40, 3);
    step("move");
    ev(KD_EV_POINTER_DOWN, 60, 4);
    ev(KD_EV_POINTER_MOVE, 62, 15);
    ev(KD_EV_POINTER_UP, 62, 15);
    step("menu");
    kd_rect pf = kd_window_frame(paint);
    click(pf.x + 5, pf.y + 5);
    step("closebox");
    return 0;
}
