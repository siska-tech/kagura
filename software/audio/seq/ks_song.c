// SPDX-License-Identifier: Apache-2.0
#include "ks_song.h"
#include <string.h>

#ifndef KS_FAULT
#define KS_FAULT 0      // tests: build mutants that must fail test_song
#endif

static int text_ok(const uint8_t *t) {
    unsigned i = 0;
    while (i < 16 && t[i]) {
        if (t[i] < 0x20 || t[i] > 0x7E) return 0;
        i++;
    }
    for (; i < 16; i++)
        if (t[i]) return 0;
    return 1;
}

// Validates one packed row; returns bytes used or 0.
static size_t check_row(const uint8_t *p, size_t avail, unsigned tracks, unsigned instruments) {
    size_t n = 0;
    for (unsigned t = 0; t < tracks; t++) {
        if (n >= avail) return 0;
        uint8_t m = p[n++];
        if (m & 0xF0) return 0;
        size_t need = (size_t)((m & 1) + (m >> 1 & 1) + (m >> 2 & 1) + 2 * (m >> 3 & 1));
        if (avail - n < need) return 0;
        if (m & 1) {
            uint8_t note = p[n++];
            if (note < 1 || note > KS_NOTE_OFF) return 0;
        }
        if (m & 2) {
#if KS_FAULT == 1
            (void)instruments;
            n++;
#else
            if (p[n++] >= instruments) return 0;
#endif
        }
        if (m & 4) {
            if (p[n++] > 15) return 0;
        }
        if (m & 8) {
            uint8_t fx = p[n++];
#if KS_FAULT == 2
            (void)fx;
#else
            if (fx > 15 || !(KS_FX_VALID >> fx & 1u)) return 0;
#endif
            uint8_t param = p[n++];
            if (fx == KS_FX_SPEED && param == 0) return 0;
        }
    }
    return n;
}

int ks_song_parse(ks_song *s, const uint8_t *d, size_t size) {
    memset(s, 0, sizeof *s);
    if (size < KS_HEADER || size > KS_MAX_BYTES) return KS_ESIZE;
    if (memcmp(d, KS_MAGIC, 4)) return KS_EMAGIC;
    if (d[4] != KS_VERSION) return KS_EVERSION;
    s->flags = d[5];
    s->tracks = d[6];
    s->instruments = d[7];
    s->waves = d[8];
    s->patterns = d[9];
    s->orders = d[10];
    s->loop_order = d[11];
    s->speed = d[12];
    s->tempo = d[13];
    if ((s->flags & ~KS_FLAG_LOOP) || s->tracks < 1 || s->tracks > KS_TRACKS ||
        s->instruments < 1 || s->instruments > KS_INSTRUMENTS || s->waves > KS_WAVES ||
        s->patterns < 1 || s->patterns > KS_PATTERNS || s->orders < 1 || s->orders > KS_ORDERS ||
        s->loop_order >= s->orders || s->speed < 1 || s->speed > KS_MAX_SPEED ||
        s->tempo < KS_MIN_TEMPO || d[14] || d[15])
        return KS_EHEADER;
    if (!text_ok(d + 16) || !text_ok(d + 32)) return KS_ETEXT;
    size_t at = KS_HEADER;
    if (size - at < s->tracks) return KS_ESIZE;
    unsigned used = 0;
    for (unsigned t = 0; t < s->tracks; t++) {
        uint8_t v = d[at + t];
        if (v >= KS_TRACKS || (used >> v & 1u)) return KS_ETRACKS;
        used |= 1u << v;
        s->voice[t] = v;
    }
    at += s->tracks;
    if (size - at < s->orders) return KS_ESIZE;
    s->order = d + at;
    for (unsigned i = 0; i < s->orders; i++)
        if (d[at + i] >= s->patterns) return KS_EORDER;
    at += s->orders;
    if ((size - at) / KS_INSTRUMENT_BYTES < s->instruments) return KS_ESIZE;
    s->instrument = d + at;
    for (unsigned i = 0; i < s->instruments; i++) {
        const uint8_t *in = d + at + i * KS_INSTRUMENT_BYTES;
        if (in[0] > KS_KIND_NOISE || in[2] > 15 || in[6] > 15) return KS_EINSTRUMENT;
        if (in[0] == KS_KIND_WAVE && in[1] >= s->waves) return KS_EINSTRUMENT;
        if (in[0] == KS_KIND_NOISE && in[1]) return KS_EINSTRUMENT;
    }
    at += (size_t)s->instruments * KS_INSTRUMENT_BYTES;
    for (unsigned w = 0; w < s->waves; w++) {
        if (size - at < 1) return KS_ESIZE;
        uint8_t log2 = d[at++];
        if (log2 < 5 || log2 > 8) return KS_EWAVE;
        size_t n = (size_t)1 << log2;
        if (size - at < n) return KS_ESIZE;
        s->wave[w] = d + at;
        s->wave_len[w] = (uint16_t)n;
        at += n;
    }
    for (unsigned p = 0; p < s->patterns; p++) {
        if (size - at < 3) return KS_ESIZE;
        uint8_t rows = d[at];
        size_t packed = (size_t)d[at + 1] | (size_t)d[at + 2] << 8;
        if (rows != 16 && rows != 32 && rows != 64) return KS_EPATTERN;
        at += 3;
        if (size - at < packed) return KS_ESIZE;
        size_t n = 0;
        for (unsigned r = 0; r < rows; r++) {
            size_t used_row = check_row(d + at + n, packed - n, s->tracks, s->instruments);
            if (!used_row) return KS_EPATTERN;
            n += used_row;
        }
#if KS_FAULT != 3
        if (n != packed) return KS_EPATTERN;
#endif
        s->pattern[p] = d + at;
        s->rows[p] = rows;
        at += packed;
    }
#if KS_FAULT != 4
    if (at != size) return KS_ESIZE;
#endif
    s->base = d;
    s->size = size;
    return KS_OK;
}

