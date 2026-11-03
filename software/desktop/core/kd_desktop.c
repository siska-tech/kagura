// SPDX-License-Identifier: Apache-2.0
#include "kd_desktop.h"

#include <string.h>

#include "kd_fault.h"
#include "kd_tile4.h"

enum { LAYER_DROPDOWN, LAYER_MENUBAR, LAYER_POPUP, LAYER_WINDOW };

typedef struct {
    uint8_t kind;
    kd_window *w;
    kd_rect r;
} layer;

static kd_rect screen_rect(void) { return kd_rect_make(0, 0, KD_W, KD_H); }
static kd_rect menubar_rect(void) { return kd_rect_make(0, 0, KD_W, KD_MENU_H); }

kd_rect kd_cursor_rect(const kd_desktop *d) {
    return kd_rect_make(d->px, d->py, KD_CURSOR_W, KD_CURSOR_H);
}

int kd_desktop_z_index(const kd_desktop *d, const kd_window *w) {
    for (int i = 0; i < d->zn; i++)
        if (&d->win[d->z[i]] == w) return i;
    return -1;
}

kd_window *kd_desktop_top(kd_desktop *d) {
    return d->zn ? &d->win[d->z[d->zn - 1]] : NULL;
}

static int menu_count(const kd_desktop *d) {
    int n = 0;
    while (d->menus && d->menus[n].title) n++;
    return n;
}

// Adds r minus every layer above z level `level` (-1: the desktop itself).
static void damage_from(kd_desktop *d, kd_rect r, int level) {
    kd_region g;
    kd_region_init(&g, kd_rect_intersect(r, screen_rect()));
    for (int i = level + 1; i < d->zn; i++) kd_region_subtract(&g, d->win[d->z[i]].frame);
    if (!kd_rect_empty(d->popup)) kd_region_subtract(&g, d->popup);   // the popup is above every window
    kd_region_subtract(&g, menubar_rect());
    if (d->menu_open >= 0) kd_region_subtract(&g, kd_menu_dropdown_rect(d->menus, d->menu_open));
    if (g.overflow) {
        kd_damage_add(&d->damage, r);
        return;
    }
    for (int i = 0; i < g.n; i++) kd_damage_add(&d->damage, g.r[i]);
}

static void damage_title(kd_desktop *d, kd_window *w) {
    int i = kd_desktop_z_index(d, w);
    if (i >= 0) damage_from(d, kd_frame_title(w->frame), i);
}

static void damage_outline(kd_desktop *d, kd_rect r) {
    kd_damage_add(&d->damage, kd_rect_make(r.x, r.y, r.w, 1));
    kd_damage_add(&d->damage, kd_rect_make(r.x, r.y + r.h - 1, r.w, 1));
    kd_damage_add(&d->damage, kd_rect_make(r.x, r.y, 1, r.h));
    kd_damage_add(&d->damage, kd_rect_make(r.x + r.w - 1, r.y, 1, r.h));
}

static bool send(kd_window *w, const kd_event *ev) {
    return w && w->cls && w->cls->event ? w->cls->event(w, ev) : false;
}

static void send_simple(kd_window *w, uint8_t type) {
    kd_event ev;
    memset(&ev, 0, sizeof ev);
    ev.type = type;
    send(w, &ev);
}

static bool send_local(kd_window *w, const kd_event *ev) {
    kd_event local = *ev;
    kd_rect work = kd_frame_work(w->frame);
    local.x = (int16_t)(ev->x - work.x);
    local.y = (int16_t)(ev->y - work.y);
    return send(w, &local);
}

void kd_desktop_init(kd_desktop *d, const kd_menu *menus, const kd_desk_icon *icons,
                     int nicons, kd_shell_hooks hooks) {
    memset(d, 0, sizeof *d);
    kd_fb_init(&d->fb, KD_C_DESK);
    d->menus = menus;
    d->menu_open = d->menu_hot = -1;
    if (nicons > KD_MAX_ICONS) nicons = KD_MAX_ICONS;
    for (int i = 0; i < nicons; i++) d->icons[i] = icons[i];
    d->nicons = (uint8_t)nicons;
    d->icon_sel = -1;
    d->hooks = hooks;
    d->px = KD_W / 2;
    d->py = KD_H / 2;
    d->drag_win = -1;
    d->last_click_target = -1;
    kd_damage_add(&d->damage, screen_rect());
}

void kd_desktop_invalidate(kd_desktop *d, kd_rect r) { kd_damage_add(&d->damage, r); }

