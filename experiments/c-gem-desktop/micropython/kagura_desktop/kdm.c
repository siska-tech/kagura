// SPDX-License-Identifier: Apache-2.0
// Retained-mode layer for script-driven windows (see kdm.h).
#include "kdm.h"

#include <string.h>

// Fault injection for the mutation tests (tests/CMakeLists.txt): a normal
// build has KDM_FAULT 0 and every KDM_FAULTY() is a constant false.
#ifndef KDM_FAULT
#define KDM_FAULT 0
#endif
#define KDM_FAULTY(n) (KDM_FAULT == (n))
enum {
    KDM_FAULT_SERIAL = 1,          // item ids are not checked against the serial
    KDM_FAULT_TEXT_CELLS = 2,      // set_text skips the cells a shorter text frees
    KDM_FAULT_COMPACT = 3,         // compaction moves strings without updating records
    KDM_FAULT_SPRITE_DAMAGE = 4,   // sprite pixel changes invalidate nothing
    KDM_FAULT_CLOSE_LEAK = 5,      // a closed window keeps its records
    KDM_FAULT_RING = 6,            // a full event ring overwrites the oldest event
    KDM_FAULT_MOVE_OLD = 7,        // moving a record does not invalidate its old box
};

static const kd_art *const icon_art[] = {
    &kd_art_folder, &kd_art_file, &kd_art_drive, &kd_art_trash, &kd_art_studio, &kd_art_app, &kd_art_text,
};
const char *const kdm_icon_names[] = {"folder", "file", "drive", "trash", "studio", "app", "text", NULL};

static bool fits16(int v) { return v >= -32768 && v <= 32767; }
static bool fits_rect(int x, int y, int w, int h) {
    return fits16(x) && fits16(y) && w >= 0 && h >= 0 && w <= 32767 && h <= 32767;
}
static bool has_text(const kdm_item *it) {
    return it->op == KDM_OP_TEXT || it->op == KDM_OP_TEXT_SMALL || it->op == KDM_OP_BUTTON || it->op == KDM_OP_ICON;
}

uint32_t kdm_crc32(uint32_t c, const uint8_t *p, size_t n) {
    c = ~c;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1)));
    }
    return ~c;
}

int kdm_icon_lookup(const char *name, size_t len) {
    for (int i = 0; kdm_icon_names[i]; i++)
        if (strlen(kdm_icon_names[i]) == len && memcmp(kdm_icon_names[i], name, len) == 0) return i;
    return KDM_EINVAL;
}

// ---- events ----

static void push(kdm *m, const kd_event *ev, int slot) {
    if (m->ring_count == KDM_EVENTS) {
        if (!KDM_FAULTY(KDM_FAULT_RING)) {
            m->stats.dropped++;
            return;
        }
        m->ring_head = (uint8_t)((m->ring_head + 1) % KDM_EVENTS);
        m->ring_count--;
    }
    kdm_event *e = &m->ring[(m->ring_head + m->ring_count) % KDM_EVENTS];
    e->ev = *ev;
    e->win = (int8_t)slot;
    e->serial = slot >= 0 ? m->win[slot].serial : 0;
    m->ring_count++;
}

bool kdm_peek(const kdm *m, kdm_event *out) {
    if (!m->ring_count) return false;
    *out = m->ring[m->ring_head];
    return true;
}

void kdm_drop(kdm *m) {
    if (!m->ring_count) return;
    m->ring_head = (uint8_t)((m->ring_head + 1) % KDM_EVENTS);
    m->ring_count--;
}

void kdm_feed(kdm *m, const kd_event *ev) { kd_desktop_event(&m->desk, ev); }

static void menu_hook(kd_desktop *d, int menu, int item, void *ctx) {
    (void)d;
    kd_event ev;
    memset(&ev, 0, sizeof ev);
    ev.type = KDM_EV_MENU;
    ev.key = (uint8_t)menu;
    ev.ch = (char)item;
    push((kdm *)ctx, &ev, -1);
}

// ---- text arena ----

