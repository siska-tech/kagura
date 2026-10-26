// SPDX-License-Identifier: Apache-2.0
// ABI 0.4 PSRAM and PCM checks for a spipsram/qspipsram bitstream (CAPS b3).
//   psram: random upload to the PSRAM region, FENCE, byte readback compare.
//   pcm:   a 2-second looping melody on PCM 0 and a recorded piano one-shot
//          on PCM 1, retriggered every 2 s with PREPARE + AUDIO_COMMIT, while the
//          status of both channels is watched for UNDERRUN and errors.
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pcm_demo.h"
#include "piano_c4_sample.h"

#define LOW_ADDR 0x400000u      // melody, or the note with PCM_DEMO_MOVE
#define HIGH_ADDR 0x480000u
#define MELODY_BYTES 96000u     // 2 s at 48 kHz
#define NOTE_BYTES PIANO_C4_SAMPLE_COUNT

static uint8_t chunk[2048], back[2048];
static uint32_t rng = 0x2468ace1u;
static uint32_t next_rng_state(uint32_t *state) {
    *state ^= *state << 13;
    *state ^= *state >> 17;
    *state ^= *state << 5;
    return *state;
}
static uint32_t next_rng(void) { return next_rng_state(&rng); }

static kh_status pcm_reg(unsigned p, uint8_t off, uint8_t value) {
    return kh_audio_write((uint8_t)KAGURA_AUDIO_PCM_INDEX(p, off), value);
}

static kh_status pcm_status(unsigned p, uint8_t *st) {
    return kh_audio_read((uint8_t)KAGURA_AUDIO_PCM_INDEX(p, KAGURA_AUDIO_PCM_STATUS), st);
}

static kh_status pcm_range(unsigned p, uint32_t start, uint32_t end, uint32_t loop, bool loop_enable) {
    const uint32_t v[3] = {start, end, loop};
    const uint8_t base[3] = {KAGURA_AUDIO_PCM_START_L, KAGURA_AUDIO_PCM_END_L, KAGURA_AUDIO_PCM_LOOP_L};
    kh_status s = KH_OK;
    for (int r = 0; r < 3; r++)
        for (int b = 0; b < 3 && s == KH_OK; b++) s = pcm_reg(p, (uint8_t)(base[r] + b), (uint8_t)(v[r] >> (8 * b)));
    if (s == KH_OK) s = pcm_reg(p, KAGURA_AUDIO_PCM_CONTROL, loop_enable ? KAGURA_AUDIO_PCM_CONTROL_LOOP_ENABLE : 0);
    return s;
}

// PREPARE and wait for READY; anything but PREPARING/READY is an error.
static kh_status pcm_prepare(unsigned p, uint8_t *st) {
    kh_status s = pcm_reg(p, KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_PREPARE);
    absolute_time_t end = make_timeout_time_us(100000);
    while (s == KH_OK) {
        s = pcm_status(p, st);
        if (s != KH_OK || (*st & KAGURA_AUDIO_PCM_STATUS_READY)) break;
        if (*st & (KAGURA_AUDIO_PCM_STATUS_CONFIG_ERROR | KAGURA_AUDIO_PCM_STATUS_MEMORY_ERROR)) return KH_DEVICE_ERROR;
        if (time_reached(end)) s = KH_TIMEOUT_STATUS;
    }
    return s;
}

static bool have_psram(void) {
    uint8_t caps = 0, size = 0, channels = 0;
    if (kh_read_reg(KAGURA_REG_CAPS, &caps) != KH_OK || !(caps & KAGURA_CAPS_PSRAM)) {
        printf("FAIL psram: CAPS 0x%02x has no PSRAM (use a spipsram/qspipsram bitstream)\n", caps);
        return false;
    }
    kh_ext_read(KAGURA_EXT_PSRAM_SIZE_LOG2, &size);
    kh_ext_read(KAGURA_EXT_PCM_CHANNELS, &channels);
    printf("PSRAM 2^%u bytes at 0x%06x, %u PCM channels\n", size, (unsigned)KAGURA_VRAM_PSRAM_BASE, channels);
    return size == 22 && channels == 2;
}