kd_window *kd_desktop_window_at(kd_desktop *d, int x, int y) {
    for (int i = d->zn - 1; i >= 0; i--) {
        kd_window *w = &d->win[d->z[i]];
        if (kd_rect_has_point(w->frame, x, y)) return w;
    }
    return NULL;
}

// ---- window operations (kd_app.h) ----

// Copies at most KD_TITLE_MAX - 1 bytes, never splitting a UTF-8 character.
static void copy_title(char out[KD_TITLE_MAX], const char *title) {
    size_t n = title ? strlen(title) : 0;
    if (n > KD_TITLE_MAX - 1) {
        n = KD_TITLE_MAX - 1;
        while (n > 0 && ((unsigned char)title[n] & 0xC0) == 0x80) n--;
    }
    memset(out, 0, KD_TITLE_MAX);
    if (n) memcpy(out, title, n);
}

kd_window *kd_window_open(kd_desktop *d, const kd_window_class *cls, void *user,
                          const char *title, kd_rect frame, unsigned flags) {
    int slot = -1;
    for (int s = 0; s < KD_MAX_WINDOWS; s++)
        if (!d->win[s].open) { slot = s; break; }
    if (slot < 0) return NULL;
    kd_window *w = &d->win[slot], *old = kd_desktop_top(d);
    memset(w, 0, sizeof *w);
    w->desk = d;
    w->cls = cls;
    w->user = user;
    w->frame = frame;
    w->flags = (uint16_t)flags;
    w->open = true;
    copy_title(w->title, title);
    d->z[d->zn++] = (int8_t)slot;
    damage_from(d, frame, d->zn - 1);
    if (old) {
        damage_title(d, old);
        send_simple(old, KD_EV_BLUR);
    }
    send_simple(w, KD_EV_FOCUS);
    return w;
}

void kd_window_close(kd_desktop *d, kd_window *w) {
    int i = kd_desktop_z_index(d, w);
    if (i < 0) return;
    int slot = d->z[i];
    if (d->drag_win == slot) {
        if (d->drag == KD_DRAG_OUTLINE) damage_outline(d, d->outline);
        d->drag = KD_DRAG_NONE;
        d->drag_win = -1;
    }
    bool was_top = i == d->zn - 1;
    if (!KD_FAULTY(KD_FAULT_CLOSE_EXPOSE)) damage_from(d, w->frame, i);
    memmove(&d->z[i], &d->z[i + 1], (size_t)(d->zn - i - 1));
    d->zn--;
    w->open = false;
    kd_window *top = kd_desktop_top(d);
    if (was_top && top) {
        damage_title(d, top);
        send_simple(top, KD_EV_FOCUS);
    }
    if (w->cls && w->cls->closed) w->cls->closed(w);
}

void kd_window_invalidate(kd_desktop *d, kd_window *w, kd_rect local) {
    int level = kd_desktop_z_index(d, w);
    if (level < 0) return;
    kd_rect work = kd_frame_work(w->frame);
    kd_rect r = kd_rect_intersect(kd_rect_make(work.x + local.x, work.y + local.y, local.w, local.h), work);
    if (KD_FAULTY(KD_FAULT_OCCLUDED_SKIP)) level--;
    damage_from(d, r, level);
}

void kd_window_invalidate_all(kd_desktop *d, kd_window *w) {
    kd_rect work = kd_frame_work(w->frame);
    kd_window_invalidate(d, w, kd_rect_make(0, 0, work.w, work.h));
}

void kd_window_set_title(kd_desktop *d, kd_window *w, const char *title) {
    copy_title(w->title, title);
    damage_title(d, w);
}

void *kd_window_user(const kd_window *w) { return w->user; }
kd_desktop *kd_window_desktop(const kd_window *w) { return w->desk; }
kd_rect kd_window_frame(const kd_window *w) { return w->frame; }
kd_rect kd_window_work(const kd_window *w) { return kd_frame_work(w->frame); }
bool kd_window_is_active(const kd_window *w) { return w->open && kd_desktop_top(w->desk) == w; }

