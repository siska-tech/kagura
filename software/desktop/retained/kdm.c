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
    KDM_FAULT_FIELD_TEXT = 8,      // a field edit does not invalidate the changed text
    KDM_FAULT_FIELD_CARET = 9,     // a field motion does not invalidate the old caret
    KDM_FAULT_EDITOR_ROWS = 10,    // an editor line break does not redraw the lines below
    KDM_FAULT_PREEDIT = 11,        // a preedit change invalidates nothing
};

static const kd_art *const icon_art[] = {
    &kd_art_folder, &kd_art_file, &kd_art_drive, &kd_art_trash, &kd_art_studio, &kd_art_app, &kd_art_text,
};
const char *const kdm_icon_names[] = {"folder", "file", "drive", "trash", "studio", "app", "text", NULL};

static bool fits16(int v) { return v >= -32768 && v <= 32767; }
static bool fits_rect(int x, int y, int w, int h) {
    return fits16(x) && fits16(y) && w >= 0 && h >= 0 && w <= 32767 && h <= 32767;
}
static bool ascii(const char *s, size_t n) {
    for (size_t i = 0; i < n; i++)
        if ((unsigned char)s[i] >= 0x80) return false;
    return true;
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
    if (it->op == KDM_OP_FIELD) return kd_rect_make(it->x, it->y, it->w, KDM_FIELD_H);
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
    if (it->op == KDM_OP_FIELD || it->op == KDM_OP_EDITOR) m->fields[it->aux].item = KDM_NONE;
    if (m->preedit_item == i) {
        m->preedit_item = KDM_NONE;
        m->preedit_len = 0;
    }
    if (m->win[it->win].focus == i) m->win[it->win].focus = KDM_NONE;
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

// ---- fields and focus ----

static int slot_of(const kdm *m, const kd_window *w) { return (int)(w - m->desk.win); }

static bool editable(const kdm_item *it) { return it->op == KDM_OP_FIELD || it->op == KDM_OP_EDITOR; }

static bool focusable(const kdm_item *it) {
    return editable(it) || (it->op == KDM_OP_BUTTON && it->c1);
}

// The focus is drawn only while the window is the active one.
static bool shows_focus(const kdm *m, int slot, int i) {
    return m->win[slot].focus == i && kd_window_is_active(&m->desk.win[slot]);
}

static const kd_font *field_font(const kdm_item *it) { return it->c0 ? &kd_font_small : &kd_font_system; }

// Glyph advance as kd_font draws it: ASCII in the font, everything else 8 px.
static int advance(void *ctx, uint32_t c) { return c < 0x80 ? ((const kd_font *)ctx)->width : 8; }

static kd_rect field_inner(const kdm_item *it) { return kd_rect_make(it->x + 1, it->y + 1, it->w - 2, KDM_FIELD_H - 2); }

// ---- input method preedit (kdm_set_preedit) ----

static bool has_preedit(const kdm *m, const kdm_item *it) {
    return m->preedit_item != KDM_NONE && &m->items[m->preedit_item] == it;
}

static int preedit_px(const kdm *m, const kdm_item *it) {
    return has_preedit(m, it) ? kd_text_width_n(field_font(it), m->preedit, m->preedit_len) : 0;
}

// Draws the preedit at screen (x, y) (the glyph row), underlined from y + 8,
// its highlight inverted over rows [top, top + h); returns its width.
static int draw_preedit(const kdm *m, kd_fb *fb, const kd_font *font, int x, int y, int top, int h) {
    int pw = kd_text_width_n(font, m->preedit, m->preedit_len);
    kd_text_n(fb, font, x, y, m->preedit, m->preedit_len, KD_C_BLACK, KD_NO_KEY);
    kd_fb_hline(fb, x, y + 8, pw, KD_C_BLACK);
    if (m->preedit_hl_b > m->preedit_hl_a) {
        int xa = kd_text_width_n(font, m->preedit, m->preedit_hl_a);
        int xb = kd_text_width_n(font, m->preedit, m->preedit_hl_b);
        kd_fb_fill_rect(fb, x + xa, top, xb - xa, h, KD_C_BLACK);
        kd_text_n(fb, font, x + xa, y, m->preedit + m->preedit_hl_a, m->preedit_hl_b - m->preedit_hl_a,
                  KD_C_WHITE, KD_NO_KEY);
    }
    return pw;
}

// Keeps the caret column inside the field, and no blank space on the right
// while text is hidden on the left.
// pw: the width of a preedit shown at the caret (the caret follows it).
static void field_scroll(kdm_field *f, const kdm_item *it, int pw) {
    const kd_font *font = field_font(it);
    int view = it->w - 5;   // caret columns 0..view
    int cx = kd_edit_x(&f->ed, f->ed.caret, advance, (void *)font) + pw;
    int tw = kd_edit_x(&f->ed, f->ed.len, advance, (void *)font) + pw;
    int s = f->scroll;
    if (cx < s) s = cx;
    if (cx - s > view) s = cx - view;
    if (s > tw - view) s = tw - view;
    if (s < 0) s = 0;
    f->scroll = (int16_t)s;
}

typedef struct {
    size_t caret, anchor;
    int16_t scroll;
    uint32_t version;
} field_was;

static field_was field_before(const kdm_field *f) {
    return (field_was){f->ed.caret, f->ed.anchor, f->scroll, f->ed.version};
}

static void field_span(kdm *m, int slot, const kdm_item *it, size_t a, size_t b) {
    const kdm_field *f = &m->fields[it->aux];
    void *font = (void *)field_font(it);
    if (a > b) { size_t t = a; a = b; b = t; }
    int tx = it->x + 2 - f->scroll;
    int x0 = kd_edit_x(&f->ed, a, advance, font), x1 = kd_edit_x(&f->ed, b, advance, font);
    invalidate(m, slot, kd_rect_intersect(kd_rect_make(tx + x0, it->y + 1, x1 - x0 + 1, KDM_FIELD_H - 2), field_inner(it)));
}

static void push_item_event(kdm *m, int slot, uint8_t type, int i, uint32_t time_ms) {
    kd_event ev;
    memset(&ev, 0, sizeof ev);
    ev.type = type;
    ev.time_ms = time_ms;
    ev.reserved = (uint32_t)item_id(m, i);
    push(m, &ev, slot);
}

// ---- the multiline editor ----
//
// The view shows logical lines from f->top, LF-separated and not wrapped,
// KDM_LINE_H apart, all shifted left by f->scroll. Every derived value
// (lines, top_off) is recomputed from the text after a change: a memchr scan
// of at most KDM_DOC_BYTES, instead of incremental bookkeeping that could
// drift.

static kd_rect editor_inner(const kdm_item *it) { return kd_rect_make(it->x + 1, it->y + 1, it->w - 2, it->h - 2); }
static int editor_rows(const kdm_item *it) { return (it->h - 4) / KDM_LINE_H; }

static size_t count_lines(const kd_edit *e) {
    size_t n = 1;
    for (const uint8_t *p = e->buf, *end = e->buf + e->len; (p = memchr(p, '\n', (size_t)(end - p))) != NULL; p++) n++;
    return n;
}

// Offset of the start of logical line `line`, or of the last line.
static size_t line_offset(const kd_edit *e, size_t line) {
    size_t pos = 0;
    for (; line > 0; line--) {
        const uint8_t *lf = memchr(e->buf + pos, '\n', e->len - pos);
        if (!lf) break;
        pos = (size_t)(lf - e->buf) + 1;
    }
    return pos;
}

// Keeps the caret's line and column in view, and no empty rows below the
// last line while lines are hidden above.
static void editor_scroll(kdm_field *f, const kdm_item *it, int pw) {
    const kd_edit *e = &f->ed;
    int view = it->w - 5, cx = kd_edit_x(e, e->caret, advance, (void *)field_font(it)) + pw;
    int s = f->scroll;
    if (cx < s) s = cx - view / 2;   // back left: with half a view of context
    if (cx - s > view) s = cx - view + view / 4;   // past the right edge: a quarter view ahead,
                                                   // so typing redraws the view once per ~9 characters
    f->scroll = (int16_t)(s < 0 ? 0 : s);
    size_t rows = (size_t)editor_rows(it), line = kd_edit_line_index(e, e->caret), top = f->top;
    if (line < top) top = line;
    if (line >= top + rows) top = line - rows + 1;
    if (f->lines > rows && top > f->lines - rows) top = f->lines - rows;
    if (f->lines <= rows) top = 0;
    f->top = (uint16_t)top;
    f->top_off = (uint16_t)line_offset(e, top);
}

// Rows [r0, r1] of the view (relative to top), full width.
static void editor_rows_damage(kdm *m, int slot, const kdm_item *it, long r0, long r1) {
    kd_rect inner = editor_inner(it);
    if (r0 < 0) r0 = 0;
    if (r1 < r0) return;
    int y0 = it->y + 2 + (int)r0 * KDM_LINE_H;
    int y1 = r1 >= editor_rows(it) ? inner.y + inner.h : it->y + 2 + ((int)r1 + 1) * KDM_LINE_H;
    invalidate(m, slot, kd_rect_intersect(kd_rect_make(inner.x, y0, inner.w, y1 - y0), inner));
}

static long view_row(const kd_edit *e, const kdm_field *f, size_t pos) {
    return (long)kd_edit_line_index(e, pos < e->len ? pos : e->len) - f->top;
}

static void editor_after(kdm *m, int slot, kdm_item *it, field_was was, bool notify, uint32_t time_ms) {
    kdm_field *f = &m->fields[it->aux];
    kd_edit *e = &f->ed;
    size_t damage = kd_edit_take_damage(e);
    uint16_t lines = f->lines, top = f->top;
    if (damage != KD_EDIT_NO_DAMAGE) f->lines = (uint16_t)count_lines(e);
    editor_scroll(f, it, preedit_px(m, it));
    if (f->scroll != was.scroll || f->top != top || has_preedit(m, it)) {   // a preedit follows the caret
        invalidate(m, slot, editor_inner(it));
    } else {
        if (damage != KD_EDIT_NO_DAMAGE && !KDM_FAULTY(KDM_FAULT_FIELD_TEXT)) {
            long r = view_row(e, f, damage);
            if (f->lines != lines && !KDM_FAULTY(KDM_FAULT_EDITOR_ROWS)) {
                editor_rows_damage(m, slot, it, r, editor_rows(it));   // lines below moved
            } else {
                int dx = it->x + 2 - f->scroll + kd_edit_x(e, damage, advance, (void *)field_font(it));
                kd_rect inner = editor_inner(it);
                kd_rect row = kd_rect_make(dx, it->y + 2 + (int)r * KDM_LINE_H, inner.x + inner.w - dx, KDM_LINE_H);
                invalidate(m, slot, kd_rect_intersect(row, inner));
            }
        }
        if (was.caret != e->caret || was.anchor != e->anchor) {
            long r[4] = {view_row(e, f, was.caret), view_row(e, f, was.anchor), view_row(e, f, e->caret),
                         view_row(e, f, e->anchor)};
            long lo = r[0], hi = r[0];
            for (int k = 1; k < 4; k++) {
                if (r[k] < lo) lo = r[k];
                if (r[k] > hi) hi = r[k];
            }
            if (KDM_FAULTY(KDM_FAULT_FIELD_CARET)) lo = hi = r[2];
            if (lo == hi && was.caret == was.anchor && e->caret == e->anchor) {
                // A caret moving along one row: only the columns between the two
                // positions. (Old positions at or after a text change lie in the
                // span invalidated above, which runs to the right edge.)
                void *font = (void *)field_font(it);
                size_t old = was.caret < e->len ? was.caret : e->len;
                int x0 = kd_edit_x(e, old, advance, font), x1 = kd_edit_x(e, e->caret, advance, font);
                if (x0 > x1) { int t = x0; x0 = x1; x1 = t; }
                int tx = it->x + 2 - f->scroll;
                kd_rect span = kd_rect_make(tx + x0, it->y + 2 + (int)lo * KDM_LINE_H, x1 - x0 + 1, KDM_LINE_H);
                invalidate(m, slot, kd_rect_intersect(span, editor_inner(it)));
            } else {
                editor_rows_damage(m, slot, it, lo, hi);
            }
        }
    }
    if (notify && e->version != was.version) push_item_event(m, slot, KDM_EV_CHANGE, (int)(it - m->items), time_ms);
}

static void draw_editor(kdm *m, const kd_draw *d, int slot, int i) {
    const kdm_item *it = &m->items[i];
    const kdm_field *f = &m->fields[it->aux];
    const kd_edit *e = &f->ed;
    void *font = (void *)field_font(it);
    kd_draw_fill(d, it->x, it->y, it->w, it->h, KD_C_WHITE);
    kd_draw_rect(d, it->x, it->y, it->w, it->h, KD_C_BLACK);
    kd_rect clip = d->fb->clip, inner = editor_inner(it);
    kd_fb_set_clip(d->fb, kd_rect_intersect(clip, kd_rect_make(d->ox + inner.x, d->oy + inner.y, inner.w, inner.h)));
    bool focus = shows_focus(m, slot, i), preedit = has_preedit(m, it);
    size_t a, b;
    kd_edit_selection(e, &a, &b);
    int tx = d->ox + it->x + 2 - f->scroll, bottom = d->oy + inner.y + inner.h;
    const char *s = (const char *)e->buf;
    size_t pos = f->top_off;
    for (int ry = d->oy + it->y + 2; ry < bottom; ry += KDM_LINE_H) {
        size_t end = kd_edit_line_end(e, pos);
        // Rows outside the clip cost only the line scan.
        bool caret_row = e->caret >= pos && e->caret <= end;
        if (focus && preedit && caret_row && ry + KDM_LINE_H > d->fb->clip.y && ry < d->fb->clip.y + d->fb->clip.h) {
            size_t c = e->caret;
            int xc = kd_edit_x(e, c, advance, font);
            kd_text_n(d->fb, font, tx, ry + 1, s + pos, (int)(c - pos), KD_C_BLACK, KD_NO_KEY);
            int pw = draw_preedit(m, d->fb, font, tx + xc, ry + 1, ry, KDM_LINE_H);
            kd_text_n(d->fb, font, tx + xc + pw, ry + 1, s + c, (int)(end - c), KD_C_BLACK, KD_NO_KEY);
            kd_fb_vline(d->fb, tx + xc + pw, ry, KDM_LINE_H, KD_C_BLACK);
        } else if (ry + KDM_LINE_H > d->fb->clip.y && ry < d->fb->clip.y + d->fb->clip.h) {
            kd_text_n(d->fb, font, tx, ry + 1, s + pos, (int)(end - pos), KD_C_BLACK, KD_NO_KEY);
            if (focus && a != b && a <= end && b > pos) {
                size_t s0 = a > pos ? a : pos, s1 = b < end ? b : end;
                int x0 = kd_edit_x(e, s0, advance, font), x1 = kd_edit_x(e, s1, advance, font);
                int nl = b > end ? 4 : 0;   // the line break is selected too
                kd_fb_fill_rect(d->fb, tx + x0, ry, x1 - x0 + nl, KDM_LINE_H, KD_C_BLACK);
                kd_text_n(d->fb, font, tx + x0, ry + 1, s + s0, (int)(s1 - s0), KD_C_WHITE, KD_NO_KEY);
            }
            if (focus && a == b && e->caret >= pos && e->caret <= end)
                kd_fb_vline(d->fb, tx + kd_edit_x(e, e->caret, advance, font), ry, KDM_LINE_H, KD_C_BLACK);
        }
        if (end == e->len) break;
        pos = end + 1;
    }
    kd_fb_set_clip(d->fb, clip);
}

// Invalidates what an edit or a motion changed: the text from the first
// changed byte to the right edge, the old and the new caret or selection, or
// the whole inside when the text scrolled. notify queues KDM_EV_CHANGE.
static void field_after(kdm *m, int slot, kdm_item *it, field_was was, bool notify, uint32_t time_ms) {
    if (it->op == KDM_OP_EDITOR) {
        editor_after(m, slot, it, was, notify, time_ms);
        return;
    }
    kdm_field *f = &m->fields[it->aux];
    size_t damage = kd_edit_take_damage(&f->ed);
    field_scroll(f, it, preedit_px(m, it));
    kd_rect inner = field_inner(it);
    if (f->scroll != was.scroll || has_preedit(m, it)) {   // a preedit follows the caret
        invalidate(m, slot, inner);
    } else {
        if (damage != KD_EDIT_NO_DAMAGE && !KDM_FAULTY(KDM_FAULT_FIELD_TEXT)) {
            int dx = it->x + 2 - f->scroll + kd_edit_x(&f->ed, damage, advance, (void *)field_font(it));
            invalidate(m, slot, kd_rect_intersect(kd_rect_make(dx, inner.y, inner.x + inner.w - dx, inner.h), inner));
        }
        if (was.caret != f->ed.caret || was.anchor != f->ed.anchor) {
            if (!KDM_FAULTY(KDM_FAULT_FIELD_CARET))
                field_span(m, slot, it, was.anchor < f->ed.len ? was.anchor : f->ed.len,
                           was.caret < f->ed.len ? was.caret : f->ed.len);
            field_span(m, slot, it, f->ed.anchor, f->ed.caret);
        }
    }
    if (notify && f->ed.version != was.version) push_item_event(m, slot, KDM_EV_CHANGE, (int)(it - m->items), time_ms);
}

static void draw_field(kdm *m, const kd_draw *d, int slot, int i) {
    const kdm_item *it = &m->items[i];
    const kdm_field *f = &m->fields[it->aux];
    const kd_font *font = field_font(it);
    kd_draw_fill(d, it->x, it->y, it->w, KDM_FIELD_H, KD_C_WHITE);
    kd_draw_rect(d, it->x, it->y, it->w, KDM_FIELD_H, KD_C_BLACK);
    kd_rect clip = d->fb->clip, inner = field_inner(it);
    kd_fb_set_clip(d->fb, kd_rect_intersect(clip, kd_rect_make(d->ox + inner.x, d->oy + inner.y, inner.w, inner.h)));
    int tx = d->ox + it->x + 2 - f->scroll, ty = d->oy + it->y + 2;
    const char *s = (const char *)f->ed.buf;
    if (shows_focus(m, slot, i) && has_preedit(m, it)) {   // text, preedit at the caret, text, caret
        size_t c = f->ed.caret;
        int xc = kd_edit_x(&f->ed, c, advance, (void *)font);
        kd_text_n(d->fb, font, tx, ty, s, (int)c, KD_C_BLACK, KD_NO_KEY);
        int pw = draw_preedit(m, d->fb, font, tx + xc, ty, d->oy + inner.y, inner.h);
        kd_text_n(d->fb, font, tx + xc + pw, ty, s + c, (int)(f->ed.len - c), KD_C_BLACK, KD_NO_KEY);
        kd_fb_vline(d->fb, tx + xc + pw, d->oy + inner.y, inner.h, KD_C_BLACK);
        kd_fb_set_clip(d->fb, clip);
        return;
    }
    kd_text_n(d->fb, font, tx, ty, s, (int)f->ed.len, KD_C_BLACK, KD_NO_KEY);
    if (shows_focus(m, slot, i)) {
        size_t a, b;
        kd_edit_selection(&f->ed, &a, &b);
        int xa = kd_edit_x(&f->ed, a, advance, (void *)font);
        if (a != b) {
            int xb = kd_edit_x(&f->ed, b, advance, (void *)font);
            kd_fb_fill_rect(d->fb, tx + xa, d->oy + inner.y, xb - xa, inner.h, KD_C_BLACK);
            kd_text_n(d->fb, font, tx + xa, ty, s + a, (int)(b - a), KD_C_WHITE, KD_NO_KEY);
        } else {
            kd_fb_vline(d->fb, tx + xa, d->oy + inner.y, inner.h, KD_C_BLACK);
        }
    }
    kd_fb_set_clip(d->fb, clip);
}

static void damage_item(kdm *m, int slot, uint16_t i) {
    if (i != KDM_NONE) invalidate(m, slot, item_box(m, &m->items[i]));
}

static void set_focus(kdm *m, int slot, uint16_t i) {
    kdm_window *w = &m->win[slot];
    if (w->focus == i) return;
    damage_item(m, slot, w->focus);
    w->focus = i;
    damage_item(m, slot, i);
}

// Moves the focus to the next (dir 1) or previous (-1) focusable control,
// wrapping. Returns false when the window has none.
static bool focus_step(kdm *m, int slot, int dir) {
    kdm_window *w = &m->win[slot];
    uint16_t first = KDM_NONE, last = KDM_NONE, before = KDM_NONE, after = KDM_NONE;
    bool seen = false;
    for (uint16_t k = w->head; k != KDM_NONE; k = m->items[k].next) {
        if (k == w->focus) {
            seen = true;
            continue;
        }
        if (!focusable(&m->items[k])) continue;
        if (first == KDM_NONE) first = k;
        last = k;
        if (!seen) before = k;
        else if (after == KDM_NONE) after = k;
    }
    if (first == KDM_NONE) return w->focus != KDM_NONE;   // only the focused one
    uint16_t to;
    if (!seen) to = dir > 0 ? first : last;
    else if (dir > 0) to = after != KDM_NONE ? after : first;
    else to = before != KDM_NONE ? before : last;
    set_focus(m, slot, to);
    return true;
}

// False when nothing is selected or the selection is too long (clipboard kept).
static bool clip_copy(kdm *m, const kd_edit *e) {
    size_t n = kd_edit_copy(e, NULL, 0);
    if (n == 0 || n >= KDM_CLIP_BYTES) return false;
    kd_edit_copy(e, m->clip, KDM_CLIP_BYTES);
    m->clip_len = (uint16_t)n;
    return true;
}

// Applies cmd to a field's editor; the caller does field_after. Returns
// true when the clipboard was written.
static bool field_command(kdm *m, kdm_field *f, int cmd) {
    kd_edit *e = &f->ed;
    switch (cmd) {
    case KDM_EDIT_COPY: return clip_copy(m, e);
    case KDM_EDIT_CUT:
        if (!clip_copy(m, e)) return false;
        kd_edit_delete(e, true);
        return true;
    case KDM_EDIT_PASTE: kd_edit_insert(e, (const uint8_t *)m->clip, m->clip_len); break;   // atomic on failure
    case KDM_EDIT_SELECT_ALL: kd_edit_select_all(e); break;
    default: break;
    }
    return false;
}

static bool field_key(kdm *m, int slot, kdm_item *it, const kd_event *ev) {
    kdm_field *f = &m->fields[it->aux];
    kd_edit *e = &f->ed;
    bool shift = ev->mods & KD_MOD_SHIFT, ctrl = ev->mods & KD_MOD_CTRL, alt = ev->mods & KD_MOD_ALT;
    bool multi = it->op == KDM_OP_EDITOR;
    unsigned char ch = (unsigned char)ev->ch;
    int motion = -1, repeat = 1;
    field_was was = field_before(f);
    switch (multi ? ev->key : KD_KEY_NONE) {   // the editor's own keys
    case KD_KEY_ENTER:
        if (ctrl || alt) return false;
        kd_edit_insert(e, (const uint8_t *)"\n", 1);
        field_after(m, slot, it, was, true, ev->time_ms);
        return true;
    case KD_KEY_UP: motion = KD_EDIT_UP; break;
    case KD_KEY_DOWN: motion = KD_EDIT_DOWN; break;
    case KD_KEY_PGUP: case KD_KEY_PGDN:
        motion = ev->key == KD_KEY_PGUP ? KD_EDIT_UP : KD_EDIT_DOWN;
        repeat = editor_rows(it) > 1 ? editor_rows(it) - 1 : 1;
        break;
    case KD_KEY_HOME: case KD_KEY_END:
        if (ctrl && !alt) motion = ev->key == KD_KEY_HOME ? KD_EDIT_START : KD_EDIT_FINISH;
        break;
    default: break;
    }
    if (motion >= 0) {
        if (alt || (ctrl && motion != KD_EDIT_START && motion != KD_EDIT_FINISH)) return false;
        void *font = (void *)field_font(it);
        while (repeat--) kd_edit_move(e, motion, shift, advance, font);
        field_after(m, slot, it, was, true, ev->time_ms);
        return true;
    }
    switch (ev->key) {
    case KD_KEY_CHAR:
        if (alt) return false;
        if (ctrl) {
            if (ch != 'a' && ch != 'A') return false;
            field_command(m, f, KDM_EDIT_SELECT_ALL);
        } else {
            if (ch < 0x20 || ch > 0x7E) return false;
            kd_edit_insert(e, &ch, 1);   // a full field changes nothing
        }
        break;
    case KD_KEY_BACKSPACE:
        if (ctrl || alt) return false;
        kd_edit_delete(e, true);
        break;
    case KD_KEY_DELETE:
        if (ctrl || alt) return false;
        if (shift) field_command(m, f, KDM_EDIT_CUT);
        else kd_edit_delete(e, false);
        break;
    case KD_KEY_INSERT:
        if (alt || ctrl == shift) return false;
        field_command(m, f, ctrl ? KDM_EDIT_COPY : KDM_EDIT_PASTE);
        break;
    case KD_KEY_LEFT: motion = KD_EDIT_LEFT; break;
    case KD_KEY_RIGHT: motion = KD_EDIT_RIGHT; break;
    case KD_KEY_HOME: motion = KD_EDIT_HOME; break;
    case KD_KEY_END: motion = KD_EDIT_END; break;
    default: return false;
    }
    if (motion >= 0) {
        if (ctrl || alt) return false;
        kd_edit_move(e, motion, shift, advance, (void *)field_font(it));
    }
    field_after(m, slot, it, was, true, ev->time_ms);
    return true;
}

static int default_button(const kdm *m, int slot) {
    for (uint16_t k = m->win[slot].head; k != KDM_NONE; k = m->items[k].next) {
        const kdm_item *it = &m->items[k];
        if (it->op == KDM_OP_BUTTON && it->c1 && (it->c0 & KD_BTN_DEFAULT) && !(it->c0 & KD_BTN_DISABLED)) return k;
    }
    return -1;
}

// Keys for the window's controls (see kdm.h). True when consumed.
static bool control_key(kdm *m, int slot, const kd_event *ev) {
    kdm_window *w = &m->win[slot];
    bool ctrl = ev->mods & KD_MOD_CTRL, alt = ev->mods & KD_MOD_ALT;
    if (ev->key == KD_KEY_TAB && !ctrl && !alt) return focus_step(m, slot, ev->mods & KD_MOD_SHIFT ? -1 : 1);
    if (w->focus != KDM_NONE) {
        kdm_item *it = &m->items[w->focus];
        if (editable(it) && field_key(m, slot, it, ev)) return true;
        if (it->op == KDM_OP_BUTTON && !ctrl && !alt &&
            (ev->key == KD_KEY_ENTER || (ev->key == KD_KEY_CHAR && ev->ch == ' '))) {
            if (!(it->c0 & KD_BTN_DISABLED)) push_item_event(m, slot, KDM_EV_ACTIVATE, w->focus, ev->time_ms);
            return true;
        }
    }
    if (ev->key == KD_KEY_ENTER && !ev->mods) {
        int k = default_button(m, slot);
        if (k >= 0) {
            push_item_event(m, slot, KDM_EV_ACTIVATE, k, ev->time_ms);
            return true;
        }
    }
    return false;
}

// A click on a focusable control focuses it; on a field it also places the
// caret (Shift extends). The pointer event is still queued.
static void pointer_focus(kdm *m, int slot, const kd_event *ev) {
    int hit = -1;
    for (uint16_t k = m->win[slot].head; k != KDM_NONE; k = m->items[k].next)
        if (focusable(&m->items[k]) && kd_rect_has_point(item_box(m, &m->items[k]), ev->x, ev->y)) hit = k;
    if (hit < 0) return;
    set_focus(m, slot, (uint16_t)hit);
    kdm_item *it = &m->items[hit];
    if (!editable(it)) return;
    kdm_field *f = &m->fields[it->aux];
    field_was was = field_before(f);
    void *font = (void *)field_font(it);
    size_t line = 0;
    if (it->op == KDM_OP_EDITOR) {
        int row = (ev->y - (it->y + 2)) / KDM_LINE_H;
        line = line_offset(&f->ed, (size_t)f->top + (size_t)(row > 0 ? row : 0));
    }
    size_t to = kd_edit_at_x(&f->ed, line, ev->x - (it->x + 2 - f->scroll), advance, font);
    kd_edit_select(&f->ed, (ev->mods & KD_MOD_SHIFT) ? f->ed.anchor : to, to);
    field_after(m, slot, it, was, false, ev->time_ms);
}

// ---- window class ----

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
        case KDM_OP_BUTTON:
            kd_draw_button(d, item_box(m, it), m->text + it->aux, it->c0 | (shows_focus(m, slot, i) ? KD_BTN_FOCUS : 0));
            break;
        case KDM_OP_FIELD: draw_field(m, d, slot, i); break;
        case KDM_OP_EDITOR: draw_editor(m, d, slot, i); break;
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
    int slot = slot_of(m, w);
    if (ev->type == KD_EV_FOCUS || ev->type == KD_EV_BLUR) damage_item(m, slot, m->win[slot].focus);
    else if (ev->type == KD_EV_KEY && control_key(m, slot, ev)) return true;
    else if (ev->type == KD_EV_POINTER_DOWN && ev->button == KD_BUTTON_LEFT) pointer_focus(m, slot, ev);
    push(m, ev, slot);
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
    for (int s = 0; s < KD_MAX_WINDOWS; s++) m->win[s].head = m->win[s].tail = m->win[s].focus = KDM_NONE;
    for (int f = 0; f <= KDM_FIELDS; f++) m->fields[f].item = KDM_NONE;
    m->preedit_item = KDM_NONE;
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
    w->head = w->tail = w->focus = KDM_NONE;
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
    it->w = (int16_t)kd_text_width_n(font ? &kd_font_small : &kd_font_system, s, (int)len);
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
    if (editable(it)) {
        kdm_field *f = &m->fields[it->aux];
        field_was was = field_before(f);
        int rc = kd_edit_set(&f->ed, (const uint8_t *)s, len);
        if (rc == KD_EDIT_EFULL) return KDM_ETOOLONG;
        if (rc < 0) return KDM_EINVAL;
        if (it->op == KDM_OP_EDITOR) kd_edit_select(&f->ed, 0, 0);   // a new document: from its start
        field_after(m, slot, it, was, false, 0);
        return KDM_OK;
    }
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
    bool text = it->op == KDM_OP_TEXT || it->op == KDM_OP_TEXT_SMALL;
    const kd_font *font = it->op == KDM_OP_TEXT_SMALL ? &kd_font_small : &kd_font_system;
    if (text && ascii(a, la) && ascii(b, len)) {
        // Fixed-width cells: invalidate runs of cells that differ, as kd_label_set.
        int cw = font->width;
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
    if (text) it->w = (int16_t)kd_text_width_n(font, b, (int)len);
    invalidate(m, slot, before);
    invalidate(m, slot, item_box(m, it));
    return KDM_OK;
}

int kdm_item_set_color(kdm *m, int slot, int id, uint8_t color) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (color > 15 || it->op == KDM_OP_SPRITE || it->op == KDM_OP_BUTTON || it->op == KDM_OP_ICON ||
        editable(it))
        return KDM_EINVAL;
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
    if (m->win[slot].focus == i) {
        focus_step(m, slot, 1);
        if (m->win[slot].focus == i) m->win[slot].focus = KDM_NONE;
    }
    unlink_item(m, slot, i);
    item_release(m, i);
    return KDM_OK;
}

