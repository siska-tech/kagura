// SPDX-License-Identifier: Apache-2.0
// KAGURA Studio mock: 16x16 4bpp sprite editor (zoomed grid, palette, 1:1 and
// 2:1 previews). The sprite is real TILE4 data (kd_sprite). Colour 0 is the
// sprite's transparent colour and is shown over a checkerboard using the
// keyed blit; the desktop itself never treats colour 0 as transparent.
#include <string.h>

#include "kd_shell.h"

#define GX KD_STUDIO_GX
#define GY KD_STUDIO_GY
#define Z KD_STUDIO_ZOOM
#define GW (KD_SPRITE_W * Z)
#define P1X 108          // 1:1 preview
#define P2X 130          // 2:1 preview
#define PY 4
#define SWX 108          // palette swatches, 8 per row, pitch 9
#define SWY 42
#define SWP 9

static const uint8_t checker[8] = {0xF0, 0xF0, 0xF0, 0xF0, 0x0F, 0x0F, 0x0F, 0x0F};

// Palette indices per pixel, '0' transparent.
static const char *const sample_art[KD_SAMPLE_SPRITES][16] = {
    {"0000000000000000",
     "0000000000000000",
     "0000001111000000",
     "00001188dd110000",
     "000118dddddd1000",
     "00118dddddddd100",
     "0018dd21dd21dd10",
     "0018dd11dd11dd10",
     "018dddddddddddd1",
     "018ddd6dddd6ddd1",
     "018dddd6666dddd1",
     "0188dddddddddd81",
     "0018888888888810",
     "0001111111111100",
     "0000000000000000",
     "0000000000000000"},
    {"0000000000000000",
     "0011100000111000",
     "0166610001666100",
     "1666661016666610",
     "1662666166666610",
     "1626666666666610",
     "1666666666666610",
     "1666666666666610",
     "0166666666666100",
     "0016666666661000",
     "0001666666610000",
     "0000166666100000",
     "0000016661000000",
     "0000001610000000",
     "0000000100000000",
     "0000000000000000"},
};

void kd_sample_sprite(int i, kd_sprite *out) {
    memset(out, 0, sizeof *out);
    for (int y = 0; y < KD_SPRITE_H; y++)
        for (int x = 0; x < KD_SPRITE_W; x++) {
            char c = sample_art[i][y][x];
            kd_sprite_set(out, x, y, c <= '9' ? c - '0' : c - 'a' + 10);
        }
}

void kd_sample_sprite_hex(int i, char out[KD_SPRITE_HEX + 1]) {
    kd_sprite s;
    kd_sample_sprite(i, &s);
    kd_sprite_export_hex(&s, out);
}

static kd_rect cell_rect(int x, int y) { return kd_rect_make(GX + x * Z, GY + y * Z, Z, Z); }

static kd_rect swatch_rect(int c) {
    return kd_rect_make(SWX + (c % 8) * SWP, SWY + (c / 8) * SWP, SWP - 1, SWP - 1);
}

static kd_rect swatch_outline(int c) {
    kd_rect r = swatch_rect(c);
    return kd_rect_make(r.x - 1, r.y - 1, r.w + 2, r.h + 2);
}

static void invalidate(kd_studio *st, kd_rect r) {
    if (st->win) kd_window_invalidate(kd_window_desktop(st->win), st->win, r);
}

static void invalidate_pixel(kd_studio *st, int x, int y) {
    invalidate(st, cell_rect(x, y));
    invalidate(st, kd_rect_make(P1X + x, PY + y, 1, 1));
    invalidate(st, kd_rect_make(P2X + 2 * x, PY + 2 * y, 2, 2));
}

// Replaces the sprite. Up to 16 changed pixels are invalidated one by one,
// more as the whole grid and previews (the KAGURA-UI #67 rule).
static void replace(kd_studio *st, const kd_sprite *next) {
    int changed = 0;
    for (int y = 0; y < KD_SPRITE_H; y++)
        for (int x = 0; x < KD_SPRITE_W; x++)
            changed += kd_sprite_get(&st->sprite, x, y) != kd_sprite_get(next, x, y);
    if (changed > 16) {
        invalidate(st, kd_rect_make(GX, GY, GW, GW));
        invalidate(st, kd_rect_make(P1X, PY, 16, 16));
        invalidate(st, kd_rect_make(P2X, PY, 32, 32));
    } else if (changed) {
        for (int y = 0; y < KD_SPRITE_H; y++)
            for (int x = 0; x < KD_SPRITE_W; x++)
                if (kd_sprite_get(&st->sprite, x, y) != kd_sprite_get(next, x, y)) invalidate_pixel(st, x, y);
    }
    st->sprite = *next;
}

