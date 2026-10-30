// SPDX-License-Identifier: Apache-2.0
// C TileFramebuffer benchmark. The workloads repeat those of the MicroPython
// examples/framebuffer_benchmark.py (compare_draw, the 1/10/100/1200-tile
// flushes and the moving-window loop) so both SDKs can be compared on the
// same bitstream. CPU drawing, transfer and FENCE waits are timed apart.
// Every line starts with "FB "; the last is "FBBENCH PASS" or "FBBENCH FAIL n".
#include "fb_bench.h"

#include <math.h>
#include <stdio.h>
#include <string.h>
#include "hardware/clocks.h"
#include "hardware/structs/systick.h"
#include "pico/stdlib.h"
#include "tile_fb.h"

// tests/test_tile_fb.py checks this against the Python TileFramebuffer.
#define SCENE_CRC 0x7529d858u

tile_fb kagura_fb;
static uint8_t back[256];
static int failures;
static unsigned audio;   // FB_BENCH_PCM | FB_BENCH_PSG while playing

uint64_t tfb_now_us(void) { return time_us_64(); }

static uint32_t crc32(const uint8_t *p, size_t n) {
    uint32_t c = 0xffffffffu;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & -(c & 1u));
    }
    return ~c;
}

static bool ok(const char *step, kh_status s) {
    if (s == KH_OK) return true;
    printf("FB FAIL %s status=%d error=0x%02x\n", step, (int)s, kh_last_error());
    failures++;
    return false;
}

// Exact lifetime mean/min/max; p95 over the last <=256 samples, as the
// MicroPython Samples ring does.
typedef struct {
    uint32_t ring[256];
    uint32_t count, min, max;
    uint64_t total;
} samples;

static void samples_reset(samples *s) { memset(s, 0, sizeof *s); s->min = UINT32_MAX; }

static void samples_add(samples *s, uint32_t v) {
    s->ring[s->count % 256u] = v;
    s->count++;
    s->total += v;
    if (v < s->min) s->min = v;
    if (v > s->max) s->max = v;
}

static uint32_t samples_p95(const samples *s) {
    static uint32_t sorted[256];
    unsigned n = s->count < 256u ? s->count : 256u;
    memcpy(sorted, s->ring, n * sizeof sorted[0]);
    for (unsigned i = 1; i < n; i++)
        for (unsigned j = i; j && sorted[j - 1] > sorted[j]; j--) {
            uint32_t t = sorted[j]; sorted[j] = sorted[j - 1]; sorted[j - 1] = t;
        }
    return n ? sorted[(n * 95u + 99u) / 100u - 1u] : 0;
}

// unit_ns converts a sample to nanoseconds (1000 for us samples).
static void print_samples(const char *key, const samples *s, double unit_ns) {
    if (!s->count) { printf(" %s=none", key); return; }
    printf(" %s_mean_us=%.3f %s_min_us=%.3f %s_p95_us=%.3f %s_max_us=%.3f", key,
           (double)s->total / s->count * unit_ns / 1000.0, key, s->min * unit_ns / 1000.0,
           key, samples_p95(s) * unit_ns / 1000.0, key, s->max * unit_ns / 1000.0);
}

// SysTick counts CPU cycles (24 bit, ~139 ms at 120 MHz); drawing is timed
// with it for sub-microsecond resolution. Interrupts (USB) still count.
static void cycles_start(void) {
    systick_hw->csr = 0;
    systick_hw->rvr = 0x00ffffffu;
    systick_hw->cvr = 0;
    systick_hw->csr = 5u;   // enable, processor clock
}
static inline uint32_t cycles_now(void) { return systick_hw->cvr; }
static inline uint32_t cycles_since(uint32_t before) { return (before - systick_hw->cvr) & 0x00ffffffu; }

static kh_status palette_gray(void) {
    uint8_t words[32];
    for (unsigned n = 0; n < 16; n++) {
        uint16_t rgb = (uint16_t)(n * 0x111u);
        words[2 * n] = (uint8_t)rgb;
        words[2 * n + 1] = (uint8_t)(rgb >> 8);
    }
    return kh_vram_write(KAGURA_VRAM_PALETTE_BASE, words, sizeof words);
}

static kh_status audio_reg(unsigned index, uint8_t value) { return kh_audio_write((uint8_t)index, value); }