// ---- fields and focus (API) ----

int kdm_add_field(kdm *m, int slot, int x, int y, int w, const char *s, size_t len, int font) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (!fits_rect(x, y, w, KDM_FIELD_H) || w < 8 || (font != 0 && font != 1)) return KDM_EINVAL;
    long need = kd_edit_measure((const uint8_t *)s, len, KD_EDIT_SINGLE_LINE);
    if (need < 0) return KDM_EINVAL;
    if (need >= KDM_FIELD_BYTES) return KDM_ETOOLONG;
    int fi = 0;
    while (fi < KDM_FIELDS && m->fields[fi].item != KDM_NONE) fi++;
    if (fi == KDM_FIELDS) return KDM_ENOFIELD;
    int i = item_new(m, slot, KDM_OP_FIELD);
    if (i < 0) return i;
    kdm_item *it = &m->items[i];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->w = (int16_t)w;
    it->h = KDM_FIELD_H;
    it->c0 = (uint8_t)font;
    it->aux = (uint16_t)fi;
    kdm_field *f = &m->fields[fi];
    f->item = (uint16_t)i;
    f->scroll = 0;
    kd_edit_init(&f->ed, f->text, KDM_FIELD_BYTES, KD_EDIT_SINGLE_LINE);
    kd_edit_set(&f->ed, (const uint8_t *)s, len);   // measured above: cannot fail
    kd_edit_take_damage(&f->ed);
    field_scroll(f, it, 0);
    if (m->win[slot].focus == KDM_NONE) m->win[slot].focus = (uint16_t)i;
    invalidate(m, slot, item_box(m, it));
    return item_id(m, i);
}