static void labels(kd_studio *st) {
    static const char hex[] = "0123456789ABCDEF";
    char color[] = "COLOUR 0", pos[] = "X00 Y00";
    color[7] = hex[st->color];
    pos[1] = (char)('0' + st->cx / 10);
    pos[2] = (char)('0' + st->cx % 10);
    pos[5] = (char)('0' + st->cy / 10);
    pos[6] = (char)('0' + st->cy % 10);
    if (st->win) {
        kd_desktop *d = kd_window_desktop(st->win);
        kd_label_set(d, st->win, &st->color_label, color);
        kd_label_set(d, st->win, &st->pos_label, pos);
    } else {
        kd_label_init(&st->color_label, SWX, 64, 8, color);
        kd_label_init(&st->pos_label, SWX, 74, 7, pos);
    }
}

bool kd_studio_put(kd_studio *st, int x, int y, int color) {
    if (!kd_sprite_set(&st->sprite, x, y, color)) return false;
    invalidate_pixel(st, x, y);
    return true;
}

void kd_studio_set_cursor(kd_studio *st, int x, int y) {
    x = x < 0 ? 0 : x > 15 ? 15 : x;
    y = y < 0 ? 0 : y > 15 ? 15 : y;
    if (x == st->cx && y == st->cy) return;
    invalidate(st, cell_rect(st->cx, st->cy));
    st->cx = x;
    st->cy = y;
    invalidate(st, cell_rect(x, y));
    labels(st);
}

void kd_studio_set_color(kd_studio *st, int color) {
    if (color < 0 || color > 15 || color == st->color) return;
    invalidate(st, swatch_outline(st->color));
    st->color = color;
    invalidate(st, swatch_outline(color));
    labels(st);
}

static void remember(kd_studio *st) {
    st->undo = st->sprite;
    st->has_undo = true;
}

bool kd_studio_import_hex(kd_studio *st, const char *hex) {
    kd_sprite next = st->sprite;
    if (!kd_sprite_import_hex(&next, hex, NULL)) return false;
    remember(st);
    replace(st, &next);
    return true;
}

void kd_studio_export_hex(const kd_studio *st, char out[KD_SPRITE_HEX + 1]) {
    kd_sprite_export_hex(&st->sprite, out);
}

void kd_studio_undo(kd_studio *st) {
    if (!st->has_undo) return;
    kd_sprite previous = st->undo;
    st->undo = st->sprite;
    replace(st, &previous);
}

static void studio_draw(kd_window *w, const kd_draw *d) {
    kd_studio *st = kd_window_user(w);
    kd_draw_fill(d, 0, 0, d->w, d->h, KD_C_WHITE);
    kd_draw_rect(d, GX - 1, GY - 1, GW + 2, GW + 2, KD_C_BLACK);
    if (kd_draw_visible(d, kd_rect_make(GX, GY, GW, GW))) {
        kd_draw_pattern(d, GX, GY, GW, GW, checker, KD_C_WHITE, KD_C_LGREY);
        kd_draw_sprite(d, GX, GY, &st->sprite, Z, 0);
        if (kd_window_is_active(w)) {
            kd_rect c = cell_rect(st->cx, st->cy);
            kd_draw_rect(d, c.x, c.y, c.w, c.h, KD_C_BLACK);
            kd_draw_rect(d, c.x + 1, c.y + 1, c.w - 2, c.h - 2, KD_C_WHITE);
        }
    }
    kd_draw_rect(d, P1X - 1, PY - 1, 18, 18, KD_C_BLACK);
    kd_draw_pattern(d, P1X, PY, 16, 16, checker, KD_C_WHITE, KD_C_LGREY);
    kd_draw_sprite(d, P1X, PY, &st->sprite, 1, 0);
    kd_draw_rect(d, P2X - 1, PY - 1, 34, 34, KD_C_BLACK);
    kd_draw_pattern(d, P2X, PY, 32, 32, checker, KD_C_WHITE, KD_C_LGREY);
    kd_draw_sprite(d, P2X, PY, &st->sprite, 2, 0);
    for (int c = 0; c < 16; c++) {
        kd_rect r = swatch_rect(c);
        if (c == 0) kd_draw_pattern(d, r.x, r.y, r.w, r.h, checker, KD_C_WHITE, KD_C_LGREY);
        else kd_draw_fill(d, r.x, r.y, r.w, r.h, (uint8_t)c);
        if (c == st->color) {
            kd_rect o = swatch_outline(c);
            kd_draw_rect(d, o.x, o.y, o.w, o.h, KD_C_BLACK);
        }
    }
    kd_draw_label(d, &st->color_label, KD_C_BLACK, KD_C_WHITE);
    kd_draw_label(d, &st->pos_label, KD_C_BLACK, KD_C_WHITE);
    kd_draw_text(d, &kd_font_small, 4, 104, "ARROWS MOVE  SPACE PAINT  0-F COLOUR  U UNDO",
                 KD_C_DGREY, KD_NO_KEY);
}