// Moves live strings down to the start of the arena, in address order.
static void compact(kdm *m) {
    uint16_t lo = 0, scan = 0;
    for (;;) {
        int best = -1;
        for (int i = 0; i < KDM_MAX_ITEMS; i++) {
            const kdm_item *it = &m->items[i];
            if (has_text(it) && it->aux >= scan && (best < 0 || it->aux < m->items[best].aux)) best = i;
        }
        if (best < 0) break;
        kdm_item *it = &m->items[best];
        uint16_t len = (uint16_t)(strlen(m->text + it->aux) + 1);
        scan = (uint16_t)(it->aux + len);
        memmove(m->text + lo, m->text + it->aux, len);
        if (!KDM_FAULTY(KDM_FAULT_COMPACT)) it->aux = lo;
        lo = (uint16_t)(lo + len);
    }
    m->text_top = lo;
    m->stats.compactions++;
}

// Copies s[0..len) plus NUL into the arena. Returns the offset or an error.
static int text_alloc(kdm *m, const char *s, size_t len) {
    if (len > KDM_TEXT_MAX || memchr(s, 0, len)) return KDM_EINVAL;
    size_t need = len + 1;
    if (m->text_top + need > KDM_TEXT_BYTES) {
        if (m->stats.text + need > KDM_TEXT_BYTES) return KDM_ENOTEXT;
        compact(m);
    }
    int off = m->text_top;
    memcpy(m->text + off, s, len);
    m->text[off + len] = 0;
    m->text_top = (uint16_t)(off + need);
    m->stats.text = (uint16_t)(m->stats.text + need);
    if (m->stats.text > m->stats.text_peak) m->stats.text_peak = m->stats.text;
    return off;
}

static void text_free(kdm *m, uint16_t off) {
    m->stats.text = (uint16_t)(m->stats.text - (strlen(m->text + off) + 1));
}

// ---- records ----

static kd_rect item_box(const kdm *m, const kdm_item *it) {
    if (it->op == KDM_OP_ICON) return kd_icon_box(it->x, it->y, m->text + it->aux);
    kd_rect r = kd_rect_make(it->x, it->y, it->w, it->h);
    if (it->op == KDM_OP_BUTTON) {   // kd_gfx_button centres the label without clipping it
        int tw = kd_text_width(&kd_font_system, m->text + it->aux);
        r = kd_rect_union(r, kd_rect_make(it->x + (it->w - tw) / 2, it->y + (it->h - 8) / 2, tw, 8));
    }
    return r;
}

static void invalidate(kdm *m, int slot, kd_rect r) {
    if (!kd_rect_empty(r)) kd_window_invalidate(&m->desk, &m->desk.win[slot], r);
}

static int item_id(const kdm *m, int i) { return i | m->items[i].serial << KDM_ITEM_BITS; }

static kdm_item *item_get(kdm *m, int slot, int id) {
    if (id < 0) return NULL;
    int i = id & ((1 << KDM_ITEM_BITS) - 1);
    if (i >= KDM_MAX_ITEMS) return NULL;
    kdm_item *it = &m->items[i];
    if (it->op == KDM_OP_FREE || it->win != slot || (it->serial != (unsigned)(id >> KDM_ITEM_BITS) && !KDM_FAULTY(KDM_FAULT_SERIAL)))
        return NULL;
    return it;
}

// Takes a record from the free list and appends it to the window's list.
static int item_new(kdm *m, int slot, uint8_t op) {
    uint16_t i = m->free_item;
    if (i == KDM_NONE) return KDM_ENOITEM;
    kdm_item *it = &m->items[i];
    m->free_item = it->next;
    if (++m->item_serial == 0 || m->item_serial > 0x3FFF) m->item_serial = 1;
    memset(it, 0, sizeof *it);
    it->op = op;
    it->win = (uint8_t)slot;
    it->serial = m->item_serial;
    it->next = KDM_NONE;
    kdm_window *w = &m->win[slot];
    if (w->tail == KDM_NONE) w->head = i;
    else m->items[w->tail].next = i;
    w->tail = i;
    if (++m->stats.items > m->stats.items_peak) m->stats.items_peak = m->stats.items;
    return i;
}

static void item_release(kdm *m, int i) {
    kdm_item *it = &m->items[i];
    if (has_text(it)) text_free(m, it->aux);
    it->op = KDM_OP_FREE;
    it->next = m->free_item;
    m->free_item = (uint16_t)i;
    m->stats.items--;
}