static kh_status audio_step(unsigned ch, float hz) {
    uint32_t step = (uint32_t)(hz * 16777216.0f / 48000.0f + 0.5f);
    kh_status s = KH_OK;
    for (unsigned b = 0; b < 3 && s == KH_OK; b++)
        s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_STEP_L + b), (uint8_t)(step >> (8 * b)));
    return s;
}

// framebuffer_diagnostic.Session.pcm_start(): MASTER_GAIN 64, a 128- and a
// 64-sample triangle (4096 B each) looping from PSRAM on PCM 0 (left 12) and
// PCM 1 (right 12).
static kh_status pcm_start(void) {
    static uint8_t cycle[4096];
    kh_status s = KH_OK;
    for (unsigned ch = 0; ch < 2 && s == KH_OK; ch++) {
        const uint32_t address = ch ? 0x410000u : 0x400000u, period = ch ? 64u : 128u, half = period / 2u;
        for (uint32_t i = 0; i < sizeof cycle; i++) {
            uint32_t p = i % period;
            cycle[i] = (uint8_t)((p < half ? p : period - 1u - p) * (256u / half) - 128u);
        }
        const unsigned base = KAGURA_AUDIO_PCM_INDEX(ch, 0);
        const uint32_t v[3] = {address, address + sizeof cycle, address};
        const uint8_t reg[3] = {KAGURA_AUDIO_PCM_START_L, KAGURA_AUDIO_PCM_END_L, KAGURA_AUDIO_PCM_LOOP_L};
        s = kh_vram_write(address, cycle, sizeof cycle);
        if (s == KH_OK) s = kh_fence(0x60u + ch, 200000);
        if (s == KH_OK) s = audio_reg(base + KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_CLEAR);
        for (unsigned r = 0; r < 3; r++)
            for (unsigned b = 0; b < 3 && s == KH_OK; b++) s = audio_reg(base + reg[r] + b, (uint8_t)(v[r] >> (8 * b)));
        if (s == KH_OK) s = audio_reg(base + KAGURA_AUDIO_PCM_CONTROL, KAGURA_AUDIO_PCM_CONTROL_LOOP_ENABLE);
        if (s == KH_OK) s = audio_reg(base + KAGURA_AUDIO_PCM_CMD, KAGURA_AUDIO_PCM_CMD_PREPARE);
        uint8_t st = 0;
        absolute_time_t end = make_timeout_time_us(100000);
        while (s == KH_OK && !(st & KAGURA_AUDIO_PCM_STATUS_READY)) {
            s = kh_audio_read((uint8_t)(base + KAGURA_AUDIO_PCM_STATUS), &st);
            if (st & (KAGURA_AUDIO_PCM_STATUS_UNDERRUN | KAGURA_AUDIO_PCM_STATUS_CONFIG_ERROR |
                      KAGURA_AUDIO_PCM_STATUS_MEMORY_ERROR)) s = KH_DEVICE_ERROR;
            else if (time_reached(end)) s = KH_TIMEOUT_STATUS;
        }
        if (s == KH_OK) s = audio_reg(base + KAGURA_AUDIO_PCM_GAIN_L, ch ? 0 : 12);
        if (s == KH_OK) s = audio_reg(base + KAGURA_AUDIO_PCM_GAIN_R, ch ? 12 : 0);
        if (s == KH_OK) s = audio_reg(base + KAGURA_AUDIO_PCM_CONTROL,
                                      KAGURA_AUDIO_PCM_CONTROL_LOOP_ENABLE | KAGURA_AUDIO_PCM_CONTROL_ENABLE);
        if (s == KH_OK) s = kh_audio_commit(100000);
    }
    return s;
}