void kd_desktop_activate(kd_desktop *d, kd_window *w) {
    int i = kd_desktop_z_index(d, w);
    if (i < 0 || i == d->zn - 1) return;
    kd_window *old = kd_desktop_top(d);
    // Parts of w covered by windows above it become visible.
    if (!KD_FAULTY(KD_FAULT_RAISE_EXPOSE))
        for (int j = i + 1; j < d->zn; j++)
            damage_from(d, kd_rect_intersect(w->frame, d->win[d->z[j]].frame), d->zn - 1);
    int8_t slot = d->z[i];
    memmove(&d->z[i], &d->z[i + 1], (size_t)(d->zn - i - 1));
    d->z[d->zn - 1] = slot;
    damage_title(d, w);
    damage_title(d, old);
    send_simple(old, KD_EV_BLUR);
    send_simple(w, KD_EV_FOCUS);
}

static void clamp_position(const kd_window *w, int *x, int *y) {
    if (*x < 16 - w->frame.w) *x = 16 - w->frame.w;
    if (*x > KD_W - 16) *x = KD_W - 16;
    if (*y < KD_MENU_H) *y = KD_MENU_H;
    if (*y > KD_H - KD_TITLE_H - 1) *y = KD_H - KD_TITLE_H - 1;
}

void kd_desktop_move(kd_desktop *d, kd_window *w, int x, int y) {
    int i = kd_desktop_z_index(d, w);
    if (i < 0) return;
    clamp_position(w, &x, &y);
    if (x == w->frame.x && y == w->frame.y) return;
    kd_rect old = w->frame;
    w->frame.x = (int16_t)x;
    w->frame.y = (int16_t)y;
    if (!KD_FAULTY(KD_FAULT_MOVE_OLD)) damage_from(d, old, i);
    damage_from(d, w->frame, i);
}

// ---- menus, icons, cursor ----

static kd_rect title_box(const kd_desktop *d, int m) {
    return kd_rect_make(kd_menu_title_x(d->menus, m) - 4, 0, kd_menu_title_w(d->menus, m) + 8, KD_MENU_H - 1);
}

static kd_rect item_box(const kd_desktop *d, int m, int item) {
    kd_rect r = kd_menu_dropdown_rect(d->menus, m);
    return kd_rect_make(r.x + 1, r.y + 1 + item * KD_MENU_ITEM_H, r.w - 3, KD_MENU_ITEM_H);
}

static bool item_usable(const kd_desktop *d, int m, int item) {
    if (item < 0 || item >= kd_menu_item_count(&d->menus[m])) return false;
    const kd_menu_item *it = &d->menus[m].items[item];
    return !it->disabled && strcmp(it->label, "-") != 0;
}

static void set_hot(kd_desktop *d, int item) {
    if (d->menu_open < 0 || item == d->menu_hot) return;
    if (d->menu_hot >= 0) kd_damage_add(&d->damage, item_box(d, d->menu_open, d->menu_hot));
    if (item >= 0) kd_damage_add(&d->damage, item_box(d, d->menu_open, item));
    d->menu_hot = (int8_t)item;
}

static int step_item(const kd_desktop *d, int from, int dir) {
    int n = kd_menu_item_count(&d->menus[d->menu_open]), i = from;
    for (int k = 0; k < n; k++) {
        i = i < 0 ? (dir > 0 ? 0 : n - 1) : (i + dir + n) % n;
        if (item_usable(d, d->menu_open, i)) return i;
    }
    return -1;
}

void kd_desktop_open_menu(kd_desktop *d, int m) {
    if (m == d->menu_open) return;
    kd_desktop_close_menu(d);
    if (m < 0 || m >= menu_count(d)) return;
    d->menu_open = (int8_t)m;
    d->menu_hot = -1;
    kd_damage_add(&d->damage, title_box(d, m));
    kd_damage_add(&d->damage, kd_menu_dropdown_rect(d->menus, m));
}

void kd_desktop_close_menu(kd_desktop *d) {
    if (d->menu_open < 0) return;
    kd_damage_add(&d->damage, title_box(d, d->menu_open));
    kd_damage_add(&d->damage, kd_menu_dropdown_rect(d->menus, d->menu_open));
    d->menu_open = d->menu_hot = -1;
}

void kd_desktop_menu_changed(kd_desktop *d) {
    if (d->menu_open >= 0) kd_damage_add(&d->damage, kd_menu_dropdown_rect(d->menus, d->menu_open));
}

// The status text's box: right-aligned, but never left of the menu titles.
kd_rect kd_desktop_status_box(const kd_desktop *d) {
    if (!d->status_len) return kd_rect_make(0, 0, 0, 0);
    int left = 4, n = menu_count(d);
    if (n) left = kd_menu_title_x(d->menus, n - 1) + kd_menu_title_w(d->menus, n - 1) + 8;
    int w = kd_text_width_n(&kd_font_system, d->status, d->status_len);
    int x = KD_W - 4 - w;
    if (x < left) x = left;                          // too long: clipped at the right
    return kd_rect_intersect(kd_rect_make(x - 2, 0, w + 4, KD_MENU_H - 1), kd_rect_make(left - 2, 0, KD_W - left + 2, KD_MENU_H - 1));
}