static void unlink_item(kdm *m, int slot, int i) {
    kdm_window *w = &m->win[slot];
    uint16_t prev = KDM_NONE;
    for (uint16_t k = w->head; k != KDM_NONE; prev = k, k = m->items[k].next) {
        if (k != i) continue;
        uint16_t next = m->items[k].next;
        if (prev == KDM_NONE) w->head = next;
        else m->items[prev].next = next;
        if (w->tail == k) w->tail = prev;
        return;
    }
}

static void free_list(kdm *m, int slot) {
    kdm_window *w = &m->win[slot];
    for (uint16_t k = w->head; k != KDM_NONE;) {
        uint16_t next = m->items[k].next;
        item_release(m, k);
        k = next;
    }
    w->head = w->tail = KDM_NONE;
}

static bool window_ok(const kdm *m, int slot) {
    return slot >= 0 && slot < KD_MAX_WINDOWS && m->win[slot].open;
}

// ---- window class ----

static int slot_of(const kdm *m, const kd_window *w) { return (int)(w - m->desk.win); }

static void draw(kd_window *w, const kd_draw *d) {
    kdm *m = kd_window_user(w);
    int slot = slot_of(m, w);
    kd_draw_fill(d, 0, 0, d->w, d->h, m->win[slot].bg);
    for (uint16_t i = m->win[slot].head; i != KDM_NONE; i = m->items[i].next) {
        const kdm_item *it = &m->items[i];
        if (!kd_draw_visible(d, item_box(m, it))) continue;
        switch (it->op) {
        case KDM_OP_FILL: kd_draw_fill(d, it->x, it->y, it->w, it->h, it->c0); break;
        case KDM_OP_RECT: kd_draw_rect(d, it->x, it->y, it->w, it->h, it->c0); break;
        case KDM_OP_HLINE: kd_draw_hline(d, it->x, it->y, it->w, it->c0); break;
        case KDM_OP_VLINE: kd_draw_vline(d, it->x, it->y, it->h, it->c0); break;
        case KDM_OP_TEXT:
        case KDM_OP_TEXT_SMALL:
            kd_draw_text(d, it->op == KDM_OP_TEXT ? &kd_font_system : &kd_font_small, it->x, it->y,
                         m->text + it->aux, it->c0, it->c1 == KDM_NO_BG ? KD_NO_KEY : it->c1);
            break;
        case KDM_OP_BUTTON: kd_draw_button(d, item_box(m, it), m->text + it->aux, it->c0); break;
        case KDM_OP_SPRITE:
            kd_draw_sprite(d, it->x, it->y, &m->sprites[it->aux].px, it->c0, it->c1 == KDM_NO_BG ? KD_NO_KEY : it->c1);
            break;
        case KDM_OP_ICON: kd_draw_icon(d, it->x, it->y, icon_art[it->c0], m->text + it->aux, it->c1 != 0); break;
        default: break;
        }
    }
}

static bool event(kd_window *w, const kd_event *ev) {
    kdm *m = kd_window_user(w);
    push(m, ev, slot_of(m, w));
    return true;
}

// After the core removed the window (it already damaged the uncovered area).
static void closed(kd_window *w) {
    kdm *m = kd_window_user(w);
    int slot = slot_of(m, w);
    if (!KDM_FAULTY(KDM_FAULT_CLOSE_LEAK)) free_list(m, slot);
    m->win[slot].open = false;
    if (m->api_closing != slot) {
        kd_event ev;
        memset(&ev, 0, sizeof ev);
        ev.type = KDM_EV_CLOSE;
        push(m, &ev, slot);
    }
}

static const kd_window_class kdm_class = {draw, event, closed};

// ---- desktop ----

static int copy_str(kdm *m, size_t *used, const char *s, const char **out) {
    size_t n = strlen(s) + 1;
    if (*used + n > KDM_MENU_TEXT) return KDM_ENOMENU;
    memcpy(m->menu_text + *used, s, n);
    *out = m->menu_text + *used;
    *used += n;
    return KDM_OK;
}

static int set_menus(kdm *m, const kdm_menu_def *def) {
    size_t used = 0;
    if (!def) return KDM_OK;
    if (def->count < 0 || def->count > KDM_MENUS) return KDM_ENOMENU;
    for (int i = 0; i < def->count; i++) {
        if (def->counts[i] < 1 || def->counts[i] > KDM_MENU_ITEMS) return KDM_ENOMENU;
        if (copy_str(m, &used, def->titles[i], &m->menus[i].title)) return KDM_ENOMENU;
        for (int k = 0; k < def->counts[i]; k++)
            if (copy_str(m, &used, def->items[i][k], &m->menu_items[i][k].label)) return KDM_ENOMENU;
        m->menus[i].items = m->menu_items[i];
    }
    return KDM_OK;
}