kh_status kagura_psram_test(size_t len) {
    if (len == 0 || len > sizeof chunk) return KH_BAD_ARGUMENT;
    if (!have_psram()) return KH_BAD_ARGUMENT;
    uint32_t addr = KAGURA_VRAM_PSRAM_BASE + (next_rng() % (KAGURA_VRAM_PSRAM_SIZE - len));
    for (size_t i = 0; i < len; i++) chunk[i] = (uint8_t)next_rng();
    uint64_t t0 = time_us_64();
    kh_status s = kh_vram_write(addr, chunk, len);
    if (s == KH_OK) s = kh_fence(0x40, 200000);
    uint64_t t1 = time_us_64();
    if (s == KH_OK) s = kh_vram_read(addr, back, len);
    uint64_t t2 = time_us_64();
    if (s != KH_OK) { printf("FAIL psram: driver %d ERROR_CODE 0x%02x\n", s, kh_last_error()); return s; }
    size_t bad = 0, first = 0;
    for (size_t i = 0; i < len; i++) if (chunk[i] != back[i]) { if (!bad) first = i; bad++; }
    printf("%s psram: %u bytes at 0x%06lx, upload+FENCE %llu us (%.1f KB/s), readback %llu us, %u mismatches",
           bad ? "FAIL" : "PASS", (unsigned)len, (unsigned long)addr, (unsigned long long)(t1 - t0),
           (t1 - t0) ? len * 1000.0 / (double)(t1 - t0) : 0.0, (unsigned long long)(t2 - t1), (unsigned)bad);
    if (bad) printf(" (first at +%u: %02x read %02x)", (unsigned)first, chunk[first], back[first]);
    printf("\n");
    return bad ? KH_DEVICE_ERROR : KH_OK;
}

// COPY: random bytes to PSRAM, COPY into the pattern area, read back from VRAM;
// then time a full 32 KiB pattern-area COPY (content is not checked there).
kh_status kagura_copy_test(size_t len) {
    if (len == 0 || len > sizeof chunk) return KH_BAD_ARGUMENT;
    if (!have_psram()) return KH_BAD_ARGUMENT;
    uint32_t src = KAGURA_VRAM_PSRAM_BASE + 0x100000u + (next_rng() & 0xfffu);
    uint32_t dst = KAGURA_VRAM_PATTERN_BASE + (next_rng() % (KAGURA_VRAM_PATTERN_SIZE - len));
    for (size_t i = 0; i < len; i++) chunk[i] = (uint8_t)next_rng();
    kh_status s = kh_vram_write(src, chunk, len);
    if (s == KH_OK) s = kh_fence(0x42, 200000);
    uint64_t t0 = time_us_64();
    if (s == KH_OK) s = kh_copy(src, dst, (uint16_t)len);
    if (s == KH_OK) s = kh_fence(0x43, 200000);
    uint64_t t1 = time_us_64();
    if (s == KH_OK) s = kh_vram_read(dst, back, len);
    if (s != KH_OK) { printf("FAIL copy: driver %d ERROR_CODE 0x%02x\n", s, kh_last_error()); return s; }
    size_t bad = 0;
    for (size_t i = 0; i < len; i++) if (chunk[i] != back[i]) bad++;
    uint64_t t2 = time_us_64();
    s = kh_copy(KAGURA_VRAM_PSRAM_BASE, KAGURA_VRAM_PATTERN_BASE, (uint16_t)(KAGURA_VRAM_PATTERN_SIZE - 1u));
    if (s == KH_OK) s = kh_fence(0x44, 500000);
    uint64_t t3 = time_us_64();
    printf("%s copy: %u bytes 0x%06lx -> 0x%06lx in %llu us incl. FENCE, %u mismatches; 32767 bytes in %llu us (%.1f KB/s)%s\n",
           bad || s != KH_OK ? "FAIL" : "PASS", (unsigned)len, (unsigned long)src, (unsigned long)dst,
           (unsigned long long)(t1 - t0), (unsigned)bad, (unsigned long long)(t3 - t2),
           (t3 - t2) ? 32767 * 1000.0 / (double)(t3 - t2) : 0.0, s == KH_OK ? "" : " (driver error)");
    return bad ? KH_DEVICE_ERROR : s;
}

