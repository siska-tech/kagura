// SPDX-License-Identifier: Apache-2.0
// C TileFramebuffer showcase. Plasma and tunnel are drawn once and moved by
// palette cycling; the tesseract over parallax stars and the line ribbon are
// redrawn every frame and only the tiles that change are sent. The palette
// COMMIT at the end of each frame waits for VBlank and paces the loop. A
// small PSG song (arpeggio, lead, bass, hi-hat) runs on its own clock.
#include "fb_demo.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "fb_bench.h"
#include "pico/stdlib.h"

#define SCENE_US 12000000u
#define FADE_FRAMES 24u
#define TICK_US 125000u    // one 16th note at 120 BPM
#define PI_F 3.14159265f

static tile_fb *const fb = &kagura_fb;
static uint16_t pal[16];   // RGB444 at full brightness
static int8_t sine[256];
static uint32_t rng = 0x2545f491u;

static unsigned rnd(unsigned n) {
    rng = rng * 1664525u + 1013904223u;
    return (rng >> 16) % n;
}

static uint16_t rgb_scale(uint16_t rgb, unsigned level) {   // level 0..16
    return (uint16_t)((((rgb >> 8) & 15u) * level / 16u) << 8 | (((rgb >> 4) & 15u) * level / 16u) << 4 |
                      (rgb & 15u) * level / 16u);
}

// Cosine palette: each channel is a sine of the phase with its own offset.
static uint16_t ramp(unsigned phase, unsigned r, unsigned g, unsigned b) {
    const unsigned off[3] = {r, g, b};
    unsigned rgb = 0;
    for (unsigned c = 0; c < 3; c++) rgb = rgb << 4 | (unsigned)(8 + sine[(phase + off[c]) & 255u] * 7 / 127);
    return (uint16_t)rgb;
}

static kh_status palette_write(unsigned level) {
    uint8_t bytes[32];
    for (unsigned i = 0; i < 16; i++) {
        uint16_t v = rgb_scale(pal[i], level);
        bytes[2 * i] = (uint8_t)v;
        bytes[2 * i + 1] = (uint8_t)(v >> 8);
    }
    return kh_vram_write(KAGURA_VRAM_PALETTE_BASE + fb->palette * 32u, bytes, sizeof bytes);
}

// ---- plasma: four sines, 16 colour bands wrapping about four times ----

static void plasma_enter(void) {
    for (int y = 0; y < TFB_HEIGHT; y++) for (int x = 0; x < TFB_WIDTH; x++) {
        int dx = x - 160, dy = y - 100;
        int v = sine[(x * 3 / 2) & 255] + sine[(y * 2 + 64) & 255] + sine[(x + y) & 255] +
                sine[((int)sqrtf((float)(dx * dx + dy * dy)) * 2) & 255];
        tfb_pixel(fb, x, y, (uint8_t)(((v + 512) >> 4) & 15));
    }
}

static void plasma_frame(unsigned t) {
    for (unsigned i = 0; i < 16; i++) pal[i] = ramp(i * 16u + t * 2u, 0, 85u + t / 3u, 170u + t / 2u);
}

// ---- tunnel: depth 1/d plus a two-arm angle term, one quadrant mirrored ----

static void tunnel_enter(void) {
    for (int y = 0; y < 120; y++) for (int x = 0; x < 160; x++) {
        float fx = (float)x + 0.5f, fy = (float)y + 0.5f;
        int depth = (int)(1024.0f / sqrtf(fx * fx + fy * fy));
        int a = (int)(atan2f(fy, fx) * 128.0f / PI_F);           // 0..63 in this quadrant
        const int ang[4] = {a, 128 - a, 128 + a, 256 - a};
        const int px[4] = {160 + x, 159 - x, 159 - x, 160 + x}, py[4] = {120 + y, 120 + y, 119 - y, 119 - y};
        for (int q = 0; q < 4; q++) tfb_pixel(fb, px[q], py[q], (uint8_t)((depth + (ang[q] >> 3)) & 15));
    }
}

static void tunnel_frame(unsigned t) {
    for (unsigned i = 0; i < 16; i++) {
        unsigned light = (unsigned)(9 + sine[(i * 16u + t * 6u) & 255u] * 7 / 127);   // 2..16
        pal[i] = rgb_scale(ramp(t / 2u + i * 4u, 0, 85, 170), light);
    }
}

// ---- tesseract: 4D rotation, perspective twice, depth-coloured edges ----

#define STARS 48
static int16_t edge_old[32][4];
static uint8_t edge_count;
static struct { int16_t x, y; uint16_t fx; uint8_t speed; } star[STARS];   // fx = x * 256