int kdm_init(kdm *m, const kdm_menu_def *menus) {
    uint32_t generation = m->generation + 1, serial = m->next_serial;
    memset(m, 0, sizeof *m);
    m->generation = generation;
    m->next_serial = serial;
    m->api_closing = -1;
    int rc = set_menus(m, menus);
    if (rc) memset(m->menus, 0, sizeof m->menus);   // the desktop still works, without menus
    for (int i = 0; i < KDM_MAX_ITEMS; i++) m->items[i].next = i + 1 < KDM_MAX_ITEMS ? (uint16_t)(i + 1) : KDM_NONE;
    for (int s = 0; s < KD_MAX_WINDOWS; s++) m->win[s].head = m->win[s].tail = KDM_NONE;
    kd_shell_hooks hooks = {menu_hook, NULL, m};
    kd_desktop_init(&m->desk, m->menus, NULL, 0, hooks);
    return rc;
}

int kdm_window_open(kdm *m, const char *title, kd_rect frame, unsigned flags, uint8_t bg) {
    if (frame.w < 32 || frame.h < 24 || frame.w > KD_W || frame.h > KD_H || bg > 15) return KDM_EINVAL;
    int slot = -1;   // kd_window_open takes the lowest free slot
    for (int s = 0; s < KD_MAX_WINDOWS && slot < 0; s++)
        if (!m->desk.win[s].open) slot = s;
    if (slot < 0) return KDM_ENOWIN;
    kdm_window *w = &m->win[slot];
    w->serial = ++m->next_serial;
    w->head = w->tail = KDM_NONE;
    w->bg = bg;
    w->open = true;   // before the core sends FOCUS
    kd_window *kw = kd_window_open(&m->desk, &kdm_class, m, title, frame, flags & (KD_WF_CLOSE | KD_WF_MOVE));
    if (kw != &m->desk.win[slot]) {   // cannot happen: the core picks the same slot
        w->open = false;
        return KDM_ENOWIN;
    }
    return slot;
}

int kdm_window_check(const kdm *m, int slot, uint32_t serial) {
    return window_ok(m, slot) && m->win[slot].serial == serial ? KDM_OK : KDM_ESTALE;
}

kd_window *kdm_window_core(kdm *m, int slot) { return window_ok(m, slot) ? &m->desk.win[slot] : NULL; }

int kdm_window_close(kdm *m, int slot) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    m->api_closing = (int8_t)slot;
    kd_window_close(&m->desk, &m->desk.win[slot]);
    m->api_closing = -1;
    return KDM_OK;
}

int kdm_window_activate(kdm *m, int slot) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kd_desktop_activate(&m->desk, &m->desk.win[slot]);
    return KDM_OK;
}

int kdm_window_move(kdm *m, int slot, int x, int y) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (!fits16(x) || !fits16(y)) return KDM_EINVAL;
    kd_desktop_move(&m->desk, &m->desk.win[slot], x, y);
    return KDM_OK;
}

int kdm_window_set_title(kdm *m, int slot, const char *title) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kd_window_set_title(&m->desk, &m->desk.win[slot], title);
    return KDM_OK;
}

int kdm_window_clear(kdm *m, int slot, int bg) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (bg > 15) return KDM_EINVAL;
    free_list(m, slot);
    if (bg >= 0) m->win[slot].bg = (uint8_t)bg;
    kd_window_invalidate_all(&m->desk, &m->desk.win[slot]);
    return KDM_OK;
}

// ---- adding records ----

static int add_shape(kdm *m, int slot, uint8_t op, int x, int y, int w, int h, int color) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (!fits_rect(x, y, w, h) || color < 0 || color > 15) return KDM_EINVAL;
    int i = item_new(m, slot, op);
    if (i < 0) return i;
    kdm_item *it = &m->items[i];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->w = (int16_t)w;
    it->h = (int16_t)h;
    it->c0 = (uint8_t)color;
    invalidate(m, slot, item_box(m, it));
    return item_id(m, i);
}