int kdm_add_editor(kdm *m, int slot, int x, int y, int w, int h, const char *s, size_t len, int font) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (!fits_rect(x, y, w, h) || w < 16 || h < KDM_LINE_H + 6 || (font != 0 && font != 1)) return KDM_EINVAL;
    long need = kd_edit_measure((const uint8_t *)s, len, 0);
    if (need < 0) return KDM_EINVAL;
    if (need >= KDM_DOC_BYTES) return KDM_ETOOLONG;
    kdm_field *f = &m->fields[KDM_FIELDS];
    if (f->item != KDM_NONE) return KDM_ENOFIELD;
    int i = item_new(m, slot, KDM_OP_EDITOR);
    if (i < 0) return i;
    kdm_item *it = &m->items[i];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->w = (int16_t)w;
    it->h = (int16_t)h;
    it->c0 = (uint8_t)font;
    it->aux = KDM_FIELDS;
    f->item = (uint16_t)i;
    f->scroll = 0;
    f->top = f->top_off = 0;
    kd_edit_init(&f->ed, m->doc, KDM_DOC_BYTES, 0);
    kd_edit_set(&f->ed, (const uint8_t *)s, len);   // measured above: cannot fail
    kd_edit_select(&f->ed, 0, 0);
    kd_edit_take_damage(&f->ed);
    f->lines = (uint16_t)count_lines(&f->ed);
    editor_scroll(f, it, 0);
    if (m->win[slot].focus == KDM_NONE) m->win[slot].focus = (uint16_t)i;
    invalidate(m, slot, item_box(m, it));
    return item_id(m, i);
}

