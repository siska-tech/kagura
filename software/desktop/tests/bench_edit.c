// SPDX-License-Identifier: Apache-2.0
// Flat buffer (kd_edit) versus a gap buffer, per keystroke, on the host.
// The flat buffer moves the text after the caret on every insertion or
// deletion; the gap buffer moves only when the caret jumps, but a view then
// has to draw two spans (or close the gap). Worst case for the flat buffer:
// typing at the very start of a full document.
//   kd_edit_bench [document bytes]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "kd_edit.h"

static double now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e9 + t.tv_nsec;
}

// Minimal byte gap buffer: text = buf[0..gs) + buf[ge..cap).
typedef struct {
    uint8_t *buf;
    size_t cap, gs, ge;
} gap;

static void gap_move(gap *g, size_t pos) {
    if (pos < g->gs) {
        size_t n = g->gs - pos;
        memmove(g->buf + g->ge - n, g->buf + pos, n);
        g->gs -= n;
        g->ge -= n;
    } else if (pos > g->gs) {
        size_t n = pos - g->gs;
        memmove(g->buf + g->gs, g->buf + g->ge, n);
        g->gs += n;
        g->ge += n;
    }
}

int main(int argc, char **argv) {
    size_t size = argc > 1 ? (size_t)atol(argv[1]) : 8192;
    enum { KEYS = 200000 };
    uint8_t *flat = malloc(size + 2), *gb = malloc(size + 2);
    if (!flat || !gb) return 1;
    kd_edit e;
    kd_edit_init(&e, flat, size + 2, 0);
    for (size_t i = 0; i < size; i++) kd_edit_insert(&e, (const uint8_t *)(i % 64 == 63 ? "\n" : "x"), 1);
    gap g = {gb, size + 2, size, size + 2};
    memset(gb, 'x', size);

    volatile uint32_t sink = 0;
    // 1. Typing a character and deleting it at the start (flat worst case).
    kd_edit_select(&e, 0, 0);
    double t0 = now_ns();
    for (int k = 0; k < KEYS; k++) {
        kd_edit_insert(&e, (const uint8_t *)"y", 1);
        kd_edit_delete(&e, true);
    }
    double flat_start = (now_ns() - t0) / (2.0 * KEYS);
    gap_move(&g, 0);
    t0 = now_ns();
    for (int k = 0; k < KEYS; k++) {
        g.buf[g.gs++] = 'y';
        g.gs--;
        sink += g.buf[g.gs];
    }
    double gap_start = (now_ns() - t0) / (2.0 * KEYS);

    // 2. Each keystroke after a jump to a random position (gap worst case).
    uint32_t s = 1;
    t0 = now_ns();
    for (int k = 0; k < KEYS; k++) {
        s = s * 1664525u + 1013904223u;
        size_t p = (s >> 8) % size;
        kd_edit_select(&e, p, p);
        kd_edit_insert(&e, (const uint8_t *)"y", 1);
        kd_edit_delete(&e, true);
    }
    double flat_jump = (now_ns() - t0) / (2.0 * KEYS);
    s = 1;
    t0 = now_ns();
    for (int k = 0; k < KEYS; k++) {
        s = s * 1664525u + 1013904223u;
        gap_move(&g, (s >> 8) % size);
        g.buf[g.gs++] = 'y';
        g.gs--;
        sink += g.buf[g.gs];
    }
    double gap_jump = (now_ns() - t0) / (2.0 * KEYS);

    printf("document %zu B, ns per edit (host)\n", size);
    printf("  typing at the start: flat %.1f, gap %.1f\n", flat_start, gap_start);
    printf("  after a random jump: flat %.1f, gap %.1f\n", flat_jump, gap_jump);
    free(flat);
    free(gb);
    return sink == 0xFFFFFFFFu;
}