static void vector_enter(void) {
    tfb_fill(fb, 0);
    edge_count = 0;
    for (unsigned i = 0; i < STARS; i++) {
        star[i].fx = (uint16_t)(rnd(TFB_WIDTH) << 8);
        star[i].x = (int16_t)(star[i].fx >> 8);
        star[i].y = (int16_t)rnd(TFB_HEIGHT);
        star[i].speed = (uint8_t)(1 + rnd(4));
    }
}

static void vector_frame(unsigned t) {
    pal[0] = 0x002;
    for (unsigned k = 1; k <= 4; k++) pal[k] = (uint16_t)(0x111u * (k * 3u) + k);
    for (unsigned k = 0; k < 8; k++) pal[8 + k] = rgb_scale(ramp(t / 2u + k * 10u, 0, 85, 170), 6u + k * 10u / 7u);
    for (unsigned e = 0; e < edge_count; e++)
        tfb_line(fb, edge_old[e][0], edge_old[e][1], edge_old[e][2], edge_old[e][3], 0);
    for (unsigned i = 0; i < STARS; i++) {
        tfb_pixel(fb, star[i].x, star[i].y, 0);
        star[i].fx = (uint16_t)((star[i].fx + star[i].speed * 96u) % (TFB_WIDTH << 8));
        star[i].x = (int16_t)(star[i].fx >> 8);
        tfb_pixel(fb, star[i].x, star[i].y, star[i].speed);
    }
    float a = (float)t * 0.021f, b = (float)t * 0.013f, c = (float)t * 0.009f;
    float ca = cosf(a), sa = sinf(a), cb = cosf(b), sb = sinf(b), cc = cosf(c), sc = sinf(c);
    int16_t px[16], py[16];
    float pz[16];
    for (unsigned v = 0; v < 16; v++) {
        float x = v & 1u ? 1.0f : -1.0f, y = v & 2u ? 1.0f : -1.0f, z = v & 4u ? 1.0f : -1.0f, w = v & 8u ? 1.0f : -1.0f;
        float x1 = x * ca - w * sa, w1 = x * sa + w * ca;           // XW
        float z1 = z * cb - w1 * sb, w2 = z * sb + w1 * cb;         // ZW
        float k = 1.0f / (2.6f - w2);                               // 4D -> 3D
        x1 *= k; y *= k; z1 *= k;
        float x2 = x1 * cc + z1 * sc, z2 = -x1 * sc + z1 * cc;      // Y axis
        float y2 = y * cc - z2 * sc, z3 = y * sc + z2 * cc;         // X axis
        float p = 230.0f / (2.2f - z3);                             // 3D -> 2D
        px[v] = (int16_t)(160.0f + x2 * p);
        py[v] = (int16_t)(120.0f + y2 * p);
        pz[v] = z3;
    }
    edge_count = 0;
    for (unsigned v = 0; v < 16; v++) for (unsigned bit = 1; bit < 16; bit <<= 1) {
        unsigned u = v | bit;
        if (u == v) continue;
        float z = (pz[v] + pz[u]) * 0.5f;                          // about -0.7..0.7
        int colour = 8 + (int)((z + 0.75f) * 5.0f);
        tfb_line(fb, px[v], py[v], px[u], py[u], (uint8_t)(colour < 8 ? 8 : colour > 15 ? 15 : colour));
        const int16_t e[4] = {px[v], py[v], px[u], py[u]};
        memcpy(edge_old[edge_count++], e, sizeof e);
    }
}

// ---- ribbon: a bouncing line and its point mirror leave a rainbow trail ----

#define TRAIL 24
static int16_t trail[TRAIL][4];
static unsigned trail_serial;
static int rib_p[4], rib_v[4];

static void ribbon_line(const int16_t *l, uint8_t colour) {
    tfb_line(fb, l[0], l[1], l[2], l[3], colour);
    tfb_line(fb, (int16_t)(319 - l[0]), (int16_t)(239 - l[1]), (int16_t)(319 - l[2]), (int16_t)(239 - l[3]), colour);
}

static void ribbon_enter(void) {
    tfb_fill(fb, 0);
    trail_serial = 0;
    const int p[4] = {40, 30, 250, 200}, v[4] = {3, 2, -2, 3};
    memcpy(rib_p, p, sizeof p);
    memcpy(rib_v, v, sizeof v);
}

static void ribbon_frame(unsigned t) {
    pal[0] = 0x000;
    for (unsigned i = 0; i < 15; i++) pal[1 + i] = ramp(i * 17u + t * 3u, 0, 85, 170);
    if (trail_serial >= TRAIL) ribbon_line(trail[trail_serial % TRAIL], 0);
    for (unsigned k = 0; k < 4; k++) {
        const int limit = k & 1u ? TFB_HEIGHT - 1 : TFB_WIDTH - 1;
        rib_p[k] += rib_v[k];
        if (rib_p[k] < 0 || rib_p[k] > limit) {
            rib_p[k] = rib_p[k] < 0 ? 0 : limit;
            rib_v[k] = (rib_p[k] ? -1 : 1) * (int)(2 + rnd(4));
        }
        trail[trail_serial % TRAIL][k] = (int16_t)rib_p[k];
    }
    trail_serial++;
    // Redraw the whole trail oldest first so the erase above leaves no gaps.
    for (unsigned n = trail_serial > TRAIL ? trail_serial - TRAIL : 0; n < trail_serial; n++)
        ribbon_line(trail[n % TRAIL], (uint8_t)(1 + n % 15u));
}