void kd_desktop_set_status(kd_desktop *d, const char *s, int len) {
    if (len < 0) len = 0;
    if (len > (int)sizeof d->status - 1) len = (int)sizeof d->status - 1;
    if (len == d->status_len && memcmp(d->status, s, (size_t)len) == 0) return;
    kd_rect old = kd_desktop_status_box(d);
    memcpy(d->status, s, (size_t)len);
    d->status[len] = 0;
    d->status_len = (uint8_t)len;
    kd_rect now = kd_desktop_status_box(d);
    if (!kd_rect_empty(old)) kd_damage_add(&d->damage, old);
    if (!kd_rect_empty(now)) kd_damage_add(&d->damage, now);
}

void kd_desktop_set_popup(kd_desktop *d, kd_rect r, void (*draw)(void *ctx, kd_fb *fb), void *ctx) {
    r = kd_rect_intersect(r, screen_rect());
    if (!draw) r = kd_rect_make(0, 0, 0, 0);
    d->popup_draw = draw;
    d->popup_ctx = ctx;
    if (r.x == d->popup.x && r.y == d->popup.y && r.w == d->popup.w && r.h == d->popup.h) return;
    // Where it was, the windows below show again; where it goes, it covers them.
    if (!kd_rect_empty(d->popup)) kd_damage_add(&d->damage, d->popup);
    d->popup = r;
    if (!kd_rect_empty(r)) kd_damage_add(&d->damage, r);
}

static void choose(kd_desktop *d, int item) {
    int m = d->menu_open;
    if (m < 0 || !item_usable(d, m, item)) return;
    kd_desktop_close_menu(d);
    if (d->hooks.menu) d->hooks.menu(d, m, item, d->hooks.ctx);
}

void kd_desktop_select_icon(kd_desktop *d, int icon) {
    if (icon == d->icon_sel) return;
    if (d->icon_sel >= 0) {
        const kd_desk_icon *ic = &d->icons[d->icon_sel];
        damage_from(d, kd_icon_box(ic->x, ic->y, ic->label), -1);
    }
    if (icon >= 0) {
        const kd_desk_icon *ic = &d->icons[icon];
        damage_from(d, kd_icon_box(ic->x, ic->y, ic->label), -1);
    }
    d->icon_sel = (int8_t)icon;
}

void kd_desktop_set_cursor(kd_desktop *d, bool on) {
    if (on == d->cursor_on) return;
    d->cursor_on = on;
    kd_damage_add(&d->damage, kd_cursor_rect(d));
}

// ---- events ----

static int icon_at(const kd_desktop *d, int x, int y) {
    for (int i = d->nicons - 1; i >= 0; i--)
        if (kd_rect_has_point(kd_icon_box(d->icons[i].x, d->icons[i].y, d->icons[i].label), x, y)) return i;
    return -1;
}

static int title_at(const kd_desktop *d, int x, int y) {
    for (int m = 0; m < menu_count(d); m++)
        if (kd_rect_has_point(title_box(d, m), x, y)) return m;
    return -1;
}

static int dropdown_item_at(const kd_desktop *d, int x, int y) {
    if (d->menu_open < 0) return -1;
    kd_rect r = kd_menu_dropdown_rect(d->menus, d->menu_open);
    kd_rect inner = kd_rect_make(r.x + 1, r.y + 1, r.w - 3, r.h - 3);
    if (!kd_rect_has_point(inner, x, y)) return -1;
    int item = (y - inner.y) / KD_MENU_ITEM_H;
    return item < kd_menu_item_count(&d->menus[d->menu_open]) ? item : -1;
}

// Every pointer event carries a position; the software cursor follows it.
static void set_pointer(kd_desktop *d, const kd_event *ev) {
    if (ev->x == d->px && ev->y == d->py) return;
    if (d->cursor_on) kd_damage_add(&d->damage, kd_cursor_rect(d));
    d->px = ev->x;
    d->py = ev->y;
    if (d->cursor_on) kd_damage_add(&d->damage, kd_cursor_rect(d));
}