// A held C major chord: pulse C4/E4/G4, wavetable C3/G3 (sine, written to
// both banks), quiet noise. Needs no host traffic once committed.
static kh_status psg_start(void) {
    static const float pulse[3] = {261.63f, 329.63f, 392.0f};
    uint8_t wave[512];
    for (unsigned i = 0; i < sizeof wave; i++) wave[i] = (uint8_t)(int8_t)(100.0f * sinf(6.2831853f * (float)(i & 255u) / 256.0f));
    kh_status s = KH_OK;
    for (unsigned ch = 0; ch < 3 && s == KH_OK; ch++) {
        s = audio_step(ch, pulse[ch]);
        if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_DUTY), 128);
        if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_GAIN_L), 16);
        if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_GAIN_R), 16);
    }
    if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(3, KAGURA_AUDIO_NOISE_PERIOD_L), 31);
    if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(3, KAGURA_AUDIO_NOISE_PERIOD_H), 0);
    if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(3, KAGURA_AUDIO_GAIN_L), 4);
    if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(3, KAGURA_AUDIO_GAIN_R), 4);
    for (unsigned ch = 4; ch < 6 && s == KH_OK; ch++) {
        s = audio_step(ch, ch == 4 ? 130.81f : 196.0f);
        if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_LEN_LOG2), 8);
        if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_GAIN_L), 24);
        if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_GAIN_R), 24);
    }
    for (unsigned ch = 0; ch < 6 && s == KH_OK; ch++)
        s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_CONTROL), KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET);
    // AUDIO_COMMIT swaps the wave banks: write, commit, write the other, commit.
    for (unsigned bank = 0; bank < 2 && s == KH_OK; bank++) {
        s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, wave, sizeof wave);
        if (s == KH_OK) s = kh_audio_commit(100000);
    }
    return s;
}

static kh_status audio_stop(void) {
    kh_status s = KH_OK;
    for (unsigned ch = 0; ch < KAGURA_AUDIO_CHANNELS && s == KH_OK; ch++)
        s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_CONTROL), 0);
    for (unsigned ch = 0; ch < 2 && s == KH_OK && (audio & FB_BENCH_PCM); ch++) {
        s = audio_reg(KAGURA_AUDIO_PCM_INDEX(ch, KAGURA_AUDIO_PCM_CONTROL), 0);
        if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_PCM_INDEX(ch, KAGURA_AUDIO_PCM_CMD), KAGURA_AUDIO_PCM_CMD_STOP);
    }
    if (s == KH_OK) s = kh_audio_commit(100000);
    audio = 0;
    return s;
}

// framebuffer_diagnostic.Session.telemetry(): ERROR_CODE, AUDIO_STATUS and,
// with PCM, both channel statuses. A fault is ERROR_CODE != 0, FIFO
// underflow/overflow, or a PCM channel with error bits or no longer ACTIVE.
typedef struct { uint8_t error, fifo, pcm[2]; } telemetry;

static kh_status read_telemetry(telemetry *t, bool *fault) {
    kh_status s = kh_read_reg(KAGURA_REG_ERROR_CODE, &t->error);
    if (s == KH_OK) s = kh_audio_read(KAGURA_AUDIO_STATUS, &t->fifo);
    t->pcm[0] = t->pcm[1] = 0;
    for (unsigned ch = 0; ch < 2 && s == KH_OK && (audio & FB_BENCH_PCM); ch++)
        s = kh_audio_read((uint8_t)KAGURA_AUDIO_PCM_INDEX(ch, KAGURA_AUDIO_PCM_STATUS), &t->pcm[ch]);
    *fault = t->error || (t->fifo & (KAGURA_AUDIO_STATUS_FIFO_UNDERFLOW | KAGURA_AUDIO_STATUS_OVERFLOW));
    for (unsigned ch = 0; ch < 2 && (audio & FB_BENCH_PCM); ch++)
        *fault |= (t->pcm[ch] & 0x78u) || !(t->pcm[ch] & KAGURA_AUDIO_PCM_STATUS_ACTIVE);
    return s;
}

static bool check_audio(const char *section) {
    telemetry t;
    bool fault;
    if (!ok("telemetry", read_telemetry(&t, &fault))) return false;
    printf("FB telemetry after=%s error=0x%02x audio_status=0x%02x pcm=0x%02x,0x%02x %s\n", section, t.error,
           t.fifo, t.pcm[0], t.pcm[1], fault ? "FAULT" : "ok");
    if (fault) failures++;
    return !fault;
}

