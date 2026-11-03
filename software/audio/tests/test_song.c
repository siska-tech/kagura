// SPDX-License-Identifier: Apache-2.0
// KSNG parser: a valid song, each kind of malformed file, every truncation,
// random corruption (no crash; run under ASan/UBSan) and pack/unpack.
#include <stdlib.h>
#include "ka_test.h"
#include "ks_song.h"

static uint8_t buf[KS_MAX_BYTES + 16];
static kb_song b;

static size_t sample(void) {
    kb_init(&b, 4, 16);
    b.instruments = 3;
    const uint8_t wave_in[8] = {KS_KIND_WAVE, 0, 12, 100, 2, 4, 8, 6};
    const uint8_t noise_in[8] = {KS_KIND_NOISE, 0, 10, 128, 0, 3, 0, 0};
    memcpy(b.instrument[1], wave_in, 8);
    memcpy(b.instrument[2], noise_in, 8);
    b.waves = 1;
    b.wave_log2[0] = 5;
    for (unsigned i = 0; i < 32; i++) b.wave[0][i] = (uint8_t)(i < 16 ? i * 8 : 255 - i * 8);
    b.voice[0] = 0;
    b.voice[1] = 4;
    b.voice[2] = 3;
    b.voice[3] = 1;
    b.patterns = 2;
    b.orders = 3;
    b.order[0] = 0;
    b.order[1] = 1;
    b.order[2] = 0;
    b.rows[1] = 32;
    kb_note(&b, 0, 0, 0, 49, 0);
    kb_note(&b, 0, 0, 1, 37, 1);
    kb_note(&b, 0, 4, 2, 60, 2);
    kb_cell(&b, 0, 8, 0)[0] = KS_NOTE_OFF;
    kb_cell(&b, 0, 9, 3)[2] = 7;
    kb_fx(&b, 1, 0, 0, KS_FX_SPEED, 150);
    kb_fx(&b, 1, 31, 3, KS_FX_JUMP, 2);
    return kb_build(&b, buf, sizeof buf);
}

static void test_valid(void) {
    size_t n = sample();
    CHECK(n > KS_HEADER);
    ks_song s;
    CHECK_EQ(ks_song_parse(&s, buf, n), KS_OK);
    CHECK_EQ(s.tracks, 4);
    CHECK_EQ(s.voice[1], 4);
    CHECK_EQ(s.patterns, 2);
    CHECK_EQ(s.rows[1], 32);
    CHECK_EQ(s.wave_len[0], 32);
    CHECK_EQ(s.tempo, 125);
    ks_instrument in;
    ks_song_instrument(&s, 1, &in);
    CHECK_EQ(in.kind, KS_KIND_WAVE);
    CHECK_EQ(in.release, 6);
    // Packed rows give back the cells.
    uint8_t cells[KS_TRACKS * KS_CELL_BYTES];
    const uint8_t *q = s.pattern[0];
    for (unsigned r = 0; r < 16; r++) {
        q += ks_unpack_row(q, s.tracks, cells);
        CHECK(!memcmp(cells, kb_cell(&b, 0, r, 0), 4 * KS_CELL_BYTES));
    }
    CHECK_EQ(q - s.pattern[0], s.pattern[1] - 3 - s.pattern[0]);
}

typedef struct {
    size_t at;
    uint8_t value;
    int err;
} corruption;