int kdm_add_fill(kdm *m, int slot, int x, int y, int w, int h, uint8_t c) {
    return add_shape(m, slot, KDM_OP_FILL, x, y, w, h, c);
}
int kdm_add_rect(kdm *m, int slot, int x, int y, int w, int h, uint8_t c) {
    return add_shape(m, slot, KDM_OP_RECT, x, y, w, h, c);
}
int kdm_add_hline(kdm *m, int slot, int x, int y, int w, uint8_t c) {
    return add_shape(m, slot, KDM_OP_HLINE, x, y, w, 1, c);
}
int kdm_add_vline(kdm *m, int slot, int x, int y, int h, uint8_t c) {
    return add_shape(m, slot, KDM_OP_VLINE, x, y, 1, h, c);
}

int kdm_add_fills(kdm *m, int slot, const int16_t *q, int n, uint8_t color) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (n < 0 || color > 15) return KDM_EINVAL;
    for (int k = 0; k < n; k++)
        if (q[4 * k + 2] < 0 || q[4 * k + 3] < 0) return KDM_EINVAL;
    if (KDM_MAX_ITEMS - m->stats.items < n) return KDM_ENOITEM;
    for (int k = 0; k < n; k++) add_shape(m, slot, KDM_OP_FILL, q[4 * k], q[4 * k + 1], q[4 * k + 2], q[4 * k + 3], color);
    return n;
}

static int add_with_text(kdm *m, int slot, uint8_t op, const char *s, size_t len) {
    if (m->free_item == KDM_NONE) return KDM_ENOITEM;
    int off = text_alloc(m, s, len);
    if (off < 0) return off;
    int i = item_new(m, slot, op);
    m->items[i].aux = (uint16_t)off;
    return i;
}

int kdm_add_text(kdm *m, int slot, int x, int y, const char *s, size_t len, uint8_t fg, int bg, int font) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (!fits16(x) || !fits16(y) || fg > 15 || bg > 15 || (font != 0 && font != 1)) return KDM_EINVAL;
    int i = add_with_text(m, slot, font ? KDM_OP_TEXT_SMALL : KDM_OP_TEXT, s, len);
    if (i < 0) return i;
    kdm_item *it = &m->items[i];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->w = (int16_t)(len * (font ? kd_font_small.width : kd_font_system.width));
    it->h = 8;
    it->c0 = fg;
    it->c1 = bg < 0 ? KDM_NO_BG : (uint8_t)bg;
    invalidate(m, slot, item_box(m, it));
    return item_id(m, i);
}

int kdm_add_button(kdm *m, int slot, int x, int y, int w, int h, const char *label, size_t len, unsigned flags) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (!fits_rect(x, y, w, h) || flags > 15) return KDM_EINVAL;
    int i = add_with_text(m, slot, KDM_OP_BUTTON, label, len);
    if (i < 0) return i;
    kdm_item *it = &m->items[i];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->w = (int16_t)w;
    it->h = (int16_t)h;
    it->c0 = (uint8_t)flags;
    invalidate(m, slot, item_box(m, it));
    return item_id(m, i);
}

int kdm_add_icon(kdm *m, int slot, int x, int y, int art, const char *label, size_t len, bool selected) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (!fits16(x) || !fits16(y) || art < 0 || art >= (int)(sizeof icon_art / sizeof icon_art[0])) return KDM_EINVAL;
    int i = add_with_text(m, slot, KDM_OP_ICON, label, len);
    if (i < 0) return i;
    kdm_item *it = &m->items[i];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->c0 = (uint8_t)art;
    it->c1 = selected;
    invalidate(m, slot, item_box(m, it));
    return item_id(m, i);
}

static bool sprite_ok(const kdm *m, int s) { return s >= 0 && s < KDM_MAX_SPRITES && m->sprites[s].used; }

int kdm_add_sprite(kdm *m, int slot, int x, int y, int s, int zoom, int key) {
    if (!window_ok(m, slot) || !sprite_ok(m, s)) return KDM_ESTALE;
    if (!fits16(x) || !fits16(y) || zoom < 1 || zoom > 16 || key > 15) return KDM_EINVAL;
    int i = item_new(m, slot, KDM_OP_SPRITE);
    if (i < 0) return i;
    kdm_item *it = &m->items[i];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->w = it->h = (int16_t)(KD_SPRITE_W * zoom);
    it->c0 = (uint8_t)zoom;
    it->c1 = key < 0 ? KDM_NO_BG : (uint8_t)key;
    it->aux = (uint16_t)s;
    invalidate(m, slot, item_box(m, it));
    return item_id(m, i);
}

