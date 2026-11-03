// SPDX-License-Identifier: Apache-2.0
// Bounded UTF-8 text editing: the state behind text fields and the editor.
//
// The text lives in caller-owned storage of a fixed capacity, as one flat run
// of bytes with a NUL after it (so it can be drawn or exported as a C string).
// It is always strictly valid UTF-8 without NUL, CR or, in single-line mode,
// LF: input is validated as a whole before anything changes, and CRLF or a
// lone CR is stored as LF. A failed call returns an error and changes nothing.
//
// Positions are byte offsets that always lie on a scalar boundary. Codepoint
// offsets (kd_edit_count) and visual columns (pixels, from the caller's
// advance function) are derived from them; nothing here knows about fonts,
// so a character may be any width. Lines are LF-separated logical lines
// (no wrapping).
//
// No allocation, no globals, no MicroPython: the caller owns the storage and
// keeps it alive (a static buffer in the firmware, never a GC object).
#ifndef KD_EDIT_H
#define KD_EDIT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum {
    KD_EDIT_OK = 0,
    KD_EDIT_EINVAL = -1,   // bad argument, or a position that is not a boundary
    KD_EDIT_EUTF8 = -2,    // input is not strictly valid UTF-8 (or contains NUL)
    KD_EDIT_ELINE = -3,    // line break in a single-line buffer
    KD_EDIT_EFULL = -4,    // result would exceed the capacity
};

enum { KD_EDIT_SINGLE_LINE = 1 };

enum {
    KD_EDIT_LEFT, KD_EDIT_RIGHT,        // one scalar value
    KD_EDIT_HOME, KD_EDIT_END,          // start / end of the logical line
    KD_EDIT_UP, KD_EDIT_DOWN,           // previous / next line, same visual x
    KD_EDIT_START, KD_EDIT_FINISH,      // start / end of the text
};

#define KD_EDIT_NO_DAMAGE SIZE_MAX

// Pixel advance of a scalar value; used for UP/DOWN. NULL counts 1 per scalar.
typedef int (*kd_edit_advance)(void *ctx, uint32_t scalar);

typedef struct {
    uint8_t *buf;
    size_t cap;            // storage bytes; the text holds at most cap - 1
    size_t len;            // text bytes, buf[len] == 0
    size_t caret;          // byte offset
    size_t anchor;         // selection is [min(anchor, caret), max(...))
    size_t damage;         // lowest offset changed since kd_edit_take_damage
    int32_t goal_x;        // UP/DOWN keep this visual x; -1: take the caret's
    uint32_t version;      // incremented by every change of the text
    uint8_t flags;         // KD_EDIT_SINGLE_LINE
} kd_edit;

// storage[0..cap-1] must stay valid while e is used; cap >= 1.
int kd_edit_init(kd_edit *e, uint8_t *storage, size_t cap, unsigned flags);
void kd_edit_reset(kd_edit *e);   // empty text, caret 0 (version advances)

// Bytes the text of s would occupy (after CRLF/CR -> LF), or an error. This
// is the check every mutation does before it changes anything.
long kd_edit_measure(const uint8_t *s, size_t n, unsigned flags);

// Replaces the whole text; caret at the end, no selection.
int kd_edit_set(kd_edit *e, const uint8_t *s, size_t n);
static inline const char *kd_edit_text(const kd_edit *e) { return (const char *)e->buf; }

// Replaces the selection (or inserts at the caret) by s; caret after it.
int kd_edit_insert(kd_edit *e, const uint8_t *s, size_t n);
// Deletes the selection, else one scalar before (backward) or after the caret.
// Returns 1 when the text changed, 0 when there was nothing to delete.
int kd_edit_delete(kd_edit *e, bool backward);

// Motions. extend keeps the anchor (Shift); otherwise the selection collapses
// (LEFT/RIGHT with a selection go to its start/end). Returns 1 when the caret
// or the selection changed.
int kd_edit_move(kd_edit *e, int motion, bool extend, kd_edit_advance adv, void *ctx);
int kd_edit_select(kd_edit *e, size_t anchor, size_t caret);
void kd_edit_select_all(kd_edit *e);
static inline bool kd_edit_has_selection(const kd_edit *e) { return e->anchor != e->caret; }
void kd_edit_selection(const kd_edit *e, size_t *start, size_t *end);

// Copies the selection into out (NUL-terminated if it fits) and returns its
// length in bytes; with outcap <= length nothing is copied, so the return
// value is the size to provide minus one.
size_t kd_edit_copy(const kd_edit *e, char *out, size_t outcap);

// Offsets and lines.
bool kd_edit_is_boundary(const kd_edit *e, size_t pos);
size_t kd_edit_prev(const kd_edit *e, size_t pos);         // previous boundary
size_t kd_edit_next(const kd_edit *e, size_t pos);         // next boundary
size_t kd_edit_line_start(const kd_edit *e, size_t pos);
size_t kd_edit_line_end(const kd_edit *e, size_t pos);     // offset of the LF or len
size_t kd_edit_count(const kd_edit *e, size_t from, size_t to);   // scalars in [from, to)
size_t kd_edit_line_index(const kd_edit *e, size_t pos);   // 0-based logical line
// Visual x of pos within its line, and the boundary in [line, line_end] whose
// x is nearest to x without exceeding it (the caret position for UP/DOWN).
int32_t kd_edit_x(const kd_edit *e, size_t pos, kd_edit_advance adv, void *ctx);
size_t kd_edit_at_x(const kd_edit *e, size_t line, int32_t x, kd_edit_advance adv, void *ctx);

// Returns the lowest offset changed since the last call (KD_EDIT_NO_DAMAGE if
// none) and clears it: a view redraws from there.
size_t kd_edit_take_damage(kd_edit *e);

// Checks every invariant (tests and debug builds).
bool kd_edit_valid(const kd_edit *e);

#endif
