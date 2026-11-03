// SPDX-License-Identifier: Apache-2.0
#include "kd_edit.h"

#include <limits.h>
#include <string.h>

#include "kj_text.h"

// Deliberate faults for the mutation tests (CMakeLists.txt); 0 in every
// normal build, where each KD_EDIT_FAULTY() is a constant false.
#ifndef KD_EDIT_FAULT
#define KD_EDIT_FAULT 0
#endif
#define KD_EDIT_FAULTY(n) (KD_EDIT_FAULT == (n))
enum {
    KD_EDIT_FAULT_CAPACITY = 1,    // the capacity check forgets the NUL
    KD_EDIT_FAULT_PREV_BYTE = 2,   // stepping back moves one byte, not one scalar
    KD_EDIT_FAULT_SET_EARLY = 3,   // set empties the text before validating
    KD_EDIT_FAULT_KEEP_CR = 4,     // CR is stored as it is
};

static bool continuation(uint8_t b) { return (b & 0xC0u) == 0x80u; }

static void note_damage(kd_edit *e, size_t pos) {
    if (pos < e->damage) e->damage = pos;
    e->version++;
}

int kd_edit_init(kd_edit *e, uint8_t *storage, size_t cap, unsigned flags) {
    if (!e || !storage || cap < 1 || cap > LONG_MAX || (flags & ~(unsigned)KD_EDIT_SINGLE_LINE))
        return KD_EDIT_EINVAL;
    memset(e, 0, sizeof *e);
    e->buf = storage;
    e->cap = cap;
    e->flags = (uint8_t)flags;
    e->buf[0] = 0;
    e->goal_x = -1;
    return KD_EDIT_OK;
}

void kd_edit_reset(kd_edit *e) {
    e->len = e->caret = e->anchor = 0;
    e->buf[0] = 0;
    e->goal_x = -1;
    note_damage(e, 0);
}

long kd_edit_measure(const uint8_t *s, size_t n, unsigned flags) {
    if ((!s && n) || n > LONG_MAX) return KD_EDIT_EINVAL;
    size_t out = 0;
    for (size_t i = 0; i < n;) {
        kj_decoded d = kj_utf8_next(s + i, n - i);
        if (!d.valid || d.scalar == 0) return KD_EDIT_EUTF8;
        if (d.scalar == '\n' || d.scalar == '\r') {
            if (flags & KD_EDIT_SINGLE_LINE) return KD_EDIT_ELINE;
            // CRLF and a lone CR become one LF.
            if (d.scalar == '\r' && i + 1 < n && s[i + 1] == '\n' && !KD_EDIT_FAULTY(KD_EDIT_FAULT_KEEP_CR)) i++;
        }
        i += d.consumed;
        out += d.consumed;
    }
    if (KD_EDIT_FAULTY(KD_EDIT_FAULT_KEEP_CR)) return (long)n;
    return (long)out;
}

// Replaces [a, b) by s (stored bytes already measured). All checks are done.
static void splice(kd_edit *e, size_t a, size_t b, const uint8_t *s, size_t n, size_t stored) {
    memmove(e->buf + a + stored, e->buf + b, e->len - b + 1);   // with the NUL
    uint8_t *p = e->buf + a;
    for (size_t i = 0; i < n; i++) {
        if (s[i] == '\r' && !KD_EDIT_FAULTY(KD_EDIT_FAULT_KEEP_CR)) {
            *p++ = '\n';
            if (i + 1 < n && s[i + 1] == '\n') i++;
        } else {
            *p++ = s[i];
        }
    }
    e->len = e->len - (b - a) + stored;
    e->caret = e->anchor = a + stored;
    e->goal_x = -1;
    note_damage(e, a);
}

