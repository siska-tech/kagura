// SPDX-License-Identifier: Apache-2.0
// ABI 0.4 PSRAM and PCM checks for a spipsram/qspipsram bitstream (CAPS b3).
//   psram: random upload to the PSRAM region, FENCE, byte readback compare.
//   pcm:   a 2-second looping melody on PCM 0 and a drum one-shot on PCM 1
//          retriggered every 0.5 s with PREPARE + AUDIO_COMMIT, while the
//          status of both channels is watched for UNDERRUN and errors.
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pcm_demo.h"

#define MELODY_ADDR 0x400000u
#define MELODY_BYTES 96000u     // 2 s at 48 kHz
#define DRUM_ADDR 0x480000u
#define DRUM_BYTES 7200u        // 150 ms

static uint8_t chunk[2048], back[2048];
static uint32_t rng = 0x2468ace1u;
static uint32_t next_rng(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }

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

// Melody: eight 250 ms notes, a decaying square-ish tone with a 2nd harmonic.
static int8_t melody_sample(uint32_t n) {
    static const float notes[8] = {523.25f, 659.25f, 783.99f, 1046.5f, 783.99f, 659.25f, 587.33f, 392.0f};
    uint32_t note = n / 12000u, t = n % 12000u;
    float f = notes[note & 7u], x = (float)t / 48000.0f;
    float env = expf(-x * 6.0f) * (t < 96u ? (float)t / 96.0f : 1.0f);
    float w = sinf(6.2831853f * f * x) + 0.35f * sinf(12.566371f * f * x);
    int v = (int)(env * w * 90.0f);
    return (int8_t)(v > 127 ? 127 : v < -127 ? -127 : v);
}

static int8_t drum_sample(uint32_t n) {
    float x = (float)n / 48000.0f;
    float tone = sinf(6.2831853f * (160.0f - 600.0f * x) * x) * expf(-x * 25.0f);
    float noise = ((int)(next_rng() & 0xffu) - 128) / 128.0f * expf(-x * 60.0f);
    int v = (int)((tone * 0.8f + noise * 0.35f) * 120.0f);
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

kh_status kagura_pcm_demo(uint32_t seconds) {
    if (!have_psram()) return KH_BAD_ARGUMENT;
    uint8_t st0 = 0, st1 = 0;
    uint64_t t0 = time_us_64();
    kh_status s = kh_clear_errors();
    if (s == KH_OK) s = pcm_reg(0, KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_STOP | KAGURA_AUDIO_PCM_CMD_CLEAR);
    if (s == KH_OK) s = pcm_reg(1, KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_STOP | KAGURA_AUDIO_PCM_CMD_CLEAR);
    if (s == KH_OK) s = upload_generated(MELODY_ADDR, MELODY_BYTES, melody_sample);
    if (s == KH_OK) s = upload_generated(DRUM_ADDR, DRUM_BYTES, drum_sample);
    if (s == KH_OK) s = kh_fence(0x41, 500000);
    uint64_t t1 = time_us_64();
    if (s != KH_OK) { printf("FAIL pcm upload: %d ERROR_CODE 0x%02x\n", s, kh_last_error()); return s; }
    printf("uploaded %u + %u bytes in %llu us (%.1f KB/s)\n", MELODY_BYTES, DRUM_BYTES,
           (unsigned long long)(t1 - t0), (MELODY_BYTES + DRUM_BYTES) * 1000.0 / (double)(t1 - t0));
    // Spot-check the upload through READ_REQUEST before playing it.
    s = kh_vram_read(MELODY_ADDR + 12345u, back, 64);
    for (uint32_t i = 0; s == KH_OK && i < 64; i++)
        if (back[i] != (uint8_t)melody_sample(12345u + i)) { printf("FAIL pcm readback at +%lu\n", (unsigned long)(12345u + i)); return KH_DEVICE_ERROR; }

    s = pcm_range(0, MELODY_ADDR, MELODY_ADDR + MELODY_BYTES, MELODY_ADDR, true);
    if (s == KH_OK) s = pcm_range(1, DRUM_ADDR, DRUM_ADDR + DRUM_BYTES, DRUM_ADDR, false);
    if (s == KH_OK) s = pcm_prepare(0, &st0);
    if (s == KH_OK) s = pcm_prepare(1, &st1);
    if (s == KH_OK) s = pcm_reg(0, KAGURA_AUDIO_PCM_GAIN_L, 150);
    if (s == KH_OK) s = pcm_reg(0, KAGURA_AUDIO_PCM_GAIN_R, 110);
    if (s == KH_OK) s = pcm_reg(1, KAGURA_AUDIO_PCM_GAIN_L, 140);
    if (s == KH_OK) s = pcm_reg(1, KAGURA_AUDIO_PCM_GAIN_R, 200);
    if (s == KH_OK) s = pcm_reg(0, KAGURA_AUDIO_PCM_CONTROL, KAGURA_AUDIO_PCM_CONTROL_ENABLE | KAGURA_AUDIO_PCM_CONTROL_LOOP_ENABLE);
    if (s == KH_OK) s = pcm_reg(1, KAGURA_AUDIO_PCM_CONTROL, KAGURA_AUDIO_PCM_CONTROL_ENABLE);
    if (s == KH_OK) s = kh_audio_commit(100000);
    if (s != KH_OK) { printf("FAIL pcm start: %d ERROR_CODE 0x%02x status %02x %02x\n", s, kh_last_error(), st0, st1); return s; }

    unsigned hits = 1, faults = 0, inactive = 0, polls = 0;
    uint64_t end = time_us_64() + (uint64_t)(seconds ? seconds : 3600u) * 1000000u, next_hit = time_us_64() + 500000u;
    printf("playing: melody loop on PCM 0, drum on PCM 1 every 0.5 s%s\n", seconds ? "" : " (any key stops)");
    while (s == KH_OK && time_us_64() < end) {
        if (!seconds && getchar_timeout_us(0) != PICO_ERROR_TIMEOUT) break;
        s = pcm_status(0, &st0);
        if (s == KH_OK) s = pcm_status(1, &st1);
        polls++;
        const uint8_t bad = KAGURA_AUDIO_PCM_STATUS_UNDERRUN | KAGURA_AUDIO_PCM_STATUS_CONFIG_ERROR | KAGURA_AUDIO_PCM_STATUS_MEMORY_ERROR;
        if ((st0 | st1) & bad) { faults++; printf("  fault: status %02x %02x\n", st0, st1); break; }
        if (!(st0 & KAGURA_AUDIO_PCM_STATUS_ACTIVE)) inactive++;
        if (s == KH_OK && time_us_64() >= next_hit) {
            next_hit += 500000u;
            s = pcm_prepare(1, &st1);           // the finished one-shot replays from START
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
    printf("%s pcm: %u drum hits, %u status polls, %u faults, melody inactive %u, ERROR_CODE 0x%02x%s\n",
           ok ? "PASS" : "FAIL", hits, polls, faults, inactive, err, s == KH_OK ? "" : " (driver error)");
    return ok ? KH_OK : (s != KH_OK ? s : KH_DEVICE_ERROR);
}