int kdm_item_get_text(kdm *m, int slot, int id, const char **s, size_t *len) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (editable(it)) {
        *s = (const char *)m->fields[it->aux].ed.buf;
        *len = m->fields[it->aux].ed.len;
        return KDM_OK;
    }
    if (!has_text(it)) return KDM_EINVAL;
    *s = m->text + it->aux;
    *len = strlen(*s);
    return KDM_OK;
}

static kdm_item *field_get(kdm *m, int slot, int id) {
    kdm_item *it = window_ok(m, slot) ? item_get(m, slot, id) : NULL;
    return it && editable(it) ? it : NULL;
}

const kd_edit *kdm_field_editor(kdm *m, int slot, int id) {
    kdm_item *it = field_get(m, slot, id);
    return it ? &m->fields[it->aux].ed : NULL;
}

int kdm_field_select(kdm *m, int slot, int id, size_t anchor, size_t caret) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (!editable(it)) return KDM_EINVAL;
    kdm_field *f = &m->fields[it->aux];
    field_was was = field_before(f);
    if (kd_edit_select(&f->ed, anchor, caret) < 0) return KDM_EINVAL;
    field_after(m, slot, it, was, false, 0);
    return KDM_OK;
}

int kdm_item_set_focusable(kdm *m, int slot, int id, bool on) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (it->op != KDM_OP_BUTTON) return KDM_EINVAL;
    int i = (int)(it - m->items);
    if (it->c1 == on) return KDM_OK;
    it->c1 = on;
    if (on && m->win[slot].focus == KDM_NONE) set_focus(m, slot, (uint16_t)i);
    if (!on && m->win[slot].focus == i) set_focus(m, slot, KDM_NONE);
    return KDM_OK;
}