static void pointer_move(kd_desktop *d, const kd_event *ev) {
    set_pointer(d, ev);
    if (d->menu_open >= 0) {
        int m = title_at(d, ev->x, ev->y);
        if (m >= 0 && m != d->menu_open) kd_desktop_open_menu(d, m);
        else set_hot(d, item_usable(d, d->menu_open, dropdown_item_at(d, ev->x, ev->y)) ?
                            dropdown_item_at(d, ev->x, ev->y) : -1);
        return;
    }
    kd_window *w = d->drag_win >= 0 ? &d->win[d->drag_win] : NULL;
    if (d->drag == KD_DRAG_MOVE) {
        kd_desktop_move(d, w, ev->x - d->grab_dx, ev->y - d->grab_dy);
    } else if (d->drag == KD_DRAG_OUTLINE) {
        int x = ev->x - d->grab_dx, y = ev->y - d->grab_dy;
        clamp_position(w, &x, &y);
        if (x != d->outline.x || y != d->outline.y) {
            damage_outline(d, d->outline);
            d->outline.x = (int16_t)x;
            d->outline.y = (int16_t)y;
            damage_outline(d, d->outline);
        }
    } else if (d->drag == KD_DRAG_CAPTURE) {
        send_local(w, ev);
    }
}

static int click_count(kd_desktop *d, const kd_event *ev, int target) {
    int dx = ev->x - d->last_click_x, dy = ev->y - d->last_click_y;
    bool dbl = target == d->last_click_target && ev->time_ms - d->last_click_ms <= KD_DOUBLE_CLICK_MS &&
               dx >= -4 && dx <= 4 && dy >= -4 && dy <= 4;
    d->last_click_target = (int8_t)(dbl ? -1 : target);
    d->last_click_ms = ev->time_ms;
    d->last_click_x = ev->x;
    d->last_click_y = ev->y;
    return dbl ? 2 : 1;
}

static void start_drag(kd_desktop *d, kd_window *w, int x, int y) {
    if (!(w->flags & KD_WF_MOVE)) return;
    d->drag = d->outline_drag ? KD_DRAG_OUTLINE : KD_DRAG_MOVE;
    d->drag_win = (int8_t)(w - d->win);
    d->grab_dx = (int16_t)(x - w->frame.x);
    d->grab_dy = (int16_t)(y - w->frame.y);
    if (d->drag == KD_DRAG_OUTLINE) {
        d->outline = w->frame;
        damage_outline(d, d->outline);
    }
}

static void pointer_down(kd_desktop *d, const kd_event *ev) {
    set_pointer(d, ev);
    if (d->menu_open >= 0) {
        int m = title_at(d, ev->x, ev->y);
        if (m == d->menu_open) kd_desktop_close_menu(d);
        else if (m >= 0) kd_desktop_open_menu(d, m);
        else if (dropdown_item_at(d, ev->x, ev->y) < 0) kd_desktop_close_menu(d);
        return;
    }
    if (ev->y < KD_MENU_H) {
        int m = title_at(d, ev->x, ev->y);
        if (m >= 0) kd_desktop_open_menu(d, m);
        return;
    }
    kd_window *w = kd_desktop_window_at(d, ev->x, ev->y);
    if (w) {
        bool in_title = kd_rect_has_point(kd_frame_title(w->frame), ev->x, ev->y);
        bool in_close = (w->flags & KD_WF_CLOSE) && kd_rect_has_point(kd_frame_close(w->frame), ev->x, ev->y);
        if (w != kd_desktop_top(d)) {
            // GEM style: the first click only tops the window (title drags too).
            kd_desktop_activate(d, w);
            if (in_title && !in_close) start_drag(d, w, ev->x, ev->y);
            d->last_click_target = -1;
            return;
        }
        if (in_close) {
            d->drag = KD_DRAG_CLOSE;
            d->drag_win = (int8_t)(w - d->win);
        } else if (in_title) {
            start_drag(d, w, ev->x, ev->y);
        } else if (kd_rect_has_point(kd_frame_work(w->frame), ev->x, ev->y)) {
            d->drag = KD_DRAG_CAPTURE;
            d->drag_win = (int8_t)(w - d->win);
            kd_event local = *ev;
            local.clicks = (uint8_t)click_count(d, ev, 64 + (int)(w - d->win));
            send_local(w, &local);
        }
        return;
    }
    int icon = icon_at(d, ev->x, ev->y);
    int clicks = click_count(d, ev, icon >= 0 ? icon : 32);
    kd_desktop_select_icon(d, icon);
    if (icon >= 0 && clicks == 2 && d->hooks.icon_open) d->hooks.icon_open(d, icon, d->hooks.ctx);
}

