// SPDX-License-Identifier: Apache-2.0
// Test harness and a KSNG builder for the audio host tests.
#ifndef KA_TEST_H
#define KA_TEST_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ks_song.h"

static int ka_failed, ka_total_failed;

#define CHECK(cond)                                                              \
    do {                                                                         \
        if (!(cond)) {                                                           \
            fprintf(stderr, "%s:%d: CHECK(%s)\n", __FILE__, __LINE__, #cond);    \
            ka_failed++;                                                         \
            return;                                                              \
        }                                                                        \
    } while (0)

#define CHECK_EQ(a, b)                                                           \
    do {                                                                         \
        long long a_ = (long long)(a), b_ = (long long)(b);                      \
        if (a_ != b_) {                                                          \
            fprintf(stderr, "%s:%d: %s == %s (%lld != %lld)\n", __FILE__,        \
                    __LINE__, #a, #b, a_, b_);                                   \
            ka_failed++;                                                         \
            return;                                                              \
        }                                                                        \
    } while (0)

typedef struct {
    const char *name;
    void (*fn)(void);
} ka_case;

static inline int ka_run(const ka_case *cases, size_t n, const char *suite) {
    for (size_t i = 0; i < n; i++) {
        ka_failed = 0;
        cases[i].fn();
        if (ka_failed) {
            fprintf(stderr, "FAIL %s.%s\n", suite, cases[i].name);
            ka_total_failed++;
        }
    }
    printf("%s: %zu tests, %d failed\n", suite, n, ka_total_failed);
    return ka_total_failed ? 1 : 0;
}

static inline uint32_t ka_rand(uint32_t *s) {
    *s = *s * 1664525u + 1013904223u;
    return *s >> 8;
}

// Builder: a song with up to 6 tracks, patterns of unpacked cells.
typedef struct {
    uint8_t flags, tracks, instruments, waves, patterns, orders, loop_order, speed, tempo;
    uint8_t voice[KS_TRACKS];
    uint8_t order[KS_ORDERS];
    uint8_t instrument[KS_INSTRUMENTS][KS_INSTRUMENT_BYTES];
    uint8_t wave_log2[KS_WAVES];
    uint8_t wave[KS_WAVES][256];
    uint8_t rows[8];
    uint8_t cells[8][64 * KS_TRACKS * KS_CELL_BYTES];
} kb_song;

static inline void kb_init(kb_song *b, unsigned tracks, unsigned rows) {
    memset(b, 0, sizeof *b);
    b->flags = KS_FLAG_LOOP;
    b->tracks = (uint8_t)tracks;
    b->instruments = 1;
    b->patterns = 1;
    b->orders = 1;
    b->speed = 6;
    b->tempo = 125;
    for (unsigned t = 0; t < tracks; t++) b->voice[t] = (uint8_t)t;
    // Instrument 0: pulse, duty 128, volume 15, centre, no envelope, sustain 15.
    const uint8_t in0[8] = {KS_KIND_PULSE, 128, 15, 128, 0, 0, 15, 0};
    memcpy(b->instrument[0], in0, 8);
    for (unsigned p = 0; p < 8; p++) {
        b->rows[p] = (uint8_t)rows;
        for (unsigned i = 0; i < 64 * KS_TRACKS; i++) {
            uint8_t *c = b->cells[p] + i * KS_CELL_BYTES;
            c[0] = 0;
            c[1] = c[2] = KS_NONE;
            c[3] = c[4] = 0;
        }
    }
}

static inline uint8_t *kb_cell(kb_song *b, unsigned pattern, unsigned row, unsigned track) {
    return b->cells[pattern] + (row * b->tracks + track) * KS_CELL_BYTES;
}

static inline void kb_note(kb_song *b, unsigned pattern, unsigned row, unsigned track, unsigned note, unsigned inst) {
    uint8_t *c = kb_cell(b, pattern, row, track);
    c[0] = (uint8_t)note;
    c[1] = (uint8_t)inst;
}

static inline void kb_fx(kb_song *b, unsigned pattern, unsigned row, unsigned track, unsigned fx, unsigned param) {
    uint8_t *c = kb_cell(b, pattern, row, track);
    c[3] = (uint8_t)fx;
    c[4] = (uint8_t)param;
}

// Returns the file size, 0 on failure.
static inline size_t kb_build(const kb_song *b, uint8_t *out, size_t cap) {
    size_t n = 0;
    if (cap < KS_HEADER) return 0;
    memset(out, 0, KS_HEADER);
    memcpy(out, KS_MAGIC, 4);
    out[4] = KS_VERSION;
    out[5] = b->flags;
    out[6] = b->tracks;
    out[7] = b->instruments;
    out[8] = b->waves;
    out[9] = b->patterns;
    out[10] = b->orders;
    out[11] = b->loop_order;
    out[12] = b->speed;
    out[13] = b->tempo;
    memcpy(out + 16, "TEST SONG", 9);
    memcpy(out + 32, "KAGURA", 6);
    n = KS_HEADER;
    memcpy(out + n, b->voice, b->tracks);
    n += b->tracks;
    memcpy(out + n, b->order, b->orders);
    n += b->orders;
    for (unsigned i = 0; i < b->instruments; i++, n += 8) memcpy(out + n, b->instrument[i], 8);
    for (unsigned w = 0; w < b->waves; w++) {
        out[n++] = b->wave_log2[w];
        memcpy(out + n, b->wave[w], (size_t)1 << b->wave_log2[w]);
        n += (size_t)1 << b->wave_log2[w];
    }
    for (unsigned p = 0; p < b->patterns; p++) {
        size_t size = ks_pack(b->cells[p], b->rows[p], b->tracks, b->instruments, out + n + 3, cap - n - 3);
        if (!size) return 0;
        out[n] = b->rows[p];
        out[n + 1] = (uint8_t)size;
        out[n + 2] = (uint8_t)(size >> 8);
        n += 3 + size;
    }
    return n;
}

#endif
