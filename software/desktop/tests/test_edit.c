// SPDX-License-Identifier: Apache-2.0
// Tests of the bounded UTF-8 editing core (text/kd_edit.c) without hardware:
// strict validation, atomic failures, capacity bounds, scalar-boundary
// motion, selections, line breaks, and random sequences checked against a
// model that edits arrays of scalar values.
#include <string.h>

#include "kd_edit.h"
#include "kd_test.h"

int kd_test_failed;
int kd_test_quiet;

void kd_test_fail(const char *file, int line, const char *what) {
    kd_test_failed++;
    if (!kd_test_quiet) fprintf(stderr, "  FAIL %s:%d: %s\n", file, line, what);
}

#define CANARY 0xA5
static uint8_t store[1024 + 16];
static kd_edit E;

static void setup(size_t cap, unsigned flags) {
    memset(store, CANARY, sizeof store);
    if (kd_edit_init(&E, store, cap, flags) != KD_EDIT_OK) kd_test_fail(__FILE__, __LINE__, "init");
}

static bool canary_ok(void) {
    for (size_t i = E.cap; i < sizeof store; i++)
        if (store[i] != CANARY) return false;
    return true;
}

static int put(const char *s) { return kd_edit_insert(&E, (const uint8_t *)s, strlen(s)); }
static int set(const char *s) { return kd_edit_set(&E, (const uint8_t *)s, strlen(s)); }
static bool is(const char *s) { return E.len == strlen(s) && !strcmp(kd_edit_text(&E), s); }

// Snapshot for atomicity checks: the whole observable state.
typedef struct {
    uint8_t bytes[sizeof store];
    kd_edit e;
} snap;
static snap S;
static void take(void) {
    memcpy(S.bytes, store, sizeof store);
    S.e = E;
}
static bool same(void) { return !memcmp(S.bytes, store, sizeof store) && !memcmp(&S.e, &E, sizeof E); }

// Japanese and other test characters by UTF-8 length.
#define A2 "\xC3\xA9"           // é U+00E9
#define J3 "\xE7\xA5\x9E"       // 神 U+795E
#define K3 "\xE6\xA5\xBD"       // 楽 U+697D
#define E4 "\xF0\x9F\x98\x80"   // 😀 U+1F600

static void t_init_arguments(void) {
    uint8_t b[4];
    kd_edit e;
    CHECK_EQ(kd_edit_init(&e, NULL, 4, 0), KD_EDIT_EINVAL);
    CHECK_EQ(kd_edit_init(&e, b, 0, 0), KD_EDIT_EINVAL);
    CHECK_EQ(kd_edit_init(&e, b, 4, 2), KD_EDIT_EINVAL);
    CHECK_EQ(kd_edit_init(&e, b, 1, 0), KD_EDIT_OK);
    CHECK(kd_edit_valid(&e) && e.len == 0 && e.buf[0] == 0);
    // Capacity 1 holds only the NUL: every insertion is full.
    CHECK_EQ(kd_edit_insert(&e, (const uint8_t *)"a", 1), KD_EDIT_EFULL);
    CHECK_EQ(kd_edit_insert(&e, NULL, 0), KD_EDIT_OK);
    CHECK_EQ(kd_edit_insert(&e, NULL, 3), KD_EDIT_EINVAL);
}

static void t_ascii(void) {
    setup(64, 0);
    CHECK_EQ(put("helo"), KD_EDIT_OK);
    CHECK(is("helo") && E.caret == 4);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, false, NULL, NULL), 1);
    CHECK_EQ(put("l"), KD_EDIT_OK);
    CHECK(is("hello") && E.caret == 4);
    CHECK_EQ(kd_edit_delete(&E, true), 1);
    CHECK(is("helo") && E.caret == 3);
    CHECK_EQ(kd_edit_delete(&E, false), 1);
    CHECK(is("hel") && E.caret == 3);
    CHECK_EQ(kd_edit_delete(&E, false), 0);   // at the end
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_HOME, false, NULL, NULL), 1);
    CHECK_EQ(kd_edit_delete(&E, true), 0);    // at the start
    CHECK(is("hel") && kd_edit_valid(&E) && canary_ok());
}

