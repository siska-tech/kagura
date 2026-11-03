// SPDX-License-Identifier: Apache-2.0
// Layer C: window manager, compositor and event dispatch.
//
// Composition: every damage rect D is recomposed top-down. The layers are the
// open dropdown, the menu bar, the popup (an input method's candidates: above
// every window, a dialog included, and below the menus) and the windows from
// the top of the z-order;
// each layer draws only into the part of D not yet covered by a layer above
// it (a GEM-style visible rectangle list), then that part is removed. The
// desktop fills what remains and the overlays (drag outline, software
// cursor) are drawn last. Every pixel of D is thus composed by one layer
// (plus overlays). Layers must be opaque over their whole rect, window
// content included. If the rectangle list overflows, D falls back to the
// painter's algorithm (bottom-up, same result, more overdraw). painter=true
// forces the fallback for comparison.
//
// The dirty tile map stays exact: a tile is dirty after a render only if its
// bytes differ from before (see compose_exact), however much a pass redraws.
//
// Invalidation subtracts every layer above the changed item before adding to
// the damage list, so occluded changes cost nothing.
//
// Single owner, no allocation, no recursion through applications: callbacks
// may invalidate (damage goes to the next render) but must not render.
#ifndef KD_DESKTOP_H
#define KD_DESKTOP_H

#include "kd_app.h"
#include "kd_region.h"

#define KD_MAX_WINDOWS 8
#define KD_MAX_ICONS 8
#define KD_TITLE_MAX 48          // bytes with NUL: 16 Japanese characters in UTF-8
#define KD_DOUBLE_CLICK_MS 400

struct kd_window {
    kd_desktop *desk;
    const kd_window_class *cls;
    void *user;
    kd_rect frame;
    char title[KD_TITLE_MAX];
    uint16_t flags;
    bool open;
};

typedef struct {
    int16_t x, y;
    const kd_art *art;
    const char *label;
} kd_desk_icon;

typedef struct {
    void (*menu)(kd_desktop *d, int menu, int item, void *ctx);
    void (*icon_open)(kd_desktop *d, int icon, void *ctx);
    void *ctx;
} kd_shell_hooks;

enum { KD_DRAG_NONE, KD_DRAG_MOVE, KD_DRAG_OUTLINE, KD_DRAG_CLOSE, KD_DRAG_CAPTURE };

typedef struct {
    uint32_t renders, rects, layers, fallbacks;   // cumulative
    uint32_t passes;          // compose passes (damage rects split into tile bands)
    uint32_t suppressed;      // tiles written during compose but left unchanged
    uint32_t last_rects, last_damage_tiles;
    int32_t last_area;        // damage pixels of the last render
} kd_compose_stats;

// Compose passes snapshot at most this many tiles (3,840 B) to keep the
// dirty map exact despite overdraw inside a pass. Three full tile rows per
// pass: a 10 px editor line straddles fewer passes, and every pass repeats
// the backgrounds of the layers it crosses (on the RP2040, a full editor
// view cost 15 ms in passes alone with one tile row).
#ifndef KD_SNAP_TILES
#define KD_SNAP_TILES (3 * KD_TILE_COLS)
#endif

struct kd_desktop {
    kd_fb fb;
    kd_damage damage;
    kd_window win[KD_MAX_WINDOWS];
    int8_t z[KD_MAX_WINDOWS];      // window slots, bottom first
    uint8_t zn;
    const kd_menu *menus;
    int8_t menu_open, menu_hot;
    kd_desk_icon icons[KD_MAX_ICONS];
    uint8_t nicons;
    int8_t icon_sel;
    kd_shell_hooks hooks;
    int16_t px, py;                // pointer
    bool cursor_on;                // draw the software cursor
    uint8_t drag;
    int8_t drag_win;
    int16_t grab_dx, grab_dy;
    kd_rect outline;
    bool outline_drag;             // option: move windows as an outline
    bool painter;                  // option: painter's algorithm (baseline)
    uint32_t last_click_ms;
    int16_t last_click_x, last_click_y;
    int8_t last_click_target;
    // Right-aligned status text in the menu bar (an input method's mode).
    char status[32];
    uint8_t status_len;
    // A popup (an input method's candidates): a layer above every window and
    // below the menus, opaque over popup; draw paints it at screen coordinates
    // with the clip set. Empty popup: none.
    kd_rect popup;
    void (*popup_draw)(void *ctx, kd_fb *fb);
    void *popup_ctx;
    kd_compose_stats stats;
    uint8_t snap[KD_SNAP_TILES * 32];
};

void kd_desktop_init(kd_desktop *d, const kd_menu *menus, const kd_desk_icon *icons,
                     int nicons, kd_shell_hooks hooks);
void kd_desktop_event(kd_desktop *d, const kd_event *ev);
// Recomposes all damage. Returns false when nothing was damaged.
bool kd_desktop_render(kd_desktop *d);
void kd_desktop_invalidate(kd_desktop *d, kd_rect screen);

kd_window *kd_desktop_top(kd_desktop *d);
kd_window *kd_desktop_window_at(kd_desktop *d, int x, int y);
int kd_desktop_z_index(const kd_desktop *d, const kd_window *w);   // -1 if closed
void kd_desktop_activate(kd_desktop *d, kd_window *w);
void kd_desktop_move(kd_desktop *d, kd_window *w, int x, int y);
void kd_desktop_open_menu(kd_desktop *d, int menu);
void kd_desktop_close_menu(kd_desktop *d);
void kd_desktop_select_icon(kd_desktop *d, int icon);
void kd_desktop_set_cursor(kd_desktop *d, bool on);
void kd_desktop_menu_changed(kd_desktop *d);   // menu item flags changed
// Shows, moves or hides (empty r) the popup layer: the old and the new rect
// are recomposed. A change of its content alone: kd_desktop_invalidate the
// changed part.
void kd_desktop_set_popup(kd_desktop *d, kd_rect r, void (*draw)(void *ctx, kd_fb *fb), void *ctx);
// Right-aligned status text in the menu bar (UTF-8, at most 31 bytes), never
// over the menu titles: it is clipped instead. Only its own box is recomposed.
void kd_desktop_set_status(kd_desktop *d, const char *s, int len);
kd_rect kd_desktop_status_box(const kd_desktop *d);

kd_rect kd_cursor_rect(const kd_desktop *d);

#endif