// ---- music: Am F C G, 16th-note arpeggio, eighth-note lead ----

static uint32_t note_step[96];

static kh_status aw(unsigned ch, unsigned off, uint8_t value) {
    return kh_audio_write((uint8_t)KAGURA_AUDIO_INDEX(ch, off), value);
}

static kh_status note(unsigned ch, int midi) {
    kh_status s = KH_OK;
    for (unsigned b = 0; b < 3 && s == KH_OK; b++) s = aw(ch, KAGURA_AUDIO_STEP_L + b, (uint8_t)(note_step[midi] >> (8 * b)));
    return s;
}

static kh_status gain(unsigned ch, uint8_t left, uint8_t right) {
    kh_status s = aw(ch, KAGURA_AUDIO_GAIN_L, left);
    return s == KH_OK ? aw(ch, KAGURA_AUDIO_GAIN_R, right) : s;
}

static kh_status music_init(void) {
    for (int m = 0; m < 96; m++)
        note_step[m] = (uint32_t)lrintf(440.0f * powf(2.0f, (float)(m - 69) / 12.0f) * 16777216.0f / 48000.0f);
    static const uint8_t duty[3] = {32, 128, 64};
    kh_status s = kh_audio_write(KAGURA_AUDIO_MASTER_GAIN, 48);
    for (unsigned ch = 0; ch < KAGURA_AUDIO_CHANNELS && s == KH_OK; ch++) {
        s = gain(ch, 0, 0);
        if (s == KH_OK && ch < 3) s = aw(ch, KAGURA_AUDIO_DUTY, duty[ch]);
        if (s == KH_OK && ch >= 4) s = aw(ch, KAGURA_AUDIO_LEN_LOG2, 8);
        if (s == KH_OK) s = aw(ch, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET);
    }
    if (s == KH_OK) s = aw(3, KAGURA_AUDIO_NOISE_PERIOD_L, 6);
    if (s == KH_OK) s = aw(3, KAGURA_AUDIO_NOISE_PERIOD_H, 0);
    uint8_t wave[512];   // triangle then sine; AUDIO_COMMIT swaps banks, so write both
    for (unsigned i = 0; i < 256; i++) {
        wave[i] = (uint8_t)(int8_t)(i < 128 ? (int)i * 2 - 128 : 383 - (int)i * 2);
        wave[256 + i] = (uint8_t)sine[i];
    }
    for (unsigned bank = 0; bank < 2 && s == KH_OK; bank++) {
        s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, wave, sizeof wave);
        if (s == KH_OK) s = kh_audio_commit(100000);
    }
    return s;
}

static kh_status music_tick(unsigned n) {
    static const uint8_t chord[4][3] = {{57, 60, 64}, {57, 60, 65}, {55, 60, 64}, {55, 59, 62}};
    static const uint8_t bass[4] = {45, 41, 48, 43};
    static const uint8_t lead[32] = {
        76, 0, 72, 74, 76, 79, 76, 74,  72, 0, 69, 72, 77, 76, 72, 69,
        67, 72, 76, 79, 77, 76, 72, 74, 74, 0, 71, 67, 74, 76, 74, 71,
    };
    const unsigned bar = (n / 16u) & 3u, s16 = n & 15u;
    const uint8_t *c = chord[bar];
    const unsigned m = lead[bar * 8u + s16 / 2u];
    kh_status s = note(0, c[s16 % 3u] + 12 + 12 * (int)((s16 / 3u) & 1u));                 // arpeggio
    if (s == KH_OK) s = gain(0, 12, 6);
    if (s == KH_OK && m && !(s16 & 1u)) s = note(1, (int)m);
    if (s == KH_OK) s = gain(1, !m ? 0 : s16 & 1u ? 9 : 16, !m ? 0 : s16 & 1u ? 9 : 16);  // lead, eighth-note decay
    if (s == KH_OK && s16 == 0) s = note(2, c[1]);
    if (s == KH_OK) s = gain(2, 3, 5);                                                    // quiet third
    if (s == KH_OK) s = gain(3, s16 % 4u == 2u ? 6 : 2, s16 % 4u == 2u ? 6 : 2);           // hi-hat
    if (s == KH_OK) s = note(4, bass[bar] + ((s16 & 4u) ? 12 : 0));                        // bass
    if (s == KH_OK) s = gain(4, s16 & 1u ? 16 : 40, s16 & 1u ? 16 : 40);
    if (s == KH_OK && s16 == 0) s = note(5, bass[bar] + 19);                              // fifth pad
    if (s == KH_OK) s = gain(5, 10, 14);
    return s == KH_OK ? kh_audio_commit(100000) : s;
}