static void t_empty(void) {
    setup(16, 0);
    for (int m = KD_EDIT_LEFT; m <= KD_EDIT_FINISH; m++) {
        CHECK_EQ(kd_edit_move(&E, m, false, NULL, NULL), 0);
        CHECK_EQ(kd_edit_move(&E, m, true, NULL, NULL), 0);
    }
    CHECK_EQ(kd_edit_delete(&E, true), 0);
    CHECK_EQ(kd_edit_delete(&E, false), 0);
    kd_edit_select_all(&E);
    CHECK(!kd_edit_has_selection(&E));
    char out[4] = "xyz";
    CHECK_EQ(kd_edit_copy(&E, out, sizeof out), 0);
    CHECK(out[0] == 0);
    CHECK_EQ(kd_edit_count(&E, 0, 0), 0);
    CHECK_EQ(kd_edit_line_index(&E, 0), 0);
    CHECK_EQ(kd_edit_x(&E, 0, NULL, NULL), 0);
    CHECK_EQ(set(""), KD_EDIT_OK);
    CHECK(is("") && kd_edit_valid(&E));
}

static void t_japanese_and_mixed(void) {
    setup(64, 0);
    CHECK_EQ(put(J3 K3), KD_EDIT_OK);
    CHECK_EQ(E.len, 6);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, false, NULL, NULL), 1);
    CHECK_EQ(E.caret, 3);
    CHECK_EQ(put("A" A2), KD_EDIT_OK);
    CHECK(is(J3 "A" A2 K3) && E.caret == 6);
    CHECK_EQ(kd_edit_count(&E, 0, E.len), 4);
    CHECK_EQ(kd_edit_count(&E, 0, E.caret), 3);
    CHECK_EQ(kd_edit_delete(&E, true), 1);   // é, both bytes
    CHECK(is(J3 "A" K3));
    CHECK_EQ(kd_edit_delete(&E, false), 1);  // 楽, all three bytes
    CHECK(is(J3 "A"));
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_START, false, NULL, NULL), 1);
    CHECK_EQ(kd_edit_delete(&E, false), 1);
    CHECK(is("A") && kd_edit_valid(&E));
}

static void t_boundaries_all_lengths(void) {
    // Scalars of 1, 2, 3 and 4 bytes, walked both ways.
    static const char text[] = "a" A2 J3 E4 "z";
    static const size_t stops[] = {0, 1, 3, 6, 10, 11};
    setup(64, 0);
    CHECK_EQ(set(text), KD_EDIT_OK);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_START, false, NULL, NULL), 1);
    for (size_t i = 1; i < 6; i++) {
        CHECK_EQ(kd_edit_move(&E, KD_EDIT_RIGHT, false, NULL, NULL), 1);
        CHECK_EQ(E.caret, stops[i]);
        CHECK_EQ(kd_edit_count(&E, 0, E.caret), i);
    }
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_RIGHT, false, NULL, NULL), 0);
    for (size_t i = 5; i > 0; i--) {
        CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, false, NULL, NULL), 1);
        CHECK_EQ(E.caret, stops[i - 1]);
    }
    for (size_t p = 0; p <= E.len; p++) {
        bool stop = false;
        for (size_t i = 0; i < 6; i++) stop |= stops[i] == p;
        CHECK(kd_edit_is_boundary(&E, p) == stop);
    }
    CHECK(!kd_edit_is_boundary(&E, E.len + 1));
    // Positions inside a scalar are rejected and change nothing.
    take();
    CHECK_EQ(kd_edit_select(&E, 0, 4), KD_EDIT_EINVAL);
    CHECK_EQ(kd_edit_select(&E, 7, 0), KD_EDIT_EINVAL);
    CHECK_EQ(kd_edit_select(&E, 0, 99), KD_EDIT_EINVAL);
    CHECK(same());
    // Deleting the 4-byte scalar from both sides.
    CHECK_EQ(kd_edit_select(&E, 10, 10), 1);
    CHECK_EQ(kd_edit_delete(&E, true), 1);
    CHECK(is("a" A2 J3 "z"));
    CHECK_EQ(set("a" E4), KD_EDIT_OK);
    CHECK_EQ(kd_edit_select(&E, 1, 1), 1);
    CHECK_EQ(kd_edit_delete(&E, false), 1);
    CHECK(is("a") && kd_edit_valid(&E));
}