// ---- changing records ----

int kdm_item_set_text(kdm *m, int slot, int id, const char *s, size_t len) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (!has_text(it)) return KDM_EINVAL;
    size_t la = strlen(m->text + it->aux);
    if (la == len && memcmp(m->text + it->aux, s, len) == 0) return KDM_OK;
    kd_rect before = item_box(m, it);
    // The old string stays live during the allocation, which may compact the
    // arena and move it (it->aux follows); it is released afterwards.
    int off = text_alloc(m, s, len);
    if (off < 0) return off;
    const char *a = m->text + it->aux, *b = m->text + off;
    m->stats.text = (uint16_t)(m->stats.text - (la + 1));
    if (it->op == KDM_OP_TEXT || it->op == KDM_OP_TEXT_SMALL) {
        // Fixed-width cells: invalidate runs of cells that differ, as kd_label_set.
        int cw = it->op == KDM_OP_TEXT ? kd_font_system.width : kd_font_small.width;
        size_t n = la > len ? la : len;
        for (size_t c = 0; c < n;) {
            if (c < la && c < len && a[c] == b[c]) { c++; continue; }
            if (KDM_FAULTY(KDM_FAULT_TEXT_CELLS) && c >= len) break;
            size_t e = c + 1;
            while (e < n && !(e < la && e < len && a[e] == b[e])) e++;
            invalidate(m, slot, kd_rect_make(it->x + (int)c * cw, it->y, (int)(e - c) * cw, it->h));
            c = e;
        }
        it->aux = (uint16_t)off;
        it->w = (int16_t)(len * cw);
        return KDM_OK;
    }
    it->aux = (uint16_t)off;
    invalidate(m, slot, before);
    invalidate(m, slot, item_box(m, it));
    return KDM_OK;
}

int kdm_item_set_color(kdm *m, int slot, int id, uint8_t color) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (color > 15 || it->op == KDM_OP_SPRITE || it->op == KDM_OP_BUTTON || it->op == KDM_OP_ICON) return KDM_EINVAL;
    if (it->c0 == color) return KDM_OK;
    it->c0 = color;
    invalidate(m, slot, item_box(m, it));
    return KDM_OK;
}

int kdm_item_set_flags(kdm *m, int slot, int id, unsigned flags) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (flags > 15 || (it->op != KDM_OP_BUTTON && it->op != KDM_OP_ICON)) return KDM_EINVAL;
    uint8_t *f = it->op == KDM_OP_BUTTON ? &it->c0 : &it->c1;
    uint8_t v = (uint8_t)(it->op == KDM_OP_BUTTON ? flags : flags != 0);
    if (*f == v) return KDM_OK;
    *f = v;
    invalidate(m, slot, item_box(m, it));
    return KDM_OK;
}

int kdm_item_move(kdm *m, int slot, int id, int x, int y) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (!fits16(x) || !fits16(y)) return KDM_EINVAL;
    if (it->x == x && it->y == y) return KDM_OK;
    if (!KDM_FAULTY(KDM_FAULT_MOVE_OLD)) invalidate(m, slot, item_box(m, it));
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    invalidate(m, slot, item_box(m, it));
    return KDM_OK;
}

int kdm_item_remove(kdm *m, int slot, int id) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    int i = (int)(it - m->items);
    invalidate(m, slot, item_box(m, it));
    unlink_item(m, slot, i);
    item_release(m, i);
    return KDM_OK;
}

// ---- sprites ----

int kdm_sprite_alloc(kdm *m, const uint8_t *data) {
    for (int s = 0; s < KDM_MAX_SPRITES; s++) {
        kdm_sprite *sp = &m->sprites[s];
        if (sp->used) continue;
        if (data) memcpy(sp->px.data, data, KD_SPRITE_BYTES);
        else memset(sp->px.data, 0, KD_SPRITE_BYTES);
        sp->used = true;
        sp->serial = ++m->next_serial;
        return s;
    }
    return KDM_ENOSPRITE;
}

int kdm_sprite_check(const kdm *m, int s, uint32_t serial) {
    return sprite_ok(m, s) && m->sprites[s].serial == serial ? KDM_OK : KDM_ESTALE;
}