int kdm_focus(kdm *m, int slot, int id) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    if (id < 0) {
        set_focus(m, slot, KDM_NONE);
        return KDM_OK;
    }
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (!focusable(it)) return KDM_EINVAL;
    set_focus(m, slot, (uint16_t)(it - m->items));
    return KDM_OK;
}

int kdm_focused(const kdm *m, int slot) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    uint16_t i = m->win[slot].focus;
    return i == KDM_NONE ? KDM_ENONE : item_id(m, i);
}

int kdm_edit(kdm *m, int slot, int id, int cmd) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (!editable(it) || cmd < KDM_EDIT_COPY || cmd > KDM_EDIT_SELECT_ALL) return KDM_EINVAL;
    kdm_field *f = &m->fields[it->aux];
    field_was was = field_before(f);
    bool clip = field_command(m, f, cmd);
    field_after(m, slot, it, was, false, 0);
    return clip || f->ed.version != was.version || f->ed.caret != was.caret || f->ed.anchor != was.anchor;
}

int kdm_text_input(kdm *m, const char *s, size_t len) {
    kd_window *top = kd_desktop_top(&m->desk);
    if (!top || m->desk.menu_open >= 0) return 0;
    int slot = slot_of(m, top);
    uint16_t i = m->win[slot].focus;
    if (i == KDM_NONE || !editable(&m->items[i])) return 0;
    kdm_item *it = &m->items[i];
    kdm_field *f = &m->fields[it->aux];
    field_was was = field_before(f);
    int rc = kd_edit_insert(&f->ed, (const uint8_t *)s, len);
    if (rc == KD_EDIT_EFULL) return KDM_ETOOLONG;
    if (rc < 0) return KDM_EINVAL;
    field_after(m, slot, it, was, true, 0);
    return 1;
}

