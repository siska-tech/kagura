// SPDX-License-Identifier: Apache-2.0
// Layer B: GEM-style drawing of desktop elements. Stateless: every call draws
// into the framebuffer through its current clip. Geometry constants here are
// shared with the window manager (hit testing must match what is drawn).
#ifndef KD_GFX_H
#define KD_GFX_H

#include "kd_fb.h"
#include "kd_font.h"

enum {
    KD_C_DESK = 0, KD_C_BLACK = 1, KD_C_WHITE = 2, KD_C_LGREY = 3,
    KD_C_DGREY = 4, KD_C_BLUE = 5, KD_C_RED = 6, KD_C_YELLOW = 7,
    KD_C_DGREEN = 8, KD_C_CYAN = 9, KD_C_MAGENTA = 10, KD_C_BROWN = 11,
    KD_C_LBLUE = 12, KD_C_LGREEN = 13, KD_C_ORANGE = 14, KD_C_CREAM = 15,
};

// 0xRGB (4 bits per channel), the format of KAGURA-9 palette writes.
extern const uint16_t kd_palette_rgb444[16];

#define KD_MENU_H 11          // menu bar rows 0..10, line at 10
#define KD_MENU_ITEM_H 10
#define KD_TITLE_H 11         // title bar inside the frame, separator below
#define KD_CLOSE_W 11
#define KD_ICON_W 16
#define KD_ICON_H 16
#define KD_CURSOR_W 11
#define KD_CURSOR_H 16

// String art: ' ' transparent, '#' ink, '-' paper, 'A'..'P' palette 0..15.
typedef struct {
    uint8_t w, h;
    const char *const *rows;
} kd_art;

extern const kd_art kd_art_cursor, kd_art_folder, kd_art_file, kd_art_drive,
    kd_art_trash, kd_art_studio, kd_art_app, kd_art_text;

void kd_gfx_art(kd_fb *fb, int x, int y, const kd_art *a, uint8_t ink, uint8_t paper);

void kd_gfx_desktop(kd_fb *fb, kd_rect area);

typedef struct {
    const char *label;     // NULL ends the list; "-" is a separator
    bool disabled, checked;
} kd_menu_item;

typedef struct {
    const char *title;
    const kd_menu_item *items;
} kd_menu;

// Title x positions are computed from the labels: 8 px margin, 2 spaces apart.
int kd_menu_title_x(const kd_menu *menus, int index);
int kd_menu_title_w(const kd_menu *menus, int index);
int kd_menu_item_count(const kd_menu *m);
kd_rect kd_menu_dropdown_rect(const kd_menu *menus, int index);
void kd_gfx_menubar(kd_fb *fb, const kd_menu *menus, int open);
void kd_gfx_dropdown(kd_fb *fb, const kd_menu *menus, int open, int hot);

kd_rect kd_frame_title(kd_rect frame);    // title bar interior (close box included)
kd_rect kd_frame_close(kd_rect frame);
kd_rect kd_frame_work(kd_rect frame);
void kd_gfx_frame(kd_fb *fb, kd_rect frame, const char *title, bool active, bool closable);
void kd_gfx_outline(kd_fb *fb, kd_rect r);    // dotted drag outline

enum { KD_BTN_DEFAULT = 1, KD_BTN_PRESSED = 2, KD_BTN_FOCUS = 4, KD_BTN_DISABLED = 8 };
void kd_gfx_button(kd_fb *fb, kd_rect r, const char *label, unsigned flags);
// Icon with its small-font label centred below; returns the label+icon box.
kd_rect kd_icon_box(int x, int y, const char *label);
void kd_gfx_icon(kd_fb *fb, int x, int y, const kd_art *a, const char *label, bool selected);

#endif
