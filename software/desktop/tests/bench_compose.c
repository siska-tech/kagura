// SPDX-License-Identifier: Apache-2.0
// Host benchmark of the editor's expensive keys: a line break in the middle
// of a document (the lines below move) and PgDn/PgUp (the whole view), as in
// tools/kagura-editor-board.py bench. For profiling (perf) and for comparing
// compositor changes; host times do not predict the RP2040.
//   kd_compose_bench [repeats]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "kdm.h"

static kdm M;

static double now_us(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e6 + t.tv_nsec / 1e3;
}

static void key(uint8_t k, uint8_t mods) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = KD_EV_KEY;
    e.key = k;
    e.mods = mods;
    kdm_feed(&M, &e);
}

static void drain(void) {
    kdm_event e;
    while (kdm_peek(&M, &e)) kdm_drop(&M);
}

static double run(const char *name, int n, void (*fn)(int)) {
    unsigned tiles = 0;
    double t0 = now_us();
    for (int i = 0; i < n; i++) {
        fn(i);
        drain();
        tiles += (unsigned)kdm_present(&M, NULL, NULL, NULL);
    }
    double us = (now_us() - t0) / n;
    printf("%-26s %8.1f us/key  %6.1f tiles/key\n", name, us, (double)tiles / n);
    return us;
}

static void enter_backspace(int i) { key(i % 2 ? KD_KEY_BACKSPACE : KD_KEY_ENTER, 0); }
static void page(int i) { key(i % 2 ? KD_KEY_PGUP : KD_KEY_PGDN, 0); }
static void type_char(int i) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = KD_EV_KEY;
    e.key = KD_KEY_CHAR;
    e.ch = (char)('a' + i % 26);
    kdm_feed(&M, &e);
}

int main(int argc, char **argv) {
    int n = argc > 1 ? atoi(argv[1]) : 400;
    static char doc[KDM_DOC_BYTES];
    size_t len = 0;
    for (int i = 0; i < 100; i++)
        len += (size_t)snprintf(doc + len, sizeof doc - len, "%03d 行目 神楽メモ帳のテキスト\n", i);
    kdm_init(&M, NULL);
    int w = kdm_window_open(&M, "E", kd_rect_make(0, 11, 320, 189), 0, 2);
    int ed = kdm_add_editor(&M, w, 2, 2, 314, 154, doc, len, 0);
    if (ed < 0) return 1;
    kdm_present(&M, NULL, NULL, NULL);
    for (int i = 0; i < 40; i++) key(KD_KEY_DOWN, 0);
    key(KD_KEY_HOME, 0);
    key(KD_KEY_RIGHT, 0);
    drain();
    kdm_present(&M, NULL, NULL, NULL);
    run("type a character", n, type_char);
    run("Enter / Backspace", n, enter_backspace);
    run("PgDn / PgUp", n, page);
    return 0;
}