// Same calls as test_tile_fb.py's scene(): bars, a fan of lines, circles and
// clipped rectangles across all four corners and the 1023/1024 boundary.
static void draw_scene(void) {
    tfb_fill(&kagura_fb, 0);
    for (int c = 0; c < 16; c++) tfb_fill_rect(&kagura_fb, c * 20, 0, 20, 24, (uint8_t)c);
    for (int n = 0; n < 32; n++) tfb_line(&kagura_fb, 160, 132, (int16_t)(n * 10 - 5), 239, (uint8_t)(1 + n % 15));
    for (int r = 4; r <= 100; r += 12) tfb_circle(&kagura_fb, 160, 132, (uint16_t)r, (uint8_t)(r % 15 + 1));
    tfb_rect(&kagura_fb, -10, -10, 40, 40, 15);
    tfb_rect(&kagura_fb, 300, 220, 40, 40, 14);
    tfb_fill_rect(&kagura_fb, 3, 201, 13, 37, 9);
    tfb_hline(&kagura_fb, -5, 205, 400, 10);
    tfb_vline(&kagura_fb, 319, -3, 300, 11);
    tfb_line(&kagura_fb, -40, 260, 360, -20, 12);
    for (int n = 0; n < 64; n++) tfb_pixel(&kagura_fb, (n * 37) % 320, 26 + (n * 11) % 20, (uint8_t)(n & 15));
}

static void w_pixel(void) {
    for (int n = 0; n < 1024; n++) tfb_pixel(&kagura_fb, (n * 17) % 320, (n * 13) % 240, (uint8_t)(1 + n % 15));
}
static void w_hline(void) { tfb_hline(&kagura_fb, 0, 120, 320, 9); }
static void w_vline(void) { tfb_vline(&kagura_fb, 160, 0, 240, 7); }
static void w_line(void) { tfb_line(&kagura_fb, 0, 0, 319, 239, 7); }
static void w_fill_rect(void) { tfb_fill_rect(&kagura_fb, 16, 16, 288, 208, 5); }
static void w_fill(void) { tfb_fill(&kagura_fb, 6); }
static void w_circle(void) { tfb_circle(&kagura_fb, 160, 120, 80, 12); }
static void w_rect(void) { tfb_rect(&kagura_fb, 16, 16, 288, 208, 3); }

static void bench_draw(unsigned reps) {
    static const struct { const char *name; void (*draw)(void); } workloads[] = {
        {"pixel_1024", w_pixel}, {"hline", w_hline}, {"vline", w_vline}, {"line", w_line},
        {"fill_rect", w_fill_rect}, {"fill", w_fill}, {"circle", w_circle}, {"rect", w_rect},
    };
    static samples s;
    double ns_per_cycle = 1e9 / clock_get_hz(clk_sys);
    cycles_start();
    for (size_t w = 0; w < sizeof workloads / sizeof workloads[0]; w++) {
        samples_reset(&s);
        for (unsigned n = 0; n < reps; n++) {
            tfb_fill(&kagura_fb, 0);
            memset(kagura_fb.dirty, 0, sizeof kagura_fb.dirty);
            uint32_t t0 = cycles_now();
            workloads[w].draw();
            samples_add(&s, cycles_since(t0));
        }
        unsigned dirty = 0;
        for (unsigned t = 0; t < TFB_TILES; t++) dirty += kagura_fb.dirty[t];
        printf("FB draw name=%s reps=%u dirty_tiles=%u", workloads[w].name, reps, dirty);
        print_samples("cpu", &s, ns_per_cycle);
        printf("\n");
    }
    // Dirty scan of a clean plane: what a no-op flush costs before any I/O.
    samples_reset(&s);
    memset(kagura_fb.dirty, 0, sizeof kagura_fb.dirty);
    for (unsigned n = 0; n < reps; n++) {
        uint32_t t0 = cycles_now();
        const void *hit = memchr(kagura_fb.dirty, 1, sizeof kagura_fb.dirty);
        samples_add(&s, cycles_since(t0));
        if (hit) failures++;
    }
    printf("FB draw name=dirty_scan reps=%u", reps);
    print_samples("cpu", &s, ns_per_cycle);
    printf("\n");
}