int kdm_set_clipboard(kdm *m, const char *s, size_t len) {
    long need = kd_edit_measure((const uint8_t *)s, len, 0);
    if (need < 0) return KDM_EINVAL;
    if (need >= KDM_CLIP_BYTES) return KDM_ETOOLONG;
    // Stored as the editor stores text: CRLF and CR become LF.
    kd_edit e;
    kd_edit_init(&e, (uint8_t *)m->clip, KDM_CLIP_BYTES, 0);
    kd_edit_set(&e, (const uint8_t *)s, len);
    m->clip_len = (uint16_t)e.len;
    return KDM_OK;
}

// ---- input methods ----

// The part of an editable record a preedit can cover: from the caret to the
// right edge of its row (the text after the caret moves with the preedit).
static void preedit_damage(kdm *m, int slot, const kdm_item *it) {
    if (KDM_FAULTY(KDM_FAULT_PREEDIT)) return;
    const kdm_field *f = &m->fields[it->aux];
    int xc = it->x + 2 - f->scroll + kd_edit_x(&f->ed, f->ed.caret, advance, (void *)field_font(it));
    if (it->op == KDM_OP_EDITOR) {
        kd_rect inner = editor_inner(it);
        int y = it->y + 2 + (int)view_row(&f->ed, f, f->ed.caret) * KDM_LINE_H;
        invalidate(m, slot, kd_rect_intersect(kd_rect_make(xc, y, inner.x + inner.w - xc, KDM_LINE_H), inner));
    } else {
        kd_rect inner = field_inner(it);
        invalidate(m, slot, kd_rect_intersect(kd_rect_make(xc, inner.y, inner.x + inner.w - xc, inner.h), inner));
    }
}