static void music_stop(void) {
    kh_status s = KH_OK;
    for (unsigned ch = 0; ch < KAGURA_AUDIO_CHANNELS && s == KH_OK; ch++) s = aw(ch, KAGURA_AUDIO_CONTROL, 0);
    if (s == KH_OK) kh_audio_commit(100000);
}

static bool key_pressed(void) {
    for (;;) {
        int c = getchar_timeout_us(0);
        if (c == PICO_ERROR_TIMEOUT) return false;
        if (c != '\r' && c != '\n') return true;   // ignore the command's line ending
    }
}

static const struct {
    const char *name;
    void (*enter)(void);         // first picture into the buffer, no I/O
    void (*frame)(unsigned t);   // per frame: buffer changes and pal[]
} scenes[] = {
    {"plasma", plasma_enter, plasma_frame},
    {"tesseract", vector_enter, vector_frame},
    {"tunnel", tunnel_enter, tunnel_frame},
    {"ribbon", ribbon_enter, ribbon_frame},
};

kh_status kagura_fb_demo(unsigned seconds) {
    for (unsigned i = 0; i < 256; i++) sine[i] = (int8_t)lrintf(127.0f * sinf(2.0f * PI_F * (float)i / 256.0f));
    tfb_reset(fb, 0);
    memset(pal, 0, sizeof pal);
    kh_status s = kh_clear_errors();
    if (s == KH_OK) s = palette_write(0);   // tfb_initialize's COMMIT applies it
    if (s == KH_OK) {
        s = tfb_initialize(fb, true);
        if (s == KH_BAD_ARGUMENT) printf("FBDEMO needs a 480p ABI 0.6 bitstream with 1200 patterns\n");
    }
    if (s == KH_OK) s = music_init();
    if (s != KH_OK) {
        music_stop();
        printf("FBDEMO FAILED %d during setup\n", s);
        return s;
    }
    printf("FBDEMO GO — %s, press any key to stop\n", seconds ? "timed run" : "unlimited run");
    const uint64_t end = seconds ? time_us_64() + (uint64_t)seconds * 1000000u : UINT64_MAX;
    uint64_t next_tick = time_us_64();
    unsigned tick = 0, total = 0;
    bool stop = false;
    for (unsigned n = 0; s == KH_OK && !stop && time_us_64() < end; n++) {
        const unsigned id = n % (sizeof scenes / sizeof scenes[0]);
        uint64_t t0 = time_us_64();
        scenes[id].enter();
        const uint64_t enter_us = time_us_64() - t0, leave = t0 + SCENE_US < end ? t0 + SCENE_US : end;
        uint64_t flush_us = 0, tiles = 0;
        unsigned frames = 0, out = FADE_FRAMES;
        for (unsigned t = 0; s == KH_OK && out; t++) {
            if (stop || time_us_64() >= leave) out--;
            uint64_t now = time_us_64();
            if (now >= next_tick) {
                s = music_tick(tick++);
                next_tick = now - next_tick > TICK_US ? now + TICK_US : next_tick + TICK_US;   // resync after a stall
            }
            scenes[id].frame(t);
            uint64_t f0 = time_us_64();
            if (s == KH_OK) s = tfb_flush(fb, 2);
            flush_us += time_us_64() - f0;
            tiles += fb->last_flush.tiles;
            unsigned level = t >= FADE_FRAMES ? 16u : t * 16u / FADE_FRAMES;
            if (out * 16u / FADE_FRAMES < level) level = out * 16u / FADE_FRAMES;
            if (s == KH_OK) s = palette_write(level);
            if (s == KH_OK) s = kh_commit(100000);   // waits for VBlank
            frames++;
            if (!stop) stop = key_pressed();
        }
        double elapsed = (double)(time_us_64() - t0 - enter_us) / 1e6;
        printf("FBDEMO scene=%s draw_first_ms=%.1f frames=%u fps=%.1f flush_mean_ms=%.2f tiles_per_frame=%.0f\n",
               scenes[id].name, enter_us / 1000.0, frames, frames / elapsed, flush_us / 1000.0 / frames,
               (double)tiles / frames);
        total += frames;
    }
    music_stop();
    if (s == KH_OK) s = kh_check_errors();
    printf("FBDEMO %s after %u frames\n", s == KH_OK ? "DONE" : "FAILED", total);
    return s;
}