static void t_invalid_utf8(void) {
    static const struct { const char *s; size_t n; } bad[] = {
        {"\x80", 1}, {"\xC0\x80", 2}, {"\xC1\xBF", 2}, {"\xE0\x80\x80", 3},
        {"\xED\xA0\x80", 3},                       // surrogate
        {"\xF4\x90\x80\x80", 4}, {"\xF5\x80\x80\x80", 4}, {"\xFF", 1},
        {"\xE7\xA5", 2},                           // truncated 3-byte
        {"\xF0\x9F\x98", 3},                       // truncated 4-byte
        {"\xC3", 1},                               // truncated 2-byte
        {"ab\xE7\xA5" "c", 5},                     // truncated, followed by ASCII
        {"\xE3\x28\xA1", 3},
        {"a\0b", 3},                               // NUL
    };
    setup(64, 0);
    CHECK_EQ(set("x" J3 "y"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_select(&E, 1, 4), 1);
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        take();
        CHECK_EQ(kd_edit_measure((const uint8_t *)bad[i].s, bad[i].n, 0), KD_EDIT_EUTF8);
        CHECK_EQ(kd_edit_insert(&E, (const uint8_t *)bad[i].s, bad[i].n), KD_EDIT_EUTF8);
        CHECK(same());
        CHECK_EQ(kd_edit_set(&E, (const uint8_t *)bad[i].s, bad[i].n), KD_EDIT_EUTF8);
        CHECK(same());
    }
    CHECK(is("x" J3 "y") && kd_edit_valid(&E) && canary_ok());
}

static void t_capacity(void) {
    // Capacity 8: seven bytes of text.
    setup(8, 0);
    CHECK_EQ(put("abcd"), KD_EDIT_OK);
    take();
    CHECK_EQ(put("efgh"), KD_EDIT_EFULL);   // 8 > 7
    CHECK(same());
    CHECK_EQ(put(J3), KD_EDIT_OK);          // exactly full
    CHECK(is("abcd" J3) && E.len == E.cap - 1 && canary_ok());
    take();
    CHECK_EQ(put("x"), KD_EDIT_EFULL);
    CHECK(same());
    CHECK_EQ(set("12345678"), KD_EDIT_EFULL);
    CHECK(same());
    // Replacing a selection may grow up to the capacity...
    CHECK_EQ(kd_edit_select(&E, 4, 7), 1);
    CHECK_EQ(put("xyz"), KD_EDIT_OK);
    CHECK(is("abcdxyz"));
    // ...but not past it, and a failed replacement keeps the selection.
    CHECK_EQ(kd_edit_select(&E, 0, 1), 1);
    take();
    CHECK_EQ(put("12"), KD_EDIT_EFULL);
    CHECK(same());
    // Multibyte input that does not fit is refused whole, not cut.
    CHECK_EQ(set("abcde"), KD_EDIT_OK);
    take();
    CHECK_EQ(put(J3), KD_EDIT_EFULL);
    CHECK(same() && canary_ok() && kd_edit_valid(&E));
    // A full buffer still deletes and moves.
    CHECK_EQ(set("abcdefg"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_delete(&E, true), 1);
    CHECK_EQ(put(A2), KD_EDIT_EFULL);
    CHECK_EQ(put("h"), KD_EDIT_OK);
    CHECK(is("abcdefh") && canary_ok());
}

static void t_selection(void) {
    setup(64, 0);
    CHECK_EQ(set("ab" J3 "cd"), KD_EDIT_OK);
    // Shift+Left twice from the end selects "cd"; anchor stays.
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, true, NULL, NULL), 1);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, true, NULL, NULL), 1);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, true, NULL, NULL), 1);
    size_t a, b;
    kd_edit_selection(&E, &a, &b);
    CHECK(a == 2 && b == 7 && E.anchor == 7 && E.caret == 2);
    char out[16];
    CHECK_EQ(kd_edit_copy(&E, out, sizeof out), 5);
    CHECK(!strcmp(out, J3 "cd"));
    // Too small: nothing copied, the size is reported.
    memset(out, 'Q', sizeof out);
    CHECK_EQ(kd_edit_copy(&E, out, 5), 5);
    CHECK(out[0] == 'Q');
    // Replacement (typing over the selection).
    CHECK_EQ(put(K3), KD_EDIT_OK);
    CHECK(is("ab" K3) && E.caret == 5 && !kd_edit_has_selection(&E));
    // Left/Right without Shift collapse to the selection's ends.
    kd_edit_select_all(&E);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, false, NULL, NULL), 1);
    CHECK(E.caret == 0 && E.anchor == 0);
    kd_edit_select_all(&E);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_RIGHT, false, NULL, NULL), 1);
    CHECK(E.caret == E.len && E.anchor == E.len);
    // Backspace and Delete remove the selection (cut = copy + delete).
    CHECK_EQ(kd_edit_select(&E, 1, 5), 1);
    CHECK_EQ(kd_edit_select(&E, 1, 5), 0);
    CHECK_EQ(kd_edit_delete(&E, false), 1);
    CHECK(is("a") && E.caret == 1);
    CHECK_EQ(set("xyz"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_select(&E, 3, 1), 1);
    CHECK_EQ(kd_edit_delete(&E, true), 1);
    CHECK(is("x") && E.caret == 1);
    // Replacing a selection with an empty string deletes it.
    CHECK_EQ(set("hello"), KD_EDIT_OK);
    kd_edit_select_all(&E);
    CHECK_EQ(put(""), KD_EDIT_OK);
    CHECK(is("") && kd_edit_valid(&E));
}