// Untimed: clear and flush. Timed: one flush of `count` single-pixel tiles.
static bool bench_flush(unsigned reps) {
    static const unsigned counts[] = {1, 10, 100, 1200};
    static samples transfer, wait, total;
    for (size_t c = 0; c < sizeof counts / sizeof counts[0]; c++) {
        samples_reset(&transfer); samples_reset(&wait); samples_reset(&total);
        uint64_t transactions = 0, wire = 0;
        for (unsigned n = 0; n < reps; n++) {
            tfb_fill(&kagura_fb, 0);
            if (!ok("flush-prepare", tfb_flush(&kagura_fb, 0))) return false;
            for (unsigned t = 0; t < counts[c]; t++)
                tfb_pixel(&kagura_fb, (int)(t % 40u * 8u), (int)(t / 40u * 8u), (uint8_t)(1 + n % 15));
            kh_stats *ks = kh_get_stats();
            uint64_t tx0 = ks->transactions, b0 = ks->bytes_sent;
            if (!ok("flush", tfb_flush(&kagura_fb, 0))) return false;
            transactions = ks->transactions - tx0;
            wire = ks->bytes_sent - b0;
            samples_add(&transfer, (uint32_t)kagura_fb.last_flush.transfer_us);
            samples_add(&wait, (uint32_t)kagura_fb.last_flush.wait_us);
            samples_add(&total, (uint32_t)kagura_fb.last_flush.total_us);
        }
        const tfb_flush_stats *st = &kagura_fb.last_flush;
        printf("FB flush dirty_tiles=%u reps=%u tiles=%lu bytes=%lu runs=%lu writes=%lu fences=%lu"
               " transactions=%llu wire_bytes=%llu", counts[c], reps, (unsigned long)st->tiles,
               (unsigned long)st->bytes, (unsigned long)st->runs, (unsigned long)st->writes,
               (unsigned long)st->fences, (unsigned long long)transactions, (unsigned long long)wire);
        print_samples("transfer", &transfer, 1000.0);
        print_samples("fence_wait", &wait, 1000.0);
        print_samples("flush", &total, 1000.0);
        printf("\n");
    }
    // Clean flush: must not touch the link at all.
    kh_stats *ks = kh_get_stats();
    uint64_t tx0 = ks->transactions;
    samples_reset(&total);
    for (unsigned n = 0; n < reps; n++) {
        if (!ok("clean-flush", tfb_flush(&kagura_fb, 0))) return false;
        samples_add(&total, (uint32_t)kagura_fb.last_flush.total_us);
    }
    bool clean = ks->transactions == tx0 && kagura_fb.last_flush.bytes == 0;
    if (!clean) failures++;
    printf("FB flush dirty_tiles=0 reps=%u transactions=%llu %s", reps,
           (unsigned long long)(ks->transactions - tx0), clean ? "ok" : "UNEXPECTED_IO");
    print_samples("flush", &total, 1000.0);
    printf("\n");
    return true;
}

// Sparse dirty patterns with and without gap merging (flush(max_gap)).
static bool bench_gap(unsigned reps) {
    static const struct { unsigned stride, gap; } cases[] = {{2, 0}, {2, 1}, {8, 0}, {8, 7}};
    static samples total;
    for (size_t c = 0; c < sizeof cases / sizeof cases[0]; c++) {
        samples_reset(&total);
        for (unsigned n = 0; n < reps; n++) {
            tfb_fill(&kagura_fb, 0);
            if (!ok("gap-prepare", tfb_flush(&kagura_fb, 0))) return false;
            for (unsigned t = 0; t < TFB_TILES; t += cases[c].stride)
                tfb_pixel(&kagura_fb, (int)(t % 40u * 8u), (int)(t / 40u * 8u), (uint8_t)(1 + n % 15));
            if (!ok("gap-flush", tfb_flush(&kagura_fb, cases[c].gap))) return false;
            samples_add(&total, (uint32_t)kagura_fb.last_flush.total_us);
        }
        const tfb_flush_stats *st = &kagura_fb.last_flush;
        printf("FB gap stride=%u max_gap=%u reps=%u tiles=%lu bytes=%lu runs=%lu fences=%lu", cases[c].stride,
               cases[c].gap, reps, (unsigned long)st->tiles, (unsigned long)st->bytes,
               (unsigned long)st->runs, (unsigned long)st->fences);
        print_samples("flush", &total, 1000.0);
        printf("\n");
    }
    return true;
}