int kdm_sprite_free(kdm *m, int s) {
    if (!sprite_ok(m, s)) return KDM_ESTALE;
    for (int i = 0; i < KDM_MAX_ITEMS; i++) {
        kdm_item *it = &m->items[i];
        if (it->op != KDM_OP_SPRITE || it->aux != s) continue;
        kdm_item_remove(m, it->win, item_id(m, i));
    }
    m->sprites[s].used = false;
    return KDM_OK;
}

// Invalidates pixel (x, y) of sprite s in every record that shows it; x < 0
// invalidates the whole record.
static void sprite_damage(kdm *m, int s, int x, int y) {
    if (KDM_FAULTY(KDM_FAULT_SPRITE_DAMAGE)) return;
    for (int i = 0; i < KDM_MAX_ITEMS; i++) {
        const kdm_item *it = &m->items[i];
        if (it->op != KDM_OP_SPRITE || it->aux != s) continue;
        int z = it->c0;
        invalidate(m, it->win, x < 0 ? item_box(m, it) : kd_rect_make(it->x + x * z, it->y + y * z, z, z));
    }
}

int kdm_sprite_set(kdm *m, int s, int x, int y, int color) {
    if (!sprite_ok(m, s)) return KDM_ESTALE;
    if (x < 0 || x >= KD_SPRITE_W || y < 0 || y >= KD_SPRITE_H || color < 0 || color > 15) return KDM_EINVAL;
    if (!kd_sprite_set(&m->sprites[s].px, x, y, color)) return 0;
    sprite_damage(m, s, x, y);
    return 1;
}

int kdm_sprite_set_many(kdm *m, int s, const uint8_t *xyc, int n) {
    if (!sprite_ok(m, s)) return KDM_ESTALE;
    for (int k = 0; k < n; k++)
        if (xyc[3 * k] >= KD_SPRITE_W || xyc[3 * k + 1] >= KD_SPRITE_H || xyc[3 * k + 2] > 15) return KDM_EINVAL;
    int changed = 0;
    for (int k = 0; k < n; k++) changed += kdm_sprite_set(m, s, xyc[3 * k], xyc[3 * k + 1], xyc[3 * k + 2]);
    return changed;
}

// Like the C Studio: up to 16 changed pixels are invalidated one by one,
// anything larger as whole records.
int kdm_sprite_load(kdm *m, int s, const uint8_t data[KD_SPRITE_BYTES]) {
    if (!sprite_ok(m, s)) return KDM_ESTALE;
    kd_sprite next;
    memcpy(next.data, data, KD_SPRITE_BYTES);
    int changed = 0;
    for (int y = 0; y < KD_SPRITE_H; y++)
        for (int x = 0; x < KD_SPRITE_W; x++) changed += kd_sprite_get(&next, x, y) != kd_sprite_get(&m->sprites[s].px, x, y);
    if (changed > 16) {
        m->sprites[s].px = next;
        sprite_damage(m, s, -1, -1);
        return changed;
    }
    for (int y = 0; y < KD_SPRITE_H; y++)
        for (int x = 0; x < KD_SPRITE_W; x++) kdm_sprite_set(m, s, x, y, kd_sprite_get(&next, x, y));
    return changed;
}

int kdm_sprite_fill(kdm *m, int s, int color) {
    if (!sprite_ok(m, s)) return KDM_ESTALE;
    if (color < 0 || color > 15) return KDM_EINVAL;
    uint8_t data[KD_SPRITE_BYTES];
    memset(data, (color << 4) | color, sizeof data);
    return kdm_sprite_load(m, s, data);
}

// ---- composition ----

static bool discard(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    (void)ctx, (void)first, (void)count, (void)data;
    return true;
}

bool kdm_render(kdm *m) { return kd_desktop_render(&m->desk); }

int kdm_present(kdm *m, kd_tile4_sink sink, void *ctx, kd_tile4_stats *st) {
    kd_tile4_stats local;
    if (!st) st = &local;
    kd_desktop_render(&m->desk);
    bool ok = kd_tile4_flush(&m->desk.fb, 0, m->staging, KD_TILE_COLS, sink ? sink : discard, ctx, st);
    m->stats.presents++;
    m->stats.tiles += st->tiles;
    m->stats.runs += st->runs;
    return ok ? (int)st->tiles : KDM_ESINK;
}