// Debug bitstreams only (KAGURA_PSRAM_DEBUG): capture the PSRAM pins of one
// write (or read) at 0x500000 and print 48 cycles: DQ rise, DQ fall, flags
// {cs_n, ck_en, dq_tx, rwds_tx, dq_oe, rwds_oe, rwds rise, rwds fall}.
kh_status kagura_psram_debug(bool on_read, uint8_t value) {
    kh_status s = kh_ext_write(0x18, on_read ? 1u : 0u);
    uint8_t v = 0;
    if (s == KH_OK) s = on_read ? kh_vram_read(0x500000u, &v, 1) : kh_vram_write(0x500000u, &value, 1);
    if (s == KH_OK) s = kh_fence(0x45, 200000);
    if (s != KH_OK) { printf("ERR pdbg %d 0x%02x\n", s, kh_last_error()); return s; }
    printf("PDBG %s 0x500000 %02x\n", on_read ? "read" : "write", on_read ? v : value);
    for (unsigned c = 0; c < 48 && s == KH_OK; c++) {
        uint8_t b[3] = {0};
        for (unsigned k = 0; k < 3 && s == KH_OK; k++) {
            s = kh_ext_write(0x17, (uint8_t)(4u * c + k));
            if (s == KH_OK) s = kh_ext_read(0x18, &b[k]);
        }
        printf("%2u %02x %02x cs%u ck%u tx%u%u oe%u%u rwds%u%u\n", c, b[0], b[1], b[2] >> 7, (b[2] >> 6) & 1u,
               (b[2] >> 5) & 1u, (b[2] >> 4) & 1u, (b[2] >> 3) & 1u, (b[2] >> 2) & 1u, (b[2] >> 1) & 1u, b[2] & 1u);
    }
    printf("PDBG END\n");
    return s;
}

// Eight 250 ms notes forming a two-second looping phrase.
static int8_t melody_sample(uint32_t n) {
    static const float notes[8] = {523.25f, 659.25f, 783.99f, 1046.5f, 783.99f, 659.25f, 587.33f, 392.0f};
    uint32_t note = n / 12000u, t = n % 12000u;
    float f = notes[note & 7u], x = (float)t / 48000.0f;
    float env = expf(-x * 6.0f) * (t < 96u ? (float)t / 96.0f : 1.0f);
    float w = sinf(6.2831853f * f * x) + 0.35f * sinf(12.566371f * f * x);
    int v = (int)(env * w * 90.0f);
    return (int8_t)(v > 127 ? 127 : v < -127 ? -127 : v);
}

static kh_status upload_generated(uint32_t addr, uint32_t bytes, int8_t (*gen)(uint32_t)) {
    kh_status s = KH_OK;
    for (uint32_t off = 0; off < bytes && s == KH_OK; off += sizeof chunk) {
        uint32_t n = bytes - off < sizeof chunk ? bytes - off : sizeof chunk;
        for (uint32_t i = 0; i < n; i++) chunk[i] = (uint8_t)gen(off + i);
        s = kh_vram_write(addr + off, chunk, n);
    }
    return s;
}

static int8_t zero_sample(uint32_t n) { (void)n; return 0; }

static kh_status upload_bytes(uint32_t addr, const int8_t *data, uint32_t bytes) {
    kh_status s = KH_OK;
    for (uint32_t off = 0; off < bytes && s == KH_OK; off += sizeof chunk) {
        uint32_t n = bytes - off < sizeof chunk ? bytes - off : sizeof chunk;
        s = kh_vram_write(addr + off, (const uint8_t *)data + off, n);
    }
    return s;
}