static bool grid_cell(const kd_event *ev, int *x, int *y) {
    if (ev->x < GX || ev->y < GY || ev->x >= GX + GW || ev->y >= GY + GW) return false;
    *x = (ev->x - GX) / Z;
    *y = (ev->y - GY) / Z;
    return true;
}

static int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool studio_event(kd_window *w, const kd_event *ev) {
    kd_studio *st = kd_window_user(w);
    int x, y;
    switch (ev->type) {
    case KD_EV_FOCUS: case KD_EV_BLUR:
        invalidate(st, cell_rect(st->cx, st->cy));   // cursor shows only when active
        return true;
    case KD_EV_POINTER_DOWN:
        if (grid_cell(ev, &x, &y)) {
            remember(st);
            st->painting = true;
            kd_studio_set_cursor(st, x, y);
            kd_studio_put(st, x, y, st->color);
            return true;
        }
        for (int c = 0; c < 16; c++)
            if (kd_rect_has_point(swatch_outline(c), ev->x, ev->y)) {
                kd_studio_set_color(st, c);
                return true;
            }
        return false;
    case KD_EV_POINTER_MOVE:
        if (st->painting && grid_cell(ev, &x, &y)) {
            kd_studio_set_cursor(st, x, y);
            kd_studio_put(st, x, y, st->color);
        }
        return true;
    case KD_EV_POINTER_UP:
        st->painting = false;
        return true;
    case KD_EV_KEY:
        switch (ev->key) {
        case KD_KEY_LEFT: kd_studio_set_cursor(st, st->cx - 1, st->cy); return true;
        case KD_KEY_RIGHT: kd_studio_set_cursor(st, st->cx + 1, st->cy); return true;
        case KD_KEY_UP: kd_studio_set_cursor(st, st->cx, st->cy - 1); return true;
        case KD_KEY_DOWN: kd_studio_set_cursor(st, st->cx, st->cy + 1); return true;
        case KD_KEY_ENTER:
            remember(st);
            kd_studio_put(st, st->cx, st->cy, st->color);
            return true;
        case KD_KEY_DELETE: case KD_KEY_BACKSPACE:
            remember(st);
            kd_studio_put(st, st->cx, st->cy, 0);
            return true;
        case KD_KEY_CHAR:
            if (ev->ch == ' ') {
                remember(st);
                kd_studio_put(st, st->cx, st->cy, st->color);
            } else if (ev->ch == 'u' || ev->ch == 'U') {
                kd_studio_undo(st);
            } else if (hex_value(ev->ch) >= 0) {
                kd_studio_set_color(st, hex_value(ev->ch));
            } else {
                return false;
            }
            return true;
        default: return false;
        }
    default: return false;
    }
}

static void studio_closed(kd_window *w) {
    kd_studio *st = kd_window_user(w);
    st->win = NULL;
    st->painting = false;
}

static const kd_window_class studio_class = {studio_draw, studio_event, studio_closed};

void kd_studio_init(kd_studio *st, kd_shell *shell) {
    memset(st, 0, sizeof *st);
    st->shell = shell;
    kd_sample_sprite(0, &st->sprite);
    st->color = 13;
    labels(st);
}

kd_window *kd_shell_open_studio(kd_shell *s) {
    kd_studio *st = &s->studio;
    if (st->win) {
        kd_desktop_activate(&s->desk, st->win);
        return st->win;
    }
    kd_rect frame = kd_rect_make(118, 60, KD_STUDIO_W + 2, KD_STUDIO_H + KD_TITLE_H + 2);
    st->win = kd_window_open(&s->desk, &studio_class, st, "KAGURA Studio", frame, KD_WF_CLOSE | KD_WF_MOVE);
    return st->win;
}