static void test_each_malformation(void) {
    size_t n = sample();
    size_t tracks = KS_HEADER, orders = tracks + 4, inst = orders + 3, waves = inst + 3 * 8;
    size_t pat = waves + 1 + 32;
    const corruption cases[] = {
        {0, 'X', KS_EMAGIC}, {4, 2, KS_EVERSION}, {5, 2, KS_EHEADER}, {6, 0, KS_EHEADER},
        {6, 7, KS_EHEADER}, {7, 0, KS_EHEADER}, {7, 33, KS_EHEADER}, {8, 17, KS_EHEADER},
        {9, 0, KS_EHEADER}, {9, 65, KS_EHEADER}, {10, 0, KS_EHEADER}, {11, 3, KS_EHEADER},
        {12, 0, KS_EHEADER}, {12, 32, KS_EHEADER}, {13, 31, KS_EHEADER}, {14, 1, KS_EHEADER},
        {15, 1, KS_EHEADER}, {16, 0x7F, KS_ETEXT}, {17 + 9, 'A', KS_ETEXT}, {32, 0x10, KS_ETEXT},
        {tracks, 6, KS_ETRACKS}, {tracks + 1, 0, KS_ETRACKS}, {orders + 2, 2, KS_EORDER},
        {inst, 3, KS_EINSTRUMENT}, {inst + 2, 16, KS_EINSTRUMENT}, {inst + 6, 16, KS_EINSTRUMENT},
        {inst + 8 + 1, 1, KS_EINSTRUMENT}, {inst + 16 + 1, 1, KS_EINSTRUMENT},
        {waves, 4, KS_EWAVE}, {waves, 9, KS_EWAVE},
        {pat, 17, KS_EPATTERN}, {pat, 0, KS_EPATTERN},
        {pat + 1, 0, KS_EPATTERN},          // packed size too small for 16 rows
        {pat + 3, 0x10, KS_EPATTERN},       // mask with a reserved bit
        {pat + 4, 0, KS_EPATTERN},          // note 0 with the note bit
        {pat + 4, 98, KS_EPATTERN},         // note past note-off
        {pat + 5, 3, KS_EPATTERN},          // instrument past the count
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        sample();
        buf[cases[i].at] = cases[i].value;
        ks_song s;
        int err = ks_song_parse(&s, buf, n);
        if (err != cases[i].err) fprintf(stderr, "case %zu: offset %zu got %d\n", i, cases[i].at, err);
        CHECK_EQ(err, cases[i].err);
    }
}

static void test_effects_validated(void) {
    for (unsigned fx = 0; fx < 16; fx++) {
        sample();
        kb_fx(&b, 0, 3, 1, fx, 1);
        size_t n = kb_build(&b, buf, sizeof buf);
        bool valid = KS_FX_VALID >> fx & 1u;
        CHECK_EQ(n != 0, valid);            // the packer refuses invalid effects
        if (!valid) continue;
        ks_song s;
        CHECK_EQ(ks_song_parse(&s, buf, n), KS_OK);
    }
    sample();
    kb_fx(&b, 0, 3, 1, KS_FX_SPEED, 0);     // speed 0 would stop time
    CHECK_EQ(kb_build(&b, buf, sizeof buf), 0);
    // A hand-made invalid effect in the file is caught by the parser.
    size_t n = sample();
    size_t pat = KS_HEADER + 4 + 3 + 3 * 8 + 1 + 32 + 3;
    CHECK_EQ(buf[pat], 3);                  // row 0 track 0: note + instrument
    buf[pat] = 0x0B;                        // claim note + inst + effect: shifts the stream
    ks_song s;
    CHECK(ks_song_parse(&s, buf, n) != KS_OK);
}

static void test_invalid_effect_in_file(void) {
    // The packer refuses effect 5, so put it into the file by hand.
    kb_init(&b, 1, 16);
    kb_fx(&b, 0, 0, 0, KS_FX_SLIDE_UP, 1);
    size_t n = kb_build(&b, buf, sizeof buf);
    size_t cell = KS_HEADER + 1 + 1 + 8 + 3;
    CHECK_EQ(buf[cell], 8);
    CHECK_EQ(buf[cell + 1], KS_FX_SLIDE_UP);
    ks_song s;
    CHECK_EQ(ks_song_parse(&s, buf, n), KS_OK);
    for (unsigned fx = 0; fx < 256; fx++) {
        buf[cell + 1] = (uint8_t)fx;
        CHECK_EQ(ks_song_parse(&s, buf, n) == KS_OK, fx < 16 && (KS_FX_VALID >> fx & 1u));
    }
}

static void test_pattern_with_slack(void) {
    // A packed size larger than its rows need: the extra byte belongs to no row.
    kb_init(&b, 2, 16);
    size_t n = kb_build(&b, buf, sizeof buf);
    size_t pat = KS_HEADER + 2 + 1 + 8;
    unsigned size = buf[pat + 1] | buf[pat + 2] << 8;
    CHECK_EQ(pat + 3 + size, n);
    buf[pat + 1] = (uint8_t)(size + 1);
    buf[n] = 0;
    ks_song s;
    CHECK_EQ(ks_song_parse(&s, buf, n + 1), KS_EPATTERN);
}