kh_status kagura_pcm_demo(uint32_t seconds, unsigned flags, int master) {
    if (!have_psram()) return KH_BAD_ARGUMENT;
    // MOVE exchanges the two PSRAM locations, to tell an address-dependent
    // read fault from a property of the sample; SOLO leaves the melody off.
    // NONOTE never starts the note channel; ZERO plays silence in its place.
    const bool solo = flags & PCM_DEMO_SOLO, nonote = flags & PCM_DEMO_NONOTE, zero = flags & PCM_DEMO_ZERO;
    const uint32_t MELODY_ADDR = flags & PCM_DEMO_MOVE ? HIGH_ADDR : LOW_ADDR;
    const uint32_t NOTE_ADDR = flags & PCM_DEMO_MOVE ? LOW_ADDR : HIGH_ADDR;
    uint8_t st0 = 0, st1 = 0;
    uint64_t t0 = time_us_64();
    kh_status s = kh_clear_errors();
    if (s == KH_OK) s = pcm_reg(0, KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_STOP | KAGURA_AUDIO_PCM_CMD_CLEAR);
    if (s == KH_OK) s = pcm_reg(1, KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_STOP | KAGURA_AUDIO_PCM_CMD_CLEAR);
    if (s == KH_OK) s = upload_generated(MELODY_ADDR, MELODY_BYTES, melody_sample);
    if (s == KH_OK) s = zero ? upload_generated(NOTE_ADDR, NOTE_BYTES, zero_sample) : upload_bytes(NOTE_ADDR, piano_c4_sample, NOTE_BYTES);
    if (s == KH_OK) s = kh_fence(0x41, 500000);
    uint64_t t1 = time_us_64();
    if (s != KH_OK) { printf("FAIL pcm upload: %d ERROR_CODE 0x%02x\n", s, kh_last_error()); return s; }
    printf("uploaded %u + %u bytes in %llu us (%.1f KB/s)\n", MELODY_BYTES, NOTE_BYTES,
           (unsigned long long)(t1 - t0), (MELODY_BYTES + NOTE_BYTES) * 1000.0 / (double)(t1 - t0));
    // Spot-check the upload through READ_REQUEST before playing it.
    s = kh_vram_read(MELODY_ADDR + 12345u, back, 64);
    for (uint32_t i = 0; s == KH_OK && i < 64; i++)
        if (back[i] != (uint8_t)melody_sample(12345u + i)) { printf("FAIL pcm readback at +%lu\n", (unsigned long)(12345u + i)); return KH_DEVICE_ERROR; }
    // The recorded note is compared in full: a corrupted upload sounds like distortion.
    uint32_t mismatches = 0, first_bad = 0;
    uint8_t first_got = 0;
    for (uint32_t off = 0; s == KH_OK && off < NOTE_BYTES; off += sizeof back) {
        uint32_t n = NOTE_BYTES - off < sizeof back ? NOTE_BYTES - off : sizeof back;
        s = kh_vram_read(NOTE_ADDR + off, back, n);
        for (uint32_t i = 0; s == KH_OK && i < n; i++)
            if (back[i] != (zero ? 0u : (uint8_t)piano_c4_sample[off + i]) && !mismatches++) { first_bad = off + i; first_got = back[i]; }
    }
    if (s != KH_OK) { printf("FAIL piano readback: %d ERROR_CODE 0x%02x\n", s, kh_last_error()); return s; }
    if (mismatches) {
        printf("FAIL piano readback: %lu/%u bytes differ, first at +%lu (got %02x expected %02x)\n",
               (unsigned long)mismatches, NOTE_BYTES, (unsigned long)first_bad,
               first_got, zero ? 0u : (unsigned)(uint8_t)piano_c4_sample[first_bad]);
        return KH_DEVICE_ERROR;
    }
    printf("piano readback: %u bytes match\n", NOTE_BYTES);

    // swap puts the note on PCM 0 and the melody on PCM 1, to tell a channel
    // fault from a property of the sample.
    const unsigned mel = flags & PCM_DEMO_SWAP ? 1u : 0u, note = 1u - mel;
    uint8_t *st_mel = mel ? &st1 : &st0, *st_note = note ? &st1 : &st0;
    s = pcm_range(mel, MELODY_ADDR, MELODY_ADDR + MELODY_BYTES, MELODY_ADDR, true);
    if (s == KH_OK) s = pcm_range(note, NOTE_ADDR, NOTE_ADDR + NOTE_BYTES, NOTE_ADDR, false);
    if (s == KH_OK) s = pcm_prepare(mel, st_mel);
    if (s == KH_OK) s = pcm_prepare(note, st_note);
    const bool mute = flags & PCM_DEMO_MUTE;
    if (s == KH_OK) s = pcm_reg(mel, KAGURA_AUDIO_PCM_GAIN_L, mute ? 0 : 150);
    if (s == KH_OK) s = pcm_reg(mel, KAGURA_AUDIO_PCM_GAIN_R, mute ? 0 : 110);
    const bool mute_note = flags & PCM_DEMO_MUTE_NOTE;
    if (s == KH_OK) s = pcm_reg(note, KAGURA_AUDIO_PCM_GAIN_L, mute_note ? 0 : 128);
    if (s == KH_OK) s = pcm_reg(note, KAGURA_AUDIO_PCM_GAIN_R, mute_note ? 0 : 128);
    if (s == KH_OK) s = pcm_reg(mel, KAGURA_AUDIO_PCM_CONTROL, (solo ? 0 : KAGURA_AUDIO_PCM_CONTROL_ENABLE) | KAGURA_AUDIO_PCM_CONTROL_LOOP_ENABLE);
    if (s == KH_OK) s = pcm_reg(note, KAGURA_AUDIO_PCM_CONTROL, nonote ? 0 : KAGURA_AUDIO_PCM_CONTROL_ENABLE);
    if (s == KH_OK && master >= 0) s = kh_audio_write(KAGURA_AUDIO_MASTER_GAIN, (uint8_t)master);
    uint8_t master_now = 0;
    if (s == KH_OK) s = kh_audio_read(KAGURA_AUDIO_MASTER_GAIN, &master_now);
    if (s == KH_OK) printf("MASTER_GAIN %u\n", master_now);
    if (s == KH_OK) s = kh_audio_commit(100000);
    if (s != KH_OK) { printf("FAIL pcm start: %d ERROR_CODE 0x%02x status %02x %02x\n", s, kh_last_error(), st0, st1); return s; }

    unsigned hits = 1, faults = 0, inactive = 0, polls = 0;
    uint64_t end = time_us_64() + (uint64_t)(seconds ? seconds : 3600u) * 1000000u, next_hit = time_us_64() + 2000000u;
    printf("playing: melody loop on PCM %u at 0x%06lx%s, %s on PCM %u at 0x%06lx%s every 2 s%s\n",
           mel, (unsigned long)MELODY_ADDR, solo ? " (off)" : mute ? " (gain 0)" : "",
           zero ? "silence" : "recorded piano C4", note, (unsigned long)NOTE_ADDR,
           nonote ? " (off)" : mute_note ? " (gain 0)" : "", seconds ? "" : " (any key stops)");
    while (s == KH_OK && time_us_64() < end) {
        if (!seconds && getchar_timeout_us(0) != PICO_ERROR_TIMEOUT) break;
        s = pcm_status(0, &st0);
        if (s == KH_OK) s = pcm_status(1, &st1);
        polls++;
        const uint8_t bad = KAGURA_AUDIO_PCM_STATUS_UNDERRUN | KAGURA_AUDIO_PCM_STATUS_CONFIG_ERROR | KAGURA_AUDIO_PCM_STATUS_MEMORY_ERROR;
        if ((st0 | st1) & bad) { faults++; printf("  fault: status %02x %02x\n", st0, st1); break; }
        if (!solo && !(*st_mel & KAGURA_AUDIO_PCM_STATUS_ACTIVE)) inactive++;
        if (s == KH_OK && !nonote && time_us_64() >= next_hit) {
            next_hit += 2000000u;
            s = pcm_prepare(note, st_note);     // the finished one-shot replays from START
            if (s == KH_OK) s = kh_audio_commit(100000);
            if (s == KH_OK) hits++;
        }
    }
    uint8_t err = 0;
    kh_read_reg(KAGURA_REG_ERROR_CODE, &err);
    pcm_reg(0, KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_STOP);
    pcm_reg(1, KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_STOP);
    pcm_reg(0, KAGURA_AUDIO_PCM_CONTROL, 0);
    pcm_reg(1, KAGURA_AUDIO_PCM_CONTROL, 0);
    kh_audio_commit(100000);
    bool ok = s == KH_OK && !faults && !inactive && !err;
    printf("%s pcm: %u piano notes, %u status polls, %u faults, melody inactive %u, ERROR_CODE 0x%02x%s\n",
           ok ? "PASS" : "FAIL", hits, polls, faults, inactive, err, s == KH_OK ? "" : " (driver error)");
    return ok ? KH_OK : (s != KH_OK ? s : KH_DEVICE_ERROR);
}