const char *ks_strerror(int err) {
    switch (err) {
    case KS_OK: return "ok";
    case KS_ESIZE: return "size";
    case KS_EMAGIC: return "not a KSNG song";
    case KS_EVERSION: return "unsupported version";
    case KS_EHEADER: return "header";
    case KS_ETEXT: return "title/author";
    case KS_ETRACKS: return "track voices";
    case KS_EORDER: return "order list";
    case KS_EINSTRUMENT: return "instrument";
    case KS_EWAVE: return "wave";
    case KS_EPATTERN: return "pattern";
    default: return "unknown";
    }
}

void ks_song_instrument(const ks_song *s, unsigned i, ks_instrument *o) {
    const uint8_t *in = s->instrument + i * KS_INSTRUMENT_BYTES;
    o->kind = in[0];
    o->data = in[1];
    o->volume = in[2];
    o->pan = in[3];
    o->attack = in[4];
    o->decay = in[5];
    o->sustain = in[6];
    o->release = in[7];
}

size_t ks_unpack_row(const uint8_t *p, unsigned tracks, uint8_t *cells) {
    size_t n = 0;
    for (unsigned t = 0; t < tracks; t++) {
        uint8_t *c = cells + t * KS_CELL_BYTES;
        uint8_t m = p[n++];
        c[0] = m & 1 ? p[n++] : 0;
        c[1] = m & 2 ? p[n++] : KS_NONE;
        c[2] = m & 4 ? p[n++] : KS_NONE;
        if (m & 8) {
            c[3] = p[n++];
            c[4] = p[n++];
        } else {
            c[3] = c[4] = 0;
        }
    }
    return n;
}

size_t ks_pack(const uint8_t *cells, unsigned rows, unsigned tracks, unsigned instruments,
               uint8_t *out, size_t cap) {
    size_t n = 0;
    for (unsigned i = 0; i < rows * tracks; i++) {
        const uint8_t *c = cells + i * KS_CELL_BYTES;
        if (c[0] > KS_NOTE_OFF || (c[1] != KS_NONE && c[1] >= instruments) ||
            (c[2] != KS_NONE && c[2] > 15) || c[3] > 15 || !(KS_FX_VALID >> c[3] & 1u) ||
            (c[3] == KS_FX_SPEED && c[4] == 0))
            return 0;
        // Arpeggio 00 is "no effect", as in the trackers this follows.
        uint8_t m = (uint8_t)((c[0] ? 1 : 0) | (c[1] != KS_NONE ? 2 : 0) | (c[2] != KS_NONE ? 4 : 0) |
                              (c[3] || c[4] ? 8 : 0));
        size_t need = 1u + (m & 1) + (m >> 1 & 1) + (m >> 2 & 1) + 2u * (m >> 3 & 1);
        if (cap - n < need) return 0;
        out[n++] = m;
        if (m & 1) out[n++] = c[0];
        if (m & 2) out[n++] = c[1];
        if (m & 4) out[n++] = c[2];
        if (m & 8) {
            out[n++] = c[3];
            out[n++] = c[4];
        }
    }
    return n;
}

size_t ks_unpack(const uint8_t *p, size_t avail, unsigned rows, unsigned tracks, unsigned instruments,
                 uint8_t *cells) {
    if (tracks < 1 || tracks > KS_TRACKS) return 0;
    size_t n = 0;
    for (unsigned r = 0; r < rows; r++) {
        size_t used = check_row(p + n, avail - n, tracks, instruments);
        if (!used) return 0;
        ks_unpack_row(p + n, tracks, cells + (size_t)r * tracks * KS_CELL_BYTES);
        n += used;
    }
    return n;
}