static int replace(kd_edit *e, size_t a, size_t b, const uint8_t *s, size_t n) {
    long stored = kd_edit_measure(s, n, e->flags);
    if (stored < 0) return (int)stored;
    size_t limit = KD_EDIT_FAULTY(KD_EDIT_FAULT_CAPACITY) ? e->cap : e->cap - 1;
    if ((size_t)stored > limit - (e->len - (b - a))) return KD_EDIT_EFULL;
    splice(e, a, b, s, n, (size_t)stored);
    return KD_EDIT_OK;
}

int kd_edit_set(kd_edit *e, const uint8_t *s, size_t n) {
    if (KD_EDIT_FAULTY(KD_EDIT_FAULT_SET_EARLY)) {
        e->len = e->caret = e->anchor = 0;
        e->buf[0] = 0;
    }
    return replace(e, 0, e->len, s, n);
}

int kd_edit_insert(kd_edit *e, const uint8_t *s, size_t n) {
    size_t a, b;
    kd_edit_selection(e, &a, &b);
    return replace(e, a, b, s, n);
}

int kd_edit_delete(kd_edit *e, bool backward) {
    size_t a, b;
    kd_edit_selection(e, &a, &b);
    if (a == b) {
        if (backward) a = kd_edit_prev(e, a);
        else b = kd_edit_next(e, b);
        if (a == b) return 0;
    }
    splice(e, a, b, NULL, 0, 0);
    return 1;
}

void kd_edit_selection(const kd_edit *e, size_t *start, size_t *end) {
    bool forward = e->anchor <= e->caret;
    *start = forward ? e->anchor : e->caret;
    *end = forward ? e->caret : e->anchor;
}

bool kd_edit_is_boundary(const kd_edit *e, size_t pos) {
    return pos <= e->len && (pos == e->len || !continuation(e->buf[pos]));
}

size_t kd_edit_prev(const kd_edit *e, size_t pos) {
    if (pos > e->len) pos = e->len;
    if (pos == 0) return 0;
    pos--;
    if (!KD_EDIT_FAULTY(KD_EDIT_FAULT_PREV_BYTE))
        while (pos > 0 && continuation(e->buf[pos])) pos--;
    return pos;
}

size_t kd_edit_next(const kd_edit *e, size_t pos) {
    if (pos >= e->len) return e->len;
    pos++;
    while (pos < e->len && continuation(e->buf[pos])) pos++;
    return pos;
}

size_t kd_edit_line_start(const kd_edit *e, size_t pos) {
    if (pos > e->len) pos = e->len;
    while (pos > 0 && e->buf[pos - 1] != '\n') pos--;
    return pos;
}

size_t kd_edit_line_end(const kd_edit *e, size_t pos) {
    if (pos > e->len) pos = e->len;
    const uint8_t *lf = memchr(e->buf + pos, '\n', e->len - pos);
    return lf ? (size_t)(lf - e->buf) : e->len;
}

size_t kd_edit_count(const kd_edit *e, size_t from, size_t to) {
    if (to > e->len) to = e->len;
    size_t n = 0;
    for (size_t i = from; i < to; i++) n += !continuation(e->buf[i]);
    return n;
}

size_t kd_edit_line_index(const kd_edit *e, size_t pos) {
    if (pos > e->len) pos = e->len;
    size_t n = 0;
    for (const uint8_t *p = e->buf, *end = e->buf + pos; (p = memchr(p, '\n', (size_t)(end - p))) != NULL; p++) n++;
    return n;
}

static int advance_of(const kd_edit *e, size_t pos, kd_edit_advance adv, void *ctx) {
    if (!adv) return 1;
    kj_decoded d = kj_utf8_next(e->buf + pos, e->len - pos);
    return adv(ctx, d.scalar);
}

int32_t kd_edit_x(const kd_edit *e, size_t pos, kd_edit_advance adv, void *ctx) {
    if (pos > e->len) pos = e->len;
    int32_t x = 0;
    for (size_t i = kd_edit_line_start(e, pos); i < pos; i = kd_edit_next(e, i))
        x += advance_of(e, i, adv, ctx);
    return x;
}

