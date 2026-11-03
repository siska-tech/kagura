// SPDX-License-Identifier: Apache-2.0
// Layer D: the application boundary of the C desktop.
//
// Applications (the native demos today, MicroPython windows in future) only
// use this header. They own a window, draw its work area when the compositor
// asks, and receive POD events in work-area coordinates. They never touch the
// framebuffer, the z-order or the damage list directly:
//
//   * Drawing happens only inside kd_window_class.draw, with the clip already
//     set to the part of the work area being recomposed. A window may be asked
//     to draw any sub-rectangle at any time (exposure), so draw must be a pure
//     function of the application's state.
//   * State changes are announced with kd_window_invalidate(local rect). Only
//     the visible part of that rect is damaged; occluded parts cost nothing.
//   * Events are copied by value (kd_event is 16 bytes, no pointers), so a
//     future binding can queue them in a fixed ring and hand them to Python
//     outside the compositor. See ARCHITECTURE.md for the proposed binding.
#ifndef KD_APP_H
#define KD_APP_H

#include "kd_fb.h"
#include "kd_font.h"
#include "kd_gfx.h"
#include "kd_sprite.h"

typedef struct kd_desktop kd_desktop;
typedef struct kd_window kd_window;

enum {
    KD_EV_NONE, KD_EV_POINTER_MOVE, KD_EV_POINTER_DOWN, KD_EV_POINTER_UP,
    KD_EV_KEY, KD_EV_FOCUS, KD_EV_BLUR,
};

enum {
    KD_KEY_NONE, KD_KEY_CHAR, KD_KEY_UP, KD_KEY_DOWN, KD_KEY_LEFT, KD_KEY_RIGHT,
    KD_KEY_ENTER, KD_KEY_ESCAPE, KD_KEY_TAB, KD_KEY_BACKSPACE, KD_KEY_DELETE,
    KD_KEY_HOME, KD_KEY_END, KD_KEY_F6, KD_KEY_F10, KD_KEY_INSERT,
    KD_KEY_PGUP, KD_KEY_PGDN,
};

enum { KD_MOD_SHIFT = 1, KD_MOD_CTRL = 2, KD_MOD_ALT = 4 };
enum { KD_BUTTON_LEFT = 1, KD_BUTTON_RIGHT = 2 };

typedef struct {
    uint8_t type;      // KD_EV_*
    uint8_t button;    // pointer: KD_BUTTON_*
    uint8_t key;       // KD_KEY_*; printable characters use KD_KEY_CHAR + ch
    uint8_t mods;      // KD_MOD_*
    char ch;
    uint8_t clicks;    // pointer down: 2 for a double click
    int16_t x, y;      // screen coordinates in, work-area coordinates for windows
    uint32_t time_ms;  // host clock; only differences are used
    uint32_t reserved;
} kd_event;

typedef struct {
    kd_fb *fb;
    int16_t ox, oy;    // work-area origin on screen
    int16_t w, h;      // work-area size
} kd_draw;

// All kd_draw coordinates are relative to the work area.
bool kd_draw_visible(const kd_draw *d, kd_rect local);
void kd_draw_fill(const kd_draw *d, int x, int y, int w, int h, uint8_t color);
void kd_draw_rect(const kd_draw *d, int x, int y, int w, int h, uint8_t color);
void kd_draw_hline(const kd_draw *d, int x, int y, int w, uint8_t color);
void kd_draw_vline(const kd_draw *d, int x, int y, int h, uint8_t color);
int kd_draw_text(const kd_draw *d, const kd_font *f, int x, int y, const char *s,
                 uint8_t fg, int bg);
void kd_draw_art(const kd_draw *d, int x, int y, const kd_art *a, uint8_t ink, uint8_t paper);
void kd_draw_icon(const kd_draw *d, int x, int y, const kd_art *a, const char *label, bool selected);
void kd_draw_button(const kd_draw *d, kd_rect local, const char *label, unsigned flags);
void kd_draw_pattern(const kd_draw *d, int x, int y, int w, int h, const uint8_t rows[8],
                     uint8_t c0, uint8_t c1);
// zoom >= 1; key KD_NO_KEY draws colour 0 opaquely, key 0 makes it transparent.
void kd_draw_sprite(const kd_draw *d, int x, int y, const kd_sprite *s, int zoom, int key);

// Fixed-width text field in the system font at work-area (x, y). Setting new
// text invalidates only the glyph cells that changed.
#define KD_LABEL_MAX 24
typedef struct {
    int16_t x, y;
    uint8_t width;              // characters
    char text[KD_LABEL_MAX + 1];
} kd_label;

typedef struct {
    void (*draw)(kd_window *w, const kd_draw *d);
    bool (*event)(kd_window *w, const kd_event *ev);   // true when consumed
    void (*closed)(kd_window *w);                       // after removal; may be NULL
} kd_window_class;

enum { KD_WF_CLOSE = 1, KD_WF_MOVE = 2 };

// Frame is the outer rect (border and title bar included). Returns NULL when
// all window slots are in use. The new window is raised and focused.
kd_window *kd_window_open(kd_desktop *d, const kd_window_class *cls, void *user,
                          const char *title, kd_rect frame, unsigned flags);
void kd_window_close(kd_desktop *d, kd_window *w);
void kd_window_invalidate(kd_desktop *d, kd_window *w, kd_rect local);
void kd_window_invalidate_all(kd_desktop *d, kd_window *w);
void kd_window_set_title(kd_desktop *d, kd_window *w, const char *title);
void *kd_window_user(const kd_window *w);
kd_desktop *kd_window_desktop(const kd_window *w);
kd_rect kd_window_frame(const kd_window *w);
kd_rect kd_window_work(const kd_window *w);    // screen coordinates
bool kd_window_is_active(const kd_window *w);

void kd_label_init(kd_label *l, int x, int y, int width, const char *text);
void kd_label_set(kd_desktop *d, kd_window *w, kd_label *l, const char *text);
void kd_draw_label(const kd_draw *d, const kd_label *l, uint8_t fg, uint8_t bg);

#endif