static void pointer_up(kd_desktop *d, const kd_event *ev) {
    set_pointer(d, ev);
    if (d->menu_open >= 0) {
        int item = dropdown_item_at(d, ev->x, ev->y);
        if (item >= 0) choose(d, item);
        return;
    }
    kd_window *w = d->drag_win >= 0 ? &d->win[d->drag_win] : NULL;
    uint8_t drag = d->drag;
    d->drag = KD_DRAG_NONE;
    d->drag_win = -1;
    if (!w) return;
    if (drag == KD_DRAG_CLOSE) {
        if (kd_rect_has_point(kd_frame_close(w->frame), ev->x, ev->y)) kd_window_close(d, w);
    } else if (drag == KD_DRAG_OUTLINE) {
        damage_outline(d, d->outline);
        kd_desktop_move(d, w, d->outline.x, d->outline.y);
    } else if (drag == KD_DRAG_CAPTURE) {
        send_local(w, ev);
    }
}

static void menu_key(kd_desktop *d, const kd_event *ev) {
    int n = menu_count(d);
    switch (ev->key) {
    case KD_KEY_ESCAPE: case KD_KEY_F10:
        kd_desktop_close_menu(d);
        break;
    case KD_KEY_LEFT: case KD_KEY_RIGHT: {
        int m = (d->menu_open + (ev->key == KD_KEY_LEFT ? n - 1 : 1)) % n;
        kd_desktop_open_menu(d, m);
        set_hot(d, step_item(d, -1, 1));
        break;
    }
    case KD_KEY_UP: set_hot(d, step_item(d, d->menu_hot, -1)); break;
    case KD_KEY_DOWN: set_hot(d, step_item(d, d->menu_hot, 1)); break;
    case KD_KEY_ENTER: choose(d, d->menu_hot); break;
    case KD_KEY_CHAR:
        if (ev->ch == ' ') choose(d, d->menu_hot);
        break;
    default: break;
    }
}

static void desktop_key(kd_desktop *d, const kd_event *ev) {
    int sel = d->icon_sel;
    switch (ev->key) {
    case KD_KEY_LEFT: case KD_KEY_UP:
        if (d->nicons) kd_desktop_select_icon(d, sel <= 0 ? 0 : sel - 1);
        break;
    case KD_KEY_RIGHT: case KD_KEY_DOWN: case KD_KEY_TAB:
        if (d->nicons) kd_desktop_select_icon(d, sel + 1 >= d->nicons ? d->nicons - 1 : sel + 1);
        break;
    case KD_KEY_ENTER:
        if (sel >= 0 && d->hooks.icon_open) d->hooks.icon_open(d, sel, d->hooks.ctx);
        break;
    default: break;
    }
}

static void key(kd_desktop *d, const kd_event *ev) {
    if (d->menu_open >= 0) {
        menu_key(d, ev);
        return;
    }
    kd_window *top = kd_desktop_top(d);
    bool ctrl = ev->mods & KD_MOD_CTRL;
    if (ev->key == KD_KEY_F10) {
        kd_desktop_open_menu(d, 0);
        if (d->menu_open >= 0) set_hot(d, step_item(d, -1, 1));   // a desktop may have no menus
        return;
    }
    if (ev->key == KD_KEY_F6 || (ctrl && ev->key == KD_KEY_TAB)) {
        if (d->zn > 1) kd_desktop_activate(d, &d->win[d->z[0]]);
        return;
    }
    if (top && ctrl && ev->key == KD_KEY_CHAR && (ev->ch == 'w' || ev->ch == 'W')) {
        if (top->flags & KD_WF_CLOSE) kd_window_close(d, top);
        return;
    }
    if (top && ctrl && ev->key >= KD_KEY_UP && ev->key <= KD_KEY_RIGHT && (top->flags & KD_WF_MOVE)) {
        int dx = ev->key == KD_KEY_LEFT ? -8 : ev->key == KD_KEY_RIGHT ? 8 : 0;
        int dy = ev->key == KD_KEY_UP ? -8 : ev->key == KD_KEY_DOWN ? 8 : 0;
        kd_desktop_move(d, top, top->frame.x + dx, top->frame.y + dy);
        return;
    }
    if (top) {
        kd_window *target = KD_FAULTY(KD_FAULT_FOCUS_BOTTOM) ? &d->win[d->z[0]] : top;
        send(target, ev);
        return;
    }
    desktop_key(d, ev);
}