// The moving window of framebuffer_benchmark.run(): erase, window, title bar,
// blinking cursor, then flush and read telemetry and FRAME_COUNT every loop.
static bool bench_loop(unsigned seconds) {
    static samples draw, flush, iteration;
    samples_reset(&draw); samples_reset(&flush); samples_reset(&iteration);
    tfb_fill(&kagura_fb, 0);
    if (!ok("loop-prepare", tfb_flush(&kagura_fb, 0))) return false;
    uint8_t frame0, frame;
    if (!ok("loop-frame", kh_read_reg(KAGURA_REG_FRAME_COUNT_L, &frame0))) return false;
    uint64_t start = time_us_64(), last_report = start, bytes = 0, frames = 0;
    uint32_t loops = 0;
    int px = -1, py = 0;
    while (time_us_64() - start < seconds * 1000000ull) {
        uint64_t t0 = time_us_64();
        if (px >= 0) tfb_fill_rect(&kagura_fb, px, py, 56, 40, 0);
        int x = (int)(loops * 5u % 264u), y = 40 + (int)(loops * 3u % 152u);
        tfb_fill_rect(&kagura_fb, x, y, 56, 40, 4);
        tfb_rect(&kagura_fb, x, y, 56, 40, 1);
        tfb_fill_rect(&kagura_fb, x + 4, y + 4, 48, 8, 3);
        tfb_fill_rect(&kagura_fb, 8, 24, 8, 8, loops % 2 ? 1 : 0);
        px = x; py = y;
        uint64_t t1 = time_us_64();
        if (!ok("loop-flush", tfb_flush(&kagura_fb, 0))) return false;
        uint64_t t2 = time_us_64();
        bytes += kagura_fb.last_flush.bytes;
        telemetry t;
        bool fault;
        if (!ok("loop-telemetry", read_telemetry(&t, &fault)) ||
            !ok("loop-frame", kh_read_reg(KAGURA_REG_FRAME_COUNT_L, &frame)))
            return false;
        if (fault) {
            printf("FB FAIL loop telemetry error=0x%02x audio_status=0x%02x pcm=0x%02x,0x%02x loops=%lu\n",
                   t.error, t.fifo, t.pcm[0], t.pcm[1], (unsigned long)loops);
            failures++;
            return false;
        }
        frames += (uint8_t)(frame - frame0);
        frame0 = frame;
        loops++;
        samples_add(&draw, (uint32_t)(t1 - t0));
        samples_add(&flush, (uint32_t)(t2 - t1));
        samples_add(&iteration, (uint32_t)(time_us_64() - t0));
        if (time_us_64() - last_report >= 10000000ull) {
            last_report = time_us_64();
            printf("FB loop_progress loops=%lu elapsed_ms=%llu\n", (unsigned long)loops,
                   (unsigned long long)((last_report - start) / 1000u));
        }
    }
    double elapsed = (double)(time_us_64() - start) / 1e6;
    printf("FB loop seconds=%.3f loops=%lu application_hz=%.3f hdmi_counter_hz=%.3f bytes=%llu",
           elapsed, (unsigned long)loops, loops / elapsed, frames / elapsed, (unsigned long long)bytes);
    print_samples("draw", &draw, 1000.0);
    print_samples("flush", &flush, 1000.0);
    print_samples("iteration", &iteration, 1000.0);
    printf("\n");
    return true;
}

// Scene CRC against the PC reference, then VRAM read-back: boundary tiles
// 0/1023/1024/1199 always, all 1200 tiles when full is set.
static bool verify(bool full) {
    draw_scene();
    uint32_t crc = crc32(kagura_fb.buffer.bytes, sizeof kagura_fb.buffer.bytes);
    bool scene_ok = crc == SCENE_CRC;
    if (!scene_ok) failures++;
    printf("FB scene buffer_crc32=%08lx expected=%08lx %s\n", (unsigned long)crc, (unsigned long)SCENE_CRC,
           scene_ok ? "ok" : "MISMATCH");
    if (!ok("scene-flush", tfb_flush(&kagura_fb, 0))) return false;
    static const unsigned tiles[] = {0, 1023, 1024, 1199};
    unsigned bad = 0;
    for (size_t i = 0; i < sizeof tiles / sizeof tiles[0]; i++) {
        unsigned t = tiles[i];
        uint32_t addr = t < 1024 ? KAGURA_VRAM_PATTERN_BASE + t * 32u : KAGURA_VRAM_PATTERN_EXT_BASE + (t - 1024u) * 32u;
        if (!ok("readback", kh_vram_read(addr, back, 32))) return false;
        bad += memcmp(back, &kagura_fb.buffer.bytes[t * 32u], 32) != 0;
    }
    if (bad) failures++;
    printf("FB readback tiles=0,1023,1024,1199 mismatched_tiles=%u %s\n", bad, bad ? "MISMATCH" : "ok");
    if (full) {
        uint64_t t0 = time_us_64();
        uint32_t vcrc = 0xffffffffu;
        bad = 0;
        for (unsigned t = 0; t < TFB_TILES; t += 8) {
            uint32_t addr = t < 1024 ? KAGURA_VRAM_PATTERN_BASE + t * 32u : KAGURA_VRAM_PATTERN_EXT_BASE + (t - 1024u) * 32u;
            if (!ok("readback-full", kh_vram_read(addr, back, 256))) return false;   // 8 tiles, never across 1024
            for (unsigned i = 0; i < 8; i++) bad += memcmp(back + i * 32u, &kagura_fb.buffer.bytes[(t + i) * 32u], 32) != 0;
            for (unsigned i = 0; i < 256; i++) {
                vcrc ^= back[i];
                for (int k = 0; k < 8; k++) vcrc = (vcrc >> 1) ^ (0xedb88320u & -(vcrc & 1u));
            }
        }
        if (bad) failures++;
        printf("FB readback_full bytes=38400 vram_crc32=%08lx mismatched_tiles=%u seconds=%.1f %s\n",
               (unsigned long)~vcrc, bad, (time_us_64() - t0) / 1e6, bad ? "MISMATCH" : "ok");
    }
    return true;
}