size_t kd_edit_at_x(const kd_edit *e, size_t line, int32_t x, kd_edit_advance adv, void *ctx) {
    size_t i = kd_edit_line_start(e, line), end = kd_edit_line_end(e, line);
    int32_t at = 0;
    while (i < end) {
        int32_t w = advance_of(e, i, adv, ctx);
        if (at + w > x) break;
        at += w;
        i = kd_edit_next(e, i);
    }
    return i;
}

static int place(kd_edit *e, size_t caret, bool extend) {
    size_t anchor = extend ? e->anchor : caret;
    bool changed = caret != e->caret || anchor != e->anchor;
    e->caret = caret;
    e->anchor = anchor;
    return changed;
}

int kd_edit_move(kd_edit *e, int motion, bool extend, kd_edit_advance adv, void *ctx) {
    size_t a, b, to;
    kd_edit_selection(e, &a, &b);
    bool collapse = !extend && a != b;
    if (motion != KD_EDIT_UP && motion != KD_EDIT_DOWN) e->goal_x = -1;
    switch (motion) {
    case KD_EDIT_LEFT: to = collapse ? a : kd_edit_prev(e, e->caret); break;
    case KD_EDIT_RIGHT: to = collapse ? b : kd_edit_next(e, e->caret); break;
    case KD_EDIT_HOME: to = kd_edit_line_start(e, e->caret); break;
    case KD_EDIT_END: to = kd_edit_line_end(e, e->caret); break;
    case KD_EDIT_START: to = 0; break;
    case KD_EDIT_FINISH: to = e->len; break;
    case KD_EDIT_UP: case KD_EDIT_DOWN: {
        if (e->goal_x < 0) e->goal_x = kd_edit_x(e, e->caret, adv, ctx);
        size_t start = kd_edit_line_start(e, e->caret);
        if (motion == KD_EDIT_UP) {
            // The first line goes to its start, as in most editors.
            to = start == 0 ? 0 : kd_edit_at_x(e, kd_edit_line_start(e, start - 1), e->goal_x, adv, ctx);
        } else {
            size_t end = kd_edit_line_end(e, e->caret);
            to = end == e->len ? e->len : kd_edit_at_x(e, end + 1, e->goal_x, adv, ctx);
        }
        break;
    }
    default: return KD_EDIT_EINVAL;
    }
    return place(e, to, extend);
}

int kd_edit_select(kd_edit *e, size_t anchor, size_t caret) {
    if (!kd_edit_is_boundary(e, anchor) || !kd_edit_is_boundary(e, caret)) return KD_EDIT_EINVAL;
    e->goal_x = -1;
    bool changed = anchor != e->anchor || caret != e->caret;
    e->anchor = anchor;
    e->caret = caret;
    return changed;
}

void kd_edit_select_all(kd_edit *e) {
    e->goal_x = -1;
    e->anchor = 0;
    e->caret = e->len;
}

size_t kd_edit_copy(const kd_edit *e, char *out, size_t outcap) {
    size_t a, b;
    kd_edit_selection(e, &a, &b);
    size_t n = b - a;
    if (out && outcap > n) {
        memcpy(out, e->buf + a, n);
        out[n] = 0;
    }
    return n;
}

size_t kd_edit_take_damage(kd_edit *e) {
    size_t d = e->damage;
    e->damage = KD_EDIT_NO_DAMAGE;
    return d;
}

bool kd_edit_valid(const kd_edit *e) {
    if (!e || !e->buf || e->cap < 1 || e->len >= e->cap || e->buf[e->len] != 0) return false;
    if (!kd_edit_is_boundary(e, e->caret) || !kd_edit_is_boundary(e, e->anchor)) return false;
    return kd_edit_measure(e->buf, e->len, e->flags) == (long)e->len &&
           !memchr(e->buf, '\r', e->len);
}