static void t_newlines(void) {
    setup(64, 0);
    CHECK_EQ(kd_edit_measure((const uint8_t *)"a\r\nb\rc\n", 7, 0), 6);
    CHECK_EQ(put("a\r\nb\rc\n"), KD_EDIT_OK);
    CHECK(is("a\nb\nc\n") && E.caret == 6);
    CHECK_EQ(kd_edit_line_index(&E, E.caret), 3);
    CHECK_EQ(put("\r"), KD_EDIT_OK);     // a CR at the end of input is a line break too
    CHECK(is("a\nb\nc\n\n"));
    CHECK_EQ(set("\r\n\r\n"), KD_EDIT_OK);
    CHECK(is("\n\n"));
    CHECK_EQ(set("\n\r"), KD_EDIT_OK);   // LF CR is two breaks
    CHECK(is("\n\n"));
    // Backspace across a line boundary joins the lines.
    CHECK_EQ(set("ab\ncd"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_select(&E, 3, 3), 1);
    CHECK_EQ(kd_edit_delete(&E, true), 1);
    CHECK(is("abcd") && E.caret == 2);
    // Home/End stay on the logical line.
    CHECK_EQ(set("one\n" J3 K3 "\nthree"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_select(&E, 7, 7), 1);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_HOME, false, NULL, NULL), 1);
    CHECK_EQ(E.caret, 4);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_HOME, false, NULL, NULL), 0);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_END, true, NULL, NULL), 1);
    CHECK(E.caret == 10 && E.anchor == 4);
    CHECK_EQ(kd_edit_line_start(&E, 10), 4);
    CHECK_EQ(kd_edit_line_end(&E, 4), 10);
    CHECK_EQ(kd_edit_line_end(&E, 11), E.len);
    CHECK_EQ(kd_edit_line_index(&E, 11), 2);
    // Single-line buffers refuse breaks atomically.
    setup(64, KD_EDIT_SINGLE_LINE);
    CHECK_EQ(put("abc"), KD_EDIT_OK);
    take();
    CHECK_EQ(put("x\ny"), KD_EDIT_ELINE);
    CHECK_EQ(put("\r"), KD_EDIT_ELINE);
    CHECK_EQ(set("a\r\nb"), KD_EDIT_ELINE);
    CHECK(same() && kd_edit_valid(&E));
}