// Scroll for the record's current preedit; the whole inside if it moved.
static void preedit_rescroll(kdm *m, int slot, const kdm_item *it) {
    kdm_field *f = &m->fields[it->aux];
    int16_t scroll = f->scroll;
    uint16_t top = f->top;
    if (it->op == KDM_OP_EDITOR) editor_scroll(f, it, preedit_px(m, it));
    else field_scroll(f, it, preedit_px(m, it));
    if (f->scroll != scroll || f->top != top)
        invalidate(m, slot, it->op == KDM_OP_EDITOR ? editor_inner(it) : field_inner(it));
    else
        preedit_damage(m, slot, it);
}

int kdm_set_preedit(kdm *m, int slot, int id, const char *s, size_t len, int hl_a, int hl_b) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (!editable(it)) return KDM_EINVAL;
    if (len >= KDM_PREEDIT_BYTES) return KDM_ETOOLONG;
    if (kd_edit_measure((const uint8_t *)s, len, KD_EDIT_SINGLE_LINE) != (long)len) return KDM_EINVAL;
    if (hl_a < 0 || hl_a == hl_b) {
        hl_a = hl_b = 0;
    } else if (hl_a > hl_b || (size_t)hl_b > len || ((unsigned char)s[hl_a] & 0xC0) == 0x80 ||
               ((size_t)hl_b < len && ((unsigned char)s[hl_b] & 0xC0) == 0x80)) {
        return KDM_EINVAL;                                   // not on character boundaries
    }
    int i = (int)(it - m->items);
    if (m->preedit_item != KDM_NONE && m->preedit_item != i) {   // it moves from another record
        kdm_item *old = &m->items[m->preedit_item];
        int old_slot = old->win;
        preedit_damage(m, old_slot, old);
        m->preedit_item = KDM_NONE;
        m->preedit_len = 0;
        preedit_rescroll(m, old_slot, old);
    }
    if (has_preedit(m, it)) preedit_damage(m, slot, it);     // where the old one was
    memcpy(m->preedit, s, len);
    m->preedit[len] = 0;
    m->preedit_len = (uint8_t)len;
    m->preedit_hl_a = (uint8_t)hl_a;
    m->preedit_hl_b = (uint8_t)hl_b;
    m->preedit_item = len ? (uint16_t)i : KDM_NONE;
    preedit_rescroll(m, slot, it);
    return KDM_OK;
}