void kd_desktop_event(kd_desktop *d, const kd_event *ev) {
    switch (ev->type) {
    case KD_EV_POINTER_MOVE: pointer_move(d, ev); break;
    case KD_EV_POINTER_DOWN:
        if (ev->button == KD_BUTTON_LEFT) pointer_down(d, ev);
        break;
    case KD_EV_POINTER_UP:
        if (ev->button == KD_BUTTON_LEFT) pointer_up(d, ev);
        break;
    case KD_EV_KEY: key(d, ev); break;
    default: break;
    }
}

// ---- composition ----

static int collect_layers(kd_desktop *d, layer out[KD_MAX_WINDOWS + 3]) {
    int n = 0;
    if (d->menu_open >= 0)
        out[n++] = (layer){LAYER_DROPDOWN, NULL, kd_menu_dropdown_rect(d->menus, d->menu_open)};
    out[n++] = (layer){LAYER_MENUBAR, NULL, menubar_rect()};
    if (!kd_rect_empty(d->popup)) out[n++] = (layer){LAYER_POPUP, NULL, d->popup};
    for (int i = d->zn - 1; i >= 0; i--) {
        kd_window *w = &d->win[d->z[i]];
        out[n++] = (layer){LAYER_WINDOW, w, w->frame};
    }
    return n;
}

static void draw_layer(kd_desktop *d, const layer *l, kd_rect clip) {
    kd_fb *fb = &d->fb;
    kd_fb_set_clip(fb, clip);
    d->stats.layers++;
    if (l->kind == LAYER_DROPDOWN) {
        kd_gfx_dropdown(fb, d->menus, d->menu_open, d->menu_hot);
    } else if (l->kind == LAYER_MENUBAR) {
        kd_gfx_menubar(fb, d->menus, d->menu_open);
        kd_rect sb = kd_desktop_status_box(d);
        kd_rect sc = kd_rect_intersect(clip, sb);
        if (!kd_rect_empty(sc)) {
            kd_fb_set_clip(fb, sc);
            int w = kd_text_width_n(&kd_font_system, d->status, d->status_len);
            int x = sb.x + 2 + (sb.w - 4 >= w ? sb.w - 4 - w : 0);
            kd_text_n(fb, &kd_font_system, x, 1, d->status, d->status_len, KD_C_BLACK, KD_NO_KEY);
        }
    } else if (l->kind == LAYER_POPUP) {
        d->popup_draw(d->popup_ctx, fb);
    } else {
        kd_window *w = l->w;
        kd_gfx_frame(fb, w->frame, w->title, w == kd_desktop_top(d), (w->flags & KD_WF_CLOSE) != 0);
        kd_rect work = kd_frame_work(w->frame);
        kd_rect c = kd_rect_intersect(clip, work);
        if (!kd_rect_empty(c) && w->cls && w->cls->draw) {
            kd_fb_set_clip(fb, c);
            kd_draw dr = {fb, work.x, work.y, work.w, work.h};
            w->cls->draw(w, &dr);
        }
    }
}

static void draw_desktop(kd_desktop *d, kd_rect clip) {
    kd_fb *fb = &d->fb;
    kd_fb_set_clip(fb, clip);
    d->stats.layers++;
    kd_gfx_desktop(fb, clip);
    for (int i = 0; i < d->nicons; i++) {
        const kd_desk_icon *ic = &d->icons[i];
        if (kd_rect_overlaps(kd_icon_box(ic->x, ic->y, ic->label), clip))
            kd_gfx_icon(fb, ic->x, ic->y, ic->art, ic->label, i == d->icon_sel);
    }
}

static void draw_overlays(kd_desktop *d, kd_rect clip) {
    kd_fb_set_clip(&d->fb, clip);
    if (d->drag == KD_DRAG_OUTLINE && kd_rect_overlaps(d->outline, clip))
        kd_gfx_outline(&d->fb, d->outline);
    if (d->cursor_on && kd_rect_overlaps(kd_cursor_rect(d), clip))
        kd_gfx_art(&d->fb, d->px, d->py, &kd_art_cursor, KD_C_BLACK, KD_C_WHITE);
}

static void compose_painter(kd_desktop *d, kd_rect area) {
    layer l[KD_MAX_WINDOWS + 3];
    int n = collect_layers(d, l);
    draw_desktop(d, area);
    for (int k = n - 1; k >= 0; k--) {
        kd_rect p = kd_rect_intersect(area, l[k].r);
        if (!kd_rect_empty(p)) draw_layer(d, &l[k], p);
    }
    draw_overlays(d, area);
}