// Visual widths: ASCII 4 px (the small font), everything else 8 px.
static int adv_small(void *ctx, uint32_t c) {
    (void)ctx;
    return c < 0x80 ? 4 : 8;
}

static void t_vertical_motion(void) {
    setup(128, 0);
    // Line 0: "abcdef" (24 px). Line 1: 神楽 (16 px). Line 2: "" . Line 3: "abcdefgh".
    CHECK_EQ(set("abcdef\n" J3 K3 "\n\nabcdefgh"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_select(&E, 4, 4), 1);   // x = 16 px, after "abcd"
    CHECK_EQ(kd_edit_x(&E, 4, adv_small, NULL), 16);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_DOWN, false, adv_small, NULL), 1);
    CHECK_EQ(E.caret, 13);                    // after 楽: x 16
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_DOWN, false, adv_small, NULL), 1);
    CHECK_EQ(E.caret, 14);                    // the empty line
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_DOWN, false, adv_small, NULL), 1);
    CHECK_EQ(E.caret, 19);                    // goal x 16 kept: after "abcd"
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_DOWN, false, adv_small, NULL), 1);
    CHECK_EQ(E.caret, E.len);                 // last line: to its end
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_UP, false, adv_small, NULL), 1);
    CHECK_EQ(E.caret, 14);
    // Same moves counted in scalars (adv NULL): column 4 on line 1 is its end.
    CHECK_EQ(kd_edit_select(&E, 4, 4), 1);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_DOWN, false, NULL, NULL), 1);
    CHECK_EQ(E.caret, 13);
    CHECK_EQ(kd_edit_count(&E, 7, 13), 2);
    // A goal between two halves of a wide glyph stays left of it.
    CHECK_EQ(kd_edit_select(&E, 3, 3), 1);   // x 12
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_DOWN, true, adv_small, NULL), 1);
    CHECK(E.caret == 10 && E.anchor == 3);   // after 神 (8 px <= 12 < 16)
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_UP, false, adv_small, NULL), 1);
    CHECK_EQ(E.caret, 3);                     // goal x 12 returns to "abc|"
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_UP, false, adv_small, NULL), 1);
    CHECK_EQ(E.caret, 0);                     // first line: to its start
    CHECK_EQ(kd_edit_move(&E, 99, false, NULL, NULL), KD_EDIT_EINVAL);
}