static kh_status audio_start(unsigned flags) {
    uint8_t caps = 0;
    kh_status s = kh_read_reg(KAGURA_REG_CAPS, &caps);
    if (s == KH_OK && (flags & FB_BENCH_PCM) && !(caps & KAGURA_CAPS_PSRAM)) {
        printf("FB FAIL pcm needs a PSRAM bitstream (CAPS 0x%02x)\n", caps);
        return KH_BAD_ARGUMENT;
    }
    audio = flags & (FB_BENCH_PCM | FB_BENCH_PSG);
    for (unsigned ch = 0; ch < KAGURA_AUDIO_CHANNELS && s == KH_OK; ch++)
        s = audio_reg(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_CONTROL), 0);
    if (s == KH_OK) s = audio_reg(KAGURA_AUDIO_MASTER_GAIN, 64);
    if (s == KH_OK) s = kh_audio_commit(100000);
    if (s == KH_OK && (audio & FB_BENCH_PCM)) s = pcm_start();
    if (s == KH_OK && (audio & FB_BENCH_PSG)) s = psg_start();
    return s;
}

void kagura_fb_bench(unsigned reps, unsigned seconds, unsigned flags) {
    failures = 0;
    audio = 0;
    const kh_config *cfg = kh_get_config();
    const unsigned sound = flags & (FB_BENCH_PCM | FB_BENCH_PSG);
    printf("FB config mode=%s sck_mhz=%.2f cpu_mhz=%.1f reps=%u loop_seconds=%u audio=%s\n",
           cfg->lanes == KH_QSPI ? "qspi" : "spi", 10.0 / cfg->clkdiv, clock_get_hz(clk_sys) / 1e6, reps, seconds,
           sound == (FB_BENCH_PCM | FB_BENCH_PSG) ? "pcm+psg" : sound == FB_BENCH_PCM ? "pcm" : sound ? "psg" : "none");
    tfb_reset(&kagura_fb, 0);
    kh_status s = kh_clear_errors();
    if (s == KH_OK) s = palette_gray();
    uint64_t t0 = time_us_64();
    if (s == KH_OK) {
        s = tfb_initialize(&kagura_fb, true);
        if (s == KH_BAD_ARGUMENT) printf("FB FAIL needs a 480p ABI 0.6 bitstream with 1200 patterns\n");
    }
    if (!ok("initialize", s)) { printf("FBBENCH FAIL %d\n", failures); return; }
    printf("FB initialize total_us=%llu flush_us=%llu\n", (unsigned long long)(time_us_64() - t0),
           (unsigned long long)kagura_fb.last_flush.total_us);
    if (sound && !ok("audio-start", audio_start(sound))) {
        audio_stop();
        printf("FBBENCH FAIL %d\n", failures);
        return;
    }
    if (check_audio("start")) {
        bench_draw(reps);
        if (check_audio("draw") && bench_flush(reps) && check_audio("flush") && bench_gap(reps) &&
            check_audio("gap") && (!seconds || bench_loop(seconds)) && verify(flags & FB_BENCH_FULL))
            check_audio("verify");
    }
    if (sound) ok("audio-stop", audio_stop());
    printf(failures ? "FBBENCH FAIL %d\n" : "FBBENCH PASS\n", failures);
}