int kdm_input_target(const kdm *m, int *slot) {
    kd_window *top = kd_desktop_top((kd_desktop *)&m->desk);
    if (!top || m->desk.menu_open >= 0) return KDM_ENONE;
    int s = slot_of(m, top);
    uint16_t i = m->win[s].focus;
    if (i == KDM_NONE || !editable(&m->items[i])) return KDM_ENONE;
    *slot = s;
    return item_id(m, i);
}

int kdm_caret_xy(kdm *m, int slot, int id, int *x, int *y, int *h) {
    if (!window_ok(m, slot)) return KDM_ESTALE;
    kdm_item *it = item_get(m, slot, id);
    if (!it) return KDM_ESTALE;
    if (!editable(it)) return KDM_EINVAL;
    const kdm_field *f = &m->fields[it->aux];
    kd_rect work = kd_window_work(&m->desk.win[slot]);
    *x = work.x + it->x + 2 - f->scroll + kd_edit_x(&f->ed, f->ed.caret, advance, (void *)field_font(it)) +
         preedit_px(m, it);
    if (it->op == KDM_OP_EDITOR) {
        *y = work.y + it->y + 2 + (int)view_row(&f->ed, f, f->ed.caret) * KDM_LINE_H;
        *h = KDM_LINE_H;
    } else {
        *y = work.y + it->y + 1;
        *h = KDM_FIELD_H - 2;
    }
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
    return kdm_present_gap(m, 0, sink, ctx, st);
}

int kdm_present_gap(kdm *m, unsigned max_gap, kd_tile4_sink sink, void *ctx, kd_tile4_stats *st) {
    kd_tile4_stats local;
    if (!st) st = &local;
    kd_desktop_render(&m->desk);
    bool ok = kd_tile4_flush(&m->desk.fb, max_gap, m->staging, KD_TILE_COLS, sink ? sink : discard, ctx, st);
    m->stats.presents++;
    m->stats.tiles += st->tiles;
    m->stats.runs += st->runs;
    return ok ? (int)st->tiles : KDM_ESINK;
}