static void t_damage_and_version(void) {
    setup(64, 0);
    CHECK_EQ(kd_edit_take_damage(&E), 0);
    CHECK_EQ(kd_edit_take_damage(&E), KD_EDIT_NO_DAMAGE);
    CHECK_EQ(set("abcdef"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_take_damage(&E), 0);
    uint32_t v = E.version;
    CHECK_EQ(kd_edit_select(&E, 4, 4), 1);
    CHECK_EQ(kd_edit_move(&E, KD_EDIT_LEFT, true, NULL, NULL), 1);
    CHECK(E.version == v && kd_edit_take_damage(&E) == KD_EDIT_NO_DAMAGE);   // motion
    CHECK_EQ(put("X"), KD_EDIT_OK);
    CHECK_EQ(kd_edit_delete(&E, false), 1);
    CHECK_EQ(kd_edit_take_damage(&E), 3);   // lowest of the two changes
    CHECK_EQ(E.version, v + 2);
    take();
    CHECK_EQ(put("\xFF"), KD_EDIT_EUTF8);
    CHECK_EQ(kd_edit_delete(&E, false), 1);
    CHECK_EQ(E.version, v + 3);
    CHECK_EQ(kd_edit_take_damage(&E), 4);
    CHECK_EQ(kd_edit_delete(&E, false), 0);
    CHECK_EQ(kd_edit_take_damage(&E), KD_EDIT_NO_DAMAGE);
    kd_edit_reset(&E);
    CHECK(is("") && E.caret == 0 && kd_edit_take_damage(&E) == 0);
}

// ---- random sequences against a model of scalar arrays ----

#define MODEL_MAX 300
typedef struct {
    uint32_t c[MODEL_MAX];
    int n, caret, anchor;
} model;
static model Mo;

static size_t enc(uint32_t c, uint8_t *o) {
    if (c < 0x80) { o[0] = (uint8_t)c; return 1; }
    if (c < 0x800) { o[0] = (uint8_t)(0xC0 | c >> 6); o[1] = (uint8_t)(0x80 | (c & 63)); return 2; }
    if (c < 0x10000) {
        o[0] = (uint8_t)(0xE0 | c >> 12); o[1] = (uint8_t)(0x80 | (c >> 6 & 63)); o[2] = (uint8_t)(0x80 | (c & 63));
        return 3;
    }
    o[0] = (uint8_t)(0xF0 | c >> 18); o[1] = (uint8_t)(0x80 | (c >> 12 & 63));
    o[2] = (uint8_t)(0x80 | (c >> 6 & 63)); o[3] = (uint8_t)(0x80 | (c & 63));
    return 4;
}

static size_t model_bytes(int from, int to) {
    uint8_t t[4];
    size_t n = 0;
    for (int i = from; i < to; i++) n += enc(Mo.c[i], t);
    return n;
}

static bool model_matches(void) {
    uint8_t t[MODEL_MAX * 4 + 1];
    size_t n = 0;
    for (int i = 0; i < Mo.n; i++) n += enc(Mo.c[i], t + n);
    return n == E.len && !memcmp(t, E.buf, n) && E.caret == model_bytes(0, Mo.caret) &&
           E.anchor == model_bytes(0, Mo.anchor) && kd_edit_valid(&E) && canary_ok();
}

static void model_place(int to, bool extend) {
    Mo.caret = to;
    if (!extend) Mo.anchor = to;
}

static void random_run(uint32_t seed, size_t cap, unsigned flags) {
    static const uint32_t pool[] = {'a', 'Z', ' ', '~', 0xE9, 0x3042, 0x795E, 0x697D, 0xFF5E, 0x1F600, 0x10FFFF, '\n'};
    uint32_t s = seed;
    setup(cap, flags);
    memset(&Mo, 0, sizeof Mo);
    for (int step = 0; step < 20000; step++) {
        int op = kd_rand_range(&s, 0, 9);
        int a = Mo.anchor < Mo.caret ? Mo.anchor : Mo.caret, b = Mo.anchor < Mo.caret ? Mo.caret : Mo.anchor;
        if (op <= 3) {   // insert 1..4 scalars, sometimes with CRLF, sometimes broken
            uint32_t ins[8];
            int k = kd_rand_range(&s, 1, 4), m = 0;
            uint8_t bytes[40];
            size_t n = 0;
            size_t last = 0;
            for (int i = 0; i < k; i++) {
                uint32_t c = pool[kd_rand_range(&s, 0, 11)];
                if (c == '\n' && kd_rand_range(&s, 0, 1)) bytes[n++] = '\r';   // CRLF: one break
                last = enc(c, bytes + n);
                n += last;
                ins[m++] = c;
            }
            // Sometimes cut the last multibyte scalar short: the whole input is refused.
            bool valid_tail = true;
            if (last > 1 && kd_rand_range(&s, 0, 15) == 0) {
                n--;
                valid_tail = false;
            }
            bool has_break = false;
            for (int i = 0; i < m; i++) has_break |= ins[i] == '\n';
            size_t need = model_bytes(0, Mo.n) - model_bytes(a, b);
            uint8_t t[4];
            for (int i = 0; i < m; i++) need += enc(ins[i], t);
            // The first problem in the input is reported; a cut scalar is always last.
            int expect = (flags & KD_EDIT_SINGLE_LINE) && has_break ? KD_EDIT_ELINE
                         : !valid_tail ? KD_EDIT_EUTF8
                         : need > cap - 1 ? KD_EDIT_EFULL : KD_EDIT_OK;
            take();
            int rc = kd_edit_insert(&E, bytes, n);
            CHECK_EQ(rc, expect);
            if (rc != KD_EDIT_OK) {
                CHECK(same());
            } else {
                memmove(&Mo.c[a + m], &Mo.c[b], (size_t)(Mo.n - b) * sizeof Mo.c[0]);
                memcpy(&Mo.c[a], ins, (size_t)m * sizeof ins[0]);
                Mo.n += m - (b - a);
                Mo.caret = Mo.anchor = a + m;
            }
        } else if (op <= 5) {   // backspace / delete
            bool back = op == 4;
            int da = a, db = b;
            if (da == db) {
                if (back && da > 0) da--;
                else if (!back && db < Mo.n) db++;
            }
            CHECK_EQ(kd_edit_delete(&E, back), da != db);
            memmove(&Mo.c[da], &Mo.c[db], (size_t)(Mo.n - db) * sizeof Mo.c[0]);
            Mo.n -= db - da;
            Mo.caret = Mo.anchor = da;
        } else if (op <= 8) {   // horizontal motion
            int motion = kd_rand_range(&s, 0, 5);
            motion = motion < 4 ? motion : motion + 2;   // LEFT RIGHT HOME END START FINISH
            bool extend = kd_rand_range(&s, 0, 1);
            int to = Mo.caret, ls = Mo.caret, le = Mo.caret;
            while (ls > 0 && Mo.c[ls - 1] != '\n') ls--;
            while (le < Mo.n && Mo.c[le] != '\n') le++;
            switch (motion) {
            case KD_EDIT_LEFT: to = !extend && a != b ? a : Mo.caret > 0 ? Mo.caret - 1 : 0; break;
            case KD_EDIT_RIGHT: to = !extend && a != b ? b : Mo.caret < Mo.n ? Mo.caret + 1 : Mo.n; break;
            case KD_EDIT_HOME: to = ls; break;
            case KD_EDIT_END: to = le; break;
            case KD_EDIT_START: to = 0; break;
            default: to = Mo.n; break;
            }
            int old_c = Mo.caret, old_a = Mo.anchor;
            model_place(to, extend);
            CHECK_EQ(kd_edit_move(&E, motion, extend, NULL, NULL), old_c != Mo.caret || old_a != Mo.anchor);
        } else {
            kd_edit_select_all(&E);
            Mo.anchor = 0;
            Mo.caret = Mo.n;
        }
        if (!model_matches()) {
            char msg[64];
            snprintf(msg, sizeof msg, "model mismatch, seed %u step %d op %d", seed, step, op);
            kd_test_fail(__FILE__, __LINE__, msg);
            return;
        }
    }
}

static void t_random_small(void) { random_run(1, 24, 0); }
static void t_random_large(void) { random_run(2, 400, 0); }
static void t_random_single_line(void) { random_run(3, 64, KD_EDIT_SINGLE_LINE); }

static const kd_test_case tests[] = {
    {"init_arguments", t_init_arguments},
    {"ascii", t_ascii},
    {"empty", t_empty},
    {"japanese_and_mixed", t_japanese_and_mixed},
    {"boundaries_all_lengths", t_boundaries_all_lengths},
    {"invalid_utf8", t_invalid_utf8},
    {"capacity", t_capacity},
    {"selection", t_selection},
    {"newlines", t_newlines},
    {"vertical_motion", t_vertical_motion},
    {"damage_and_version", t_damage_and_version},
    {"random_small", t_random_small},
    {"random_large", t_random_large},
    {"random_single_line", t_random_single_line},
    {NULL, NULL},
};

int main(int argc, char **argv) {
    const char *only = argc > 1 ? argv[1] : NULL;
    int run = 0, failed = 0;
    for (const kd_test_case *t = tests; t->name; t++) {
        if (only && !strstr(t->name, only)) continue;
        kd_test_failed = 0;
        t->fn();
        run++;
        if (kd_test_failed) failed++;
        printf("%-4s %s\n", kd_test_failed ? "FAIL" : "ok", t->name);
    }
    printf("%d tests, %d failed\n", run, failed);
    return failed ? 1 : 0;
}
