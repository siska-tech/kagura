// SPDX-License-Identifier: Apache-2.0
// KSNG, the native song format (software/audio/README.md#song-format-ksng-v1).
// ks_song_parse() checks a whole file before anything uses it: after it
// returns KS_OK, playback reads the buffer without further bounds checks.
// The song points into the caller's buffer, which must stay unchanged and
// alive while the song is used. Nothing is allocated.
#ifndef KS_SONG_H
#define KS_SONG_H

#include <stddef.h>
#include <stdint.h>

#define KS_MAGIC "KSNG"
#define KS_VERSION 1
#define KS_HEADER 48
#define KS_TRACKS 6
#define KS_INSTRUMENTS 32
#define KS_WAVES 16
#define KS_PATTERNS 64
#define KS_ORDERS 128
#define KS_MAX_BYTES 65535u
#define KS_INSTRUMENT_BYTES 8
#define KS_CELL_BYTES 5                // unpacked cell: note, inst, vol, fx, param

#define KS_FLAG_LOOP 1u
#define KS_NOTE_OFF 97                 // notes 1..96: C-0..B-7 (MIDI 12..107)
#define KS_NONE 0xFF                   // unpacked cell: no instrument / no volume
#define KS_MIN_TEMPO 32
#define KS_MAX_SPEED 31

enum { KS_KIND_PULSE = 0, KS_KIND_WAVE = 1, KS_KIND_NOISE = 2 };

// Effects (cell fx nibble); any other value is invalid.
enum {
    KS_FX_ARPEGGIO = 0x0, KS_FX_SLIDE_UP = 0x1, KS_FX_SLIDE_DOWN = 0x2, KS_FX_PORTA = 0x3,
    KS_FX_VIBRATO = 0x4, KS_FX_DUTY = 0x7, KS_FX_PAN = 0x8, KS_FX_VOLSLIDE = 0xA,
    KS_FX_JUMP = 0xB, KS_FX_CUT = 0xC, KS_FX_BREAK = 0xD, KS_FX_SPEED = 0xF,
};
#define KS_FX_VALID 0xBD9Fu            // bit per valid effect

enum {
    KS_OK = 0,
    KS_ESIZE = -1,      // shorter than its contents, longer than them, or over KS_MAX_BYTES
    KS_EMAGIC = -2,
    KS_EVERSION = -3,
    KS_EHEADER = -4,    // count, flag, speed, tempo or reserved byte out of range
    KS_ETEXT = -5,      // title or author not printable ASCII
    KS_ETRACKS = -6,    // voice out of range or used twice
    KS_EORDER = -7,
    KS_EINSTRUMENT = -8,
    KS_EWAVE = -9,
    KS_EPATTERN = -10,  // row count, packed size or cell field out of range
};

typedef struct {
    uint8_t kind, data, volume, pan, attack, decay, sustain, release;
} ks_instrument;

typedef struct {
    const uint8_t *base;
    size_t size;
    uint8_t flags, tracks, instruments, waves, patterns, orders, loop_order, speed, tempo;
    uint8_t voice[KS_TRACKS];          // hardware voice of each track
    const uint8_t *order;              // orders entries, each < patterns
    const uint8_t *instrument;         // instruments x 8 bytes
    const uint8_t *wave[KS_WAVES];     // samples of each wave
    uint16_t wave_len[KS_WAVES];
    const uint8_t *pattern[KS_PATTERNS];   // packed rows
    uint8_t rows[KS_PATTERNS];
} ks_song;

int ks_song_parse(ks_song *s, const uint8_t *data, size_t size);
const char *ks_strerror(int err);
void ks_song_instrument(const ks_song *s, unsigned i, ks_instrument *out);

// Packed rows: one cell per track, a mask byte (b0 note, b1 instrument,
// b2 volume, b3 effect+parameter) and the present fields in that order.
// Unpacks one row of a validated pattern into tracks x KS_CELL_BYTES and
// returns the packed bytes consumed.
size_t ks_unpack_row(const uint8_t *packed, unsigned tracks, uint8_t *cells);
// Checked: unpacks rows of packed data of avail bytes, each cell validated as
// ks_song_parse does; returns bytes consumed, or 0 if the data is invalid or
// shorter than the rows (cells is then undefined).
size_t ks_unpack(const uint8_t *packed, size_t avail, unsigned rows, unsigned tracks, unsigned instruments,
                 uint8_t *cells);
// Packs rows x tracks unpacked cells; returns the packed size, or 0 if out is
// too small or a cell is invalid (out is then undefined).
size_t ks_pack(const uint8_t *cells, unsigned rows, unsigned tracks, unsigned instruments,
               uint8_t *out, size_t cap);

#endif