static void test_every_truncation_and_extension(void) {
    size_t n = sample();
    ks_song s;
    for (size_t len = 0; len < n; len++) CHECK(ks_song_parse(&s, buf, len) != KS_OK);
    CHECK_EQ(ks_song_parse(&s, buf, n), KS_OK);
    buf[n] = 0;
    CHECK_EQ(ks_song_parse(&s, buf, n + 1), KS_ESIZE);
    CHECK_EQ(ks_song_parse(&s, buf, KS_MAX_BYTES + 1), KS_ESIZE);
}

static void test_random_corruption(void) {
    size_t n = sample();
    uint8_t good[4096];
    memcpy(good, buf, n);
    uint32_t seed = 99;
    unsigned accepted = 0;
    for (unsigned i = 0; i < 200000; i++) {
        memcpy(buf, good, n);
        unsigned flips = 1 + ka_rand(&seed) % 4;
        for (unsigned k = 0; k < flips; k++) buf[ka_rand(&seed) % n] = (uint8_t)ka_rand(&seed);
        size_t len = ka_rand(&seed) % 8 ? n : ka_rand(&seed) % (n + 8);
        ks_song s;
        if (ks_song_parse(&s, buf, len) != KS_OK) continue;
        accepted++;
        // Accepted: every row must unpack inside the file.
        uint8_t cells[KS_TRACKS * KS_CELL_BYTES];
        for (unsigned p = 0; p < s.patterns; p++) {
            const uint8_t *q = s.pattern[p];
            for (unsigned r = 0; r < s.rows[p]; r++) q += ks_unpack_row(q, s.tracks, cells);
            CHECK(q <= buf + len);
        }
        for (unsigned o = 0; o < s.orders; o++) CHECK(s.order[o] < s.patterns);
    }
    CHECK(accepted > 100);   // some flips land in harmless places (cell values, text)
}

static void test_checked_unpack(void) {
    sample();
    uint8_t packed[4096], cells[64 * KS_TRACKS * KS_CELL_BYTES];
    size_t n = ks_pack(b.cells[0], 16, 4, 3, packed, sizeof packed);
    CHECK_EQ(ks_unpack(packed, n, 16, 4, 3, cells), n);
    CHECK(!memcmp(cells, b.cells[0], 16 * 4 * KS_CELL_BYTES));
    for (size_t len = 0; len < n; len++) CHECK_EQ(ks_unpack(packed, len, 16, 4, 3, cells), 0);
    CHECK_EQ(ks_unpack(packed, n, 16, 4, 2, cells), 0);     // instrument 2 out of range
    CHECK_EQ(ks_unpack(packed, n, 16, 7, 3, cells), 0);
    uint32_t seed = 4;
    for (unsigned i = 0; i < 20000; i++) {
        uint8_t junk[64];
        for (unsigned k = 0; k < sizeof junk; k++) junk[k] = (uint8_t)ka_rand(&seed) % 12;
        size_t used = ks_unpack(junk, sizeof junk, 4, 2, 32, cells);
        CHECK(used <= sizeof junk);
    }
}

static void test_pack_bounds(void) {
    sample();
    uint8_t out[8];
    CHECK_EQ(ks_pack(b.cells[0], 16, 4, 3, out, sizeof out), 0);   // too small
    uint8_t big[4096];
    size_t n = ks_pack(b.cells[0], 16, 4, 3, big, sizeof big);
    CHECK(n >= 64);
    CHECK_EQ(ks_pack(b.cells[0], 16, 4, 3, big, n), n);           // exactly enough
    CHECK_EQ(ks_pack(b.cells[0], 16, 4, 3, big, n - 1), 0);
    CHECK_EQ(ks_pack(b.cells[0], 16, 4, 1, big, sizeof big), 0);  // instrument 1, 2 out of range
}

int main(void) {
    static const ka_case cases[] = {
        {"valid", test_valid},
        {"each_malformation", test_each_malformation},
        {"effects_validated", test_effects_validated},
        {"invalid_effect_in_file", test_invalid_effect_in_file},
        {"pattern_with_slack", test_pattern_with_slack},
        {"every_truncation_and_extension", test_every_truncation_and_extension},
        {"random_corruption", test_random_corruption},
        {"checked_unpack", test_checked_unpack},
        {"pack_bounds", test_pack_bounds},
    };
    return ka_run(cases, sizeof cases / sizeof cases[0], "song");
}