static void compose_region(kd_desktop *d, kd_rect area) {
    layer l[KD_MAX_WINDOWS + 3];
    int n = collect_layers(d, l);
    kd_region g;
    kd_region_init(&g, area);
    for (int k = 0; k < n && g.n; k++) {
        for (int j = 0; j < g.n; j++) {
            kd_rect p = kd_rect_intersect(g.r[j], l[k].r);
            if (!kd_rect_empty(p)) draw_layer(d, &l[k], p);
        }
        if (!KD_FAULTY(KD_FAULT_NO_SUBTRACT)) kd_region_subtract(&g, l[k].r);
        if (g.overflow) {
            d->stats.fallbacks++;
            compose_painter(d, area);
            return;
        }
    }
    for (int j = 0; j < g.n; j++) draw_desktop(d, g.r[j]);
    draw_overlays(d, area);
}

// Layers overdraw inside themselves (a window fills its background, then
// draws text), so a byte can change and change back within one pass. The
// raster marks such tiles dirty. To keep the dirty map equal to "differs from
// before the render", each pass snapshots its tiles first and afterwards sets
// dirty = (dirty before) || (content differs). A pass covers at most
// KD_SNAP_TILES tiles; larger damage is composed in bands of tile rows.
static void compose_exact(kd_desktop *d, kd_rect area) {
    kd_fb *fb = &d->fb;
    int tx0 = area.x >> 3, tx1 = (area.x + area.w - 1) >> 3;
    int ty0 = area.y >> 3, ty1 = (area.y + area.h - 1) >> 3;
    int cols = tx1 - tx0 + 1, rows_per_pass = KD_SNAP_TILES / cols;
    int span = cols * 4;   // bytes of a pixel row across the band's tiles
    bool was[KD_SNAP_TILES];
    for (int ty = ty0; ty <= ty1; ty += rows_per_pass) {
        int tyn = ty + rows_per_pass - 1 < ty1 ? ty + rows_per_pass - 1 : ty1;
        kd_rect band = kd_rect_intersect(area, kd_rect_make(0, ty * 8, KD_W, (tyn - ty + 1) * 8));
        // Snapshot the band's pixel rows: one copy per row (a copy per tile
        // row cost thousands of small library calls per pass on the RP2040).
        const uint8_t *src = fb->px + ty * 8 * KD_STRIDE + tx0 * 4;
        for (int r = 0; r < (tyn - ty + 1) * 8; r++) memcpy(d->snap + r * span, src + r * KD_STRIDE, (size_t)span);
        int k = 0;
        for (int y = ty; y <= tyn; y++)
            for (int x = tx0; x <= tx1; x++, k++) was[k] = kd_fb_tile_dirty(fb, (unsigned)(y * KD_TILE_COLS + x));
        d->stats.passes++;
        if (d->painter) compose_painter(d, band);
        else compose_region(d, band);
        k = 0;
        for (int y = ty; y <= tyn; y++)
            for (int x = tx0; x <= tx1; x++, k++) {
                unsigned t = (unsigned)(y * KD_TILE_COLS + x);
                const uint8_t *now = fb->px + y * 8 * KD_STRIDE + x * 4;
                const uint8_t *old = d->snap + (y - ty) * 8 * span + (x - tx0) * 4;
                bool changed = false;
                for (int r = 0; r < 8 && !changed; r++, now += KD_STRIDE, old += span)
                    changed = now[0] != old[0] || now[1] != old[1] || now[2] != old[2] || now[3] != old[3];
                if (!was[k] && !changed && kd_fb_tile_dirty(fb, t)) d->stats.suppressed++;
                kd_fb_set_tile_dirty(fb, t, was[k] || changed);
            }
    }
}

bool kd_desktop_render(kd_desktop *d) {
    if (d->damage.n == 0) return false;
    kd_damage work = d->damage;
    kd_damage_clear(&d->damage);
    d->stats.renders++;
    d->stats.rects += work.n;
    d->stats.last_rects = work.n;
    d->stats.last_area = kd_damage_area(&work);
    d->stats.last_damage_tiles = kd_damage_tiles(&work);
    for (int i = 0; i < work.n; i++) compose_exact(d, work.r[i]);
    kd_fb_reset_clip(&d->fb);
    return true;
}
