// SPDX-License-Identifier: Apache-2.0
// Pico-driven KAGURA-9 showcase: a moonlit city, parallax raster bands,
// an animated original runner, magic lights and six-voice melodic music.
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "spectacular_demo.h"

static uint8_t work[8192];

static int wave64(unsigned phase) {
    static const int8_t q[17] = {0,12,24,35,45,53,59,63,64,63,59,53,45,35,24,12,0};
    phase &= 63u;
    if (phase < 16) return q[phase];
    if (phase < 32) return q[32 - phase];
    if (phase < 48) return -q[phase - 32];
    return -q[64 - phase];
}

static void pattern_pixel(unsigned tile, unsigned x, unsigned y, unsigned colour) {
    unsigned addr = tile * 32u + y * 4u + x / 2u;
    if ((x & 1u) == 0) work[addr] = (uint8_t)((work[addr] & 15u) | (colour << 4));
    else work[addr] = (uint8_t)((work[addr] & 0xf0u) | colour);
}

static void sprite_pixel(unsigned base, unsigned x, unsigned y, unsigned colour) {
    unsigned tile = base + (y >= 8 ? 2u : 0u) + (x >= 8 ? 1u : 0u);
    pattern_pixel(tile, x & 7u, y & 7u, colour);
}

static void canvas_pixel(uint8_t *canvas, int x, int y, uint8_t colour) {
    if (x >= 0 && x < 32 && y >= 0 && y < 32) canvas[y * 32 + x] = colour;
}

static void canvas_rect(uint8_t *canvas, int x0, int y0, int x1, int y1, uint8_t colour) {
    for (int y = y0; y <= y1; y++) for (int x = x0; x <= x1; x++) canvas_pixel(canvas, x, y, colour);
}

static void canvas_line(uint8_t *canvas, int x0, int y0, int x1, int y1, uint8_t colour) {
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, sx = x0 < x1 ? 1 : -1;
    int dy = -(y1 > y0 ? y1 - y0 : y0 - y1), sy = y0 < y1 ? 1 : -1, err = dx + dy;
    for (;;) {
        canvas_pixel(canvas, x0, y0, colour);
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

static void make_runner_frame(unsigned frame) {
    uint8_t c[32 * 32];
    memset(c, 0, sizeof c);
    // Original desert courier: indigo hair, magenta scarf, teal vest and
    // cream trousers. Four poses share a deliberately chunky 8/16-bit style.
    int bob = frame == 1 ? 1 : 0;
    canvas_rect(c, 12, 3 + bob, 19, 9 + bob, 3);       // hair
    canvas_rect(c, 15, 5 + bob, 21, 11 + bob, 7);      // face
    canvas_pixel(c, 20, 7 + bob, 15);
    canvas_line(c, 12, 6 + bob, 6, 4 + bob, 11);       // scarf
    canvas_line(c, 10, 7 + bob, 3, 8 + bob, 11);
    canvas_rect(c, 11, 11 + bob, 20, 20 + bob, 9);     // vest
    canvas_rect(c, 13, 12 + bob, 18, 20 + bob, 5);     // shirt
    int arm = frame == 0 ? 4 : (frame == 1 ? -3 : 7);
    canvas_line(c, 12, 13 + bob, 7, 16 + arm / 3 + bob, 7);
    canvas_line(c, 20, 13 + bob, 25, 16 - arm / 3 + bob, 7);
    canvas_rect(c, 11, 20 + bob, 20, 24 + bob, 13);    // sash/trousers
    if (frame == 2) {                                  // airborne tuck
        canvas_line(c, 13, 24, 8, 27, 13); canvas_line(c, 19, 24, 24, 27, 13);
        canvas_line(c, 8, 27, 5, 26, 3); canvas_line(c, 24, 27, 28, 25, 3);
    } else if (frame == 3) {                           // long jump
        canvas_line(c, 13, 24, 5, 25, 13); canvas_line(c, 19, 24, 27, 24, 13);
        canvas_line(c, 5, 25, 2, 23, 3); canvas_line(c, 27, 24, 30, 22, 3);
    } else if (frame == 0) {
        canvas_line(c, 13, 24, 8, 30, 13); canvas_line(c, 19, 24, 24, 27, 13);
        canvas_line(c, 8, 30, 4, 30, 3); canvas_line(c, 24, 27, 28, 27, 3);
    } else {
        canvas_line(c, 13, 24, 7, 27, 13); canvas_line(c, 19, 24, 22, 31, 13);
        canvas_line(c, 7, 27, 3, 26, 3); canvas_line(c, 22, 31, 27, 31, 3);
    }
    unsigned frame_base = 64u + frame * 16u;
    for (unsigned qy = 0; qy < 2; qy++) for (unsigned qx = 0; qx < 2; qx++) {
        unsigned base = frame_base + (qy * 2u + qx) * 4u;
        for (unsigned y = 0; y < 16; y++) for (unsigned x = 0; x < 16; x++)
            sprite_pixel(base, x, y, c[(qy * 16u + y) * 32u + qx * 16u + x]);
    }
}

static void make_patterns(void) {
    memset(work, 0, sizeof work);
    for (unsigned y = 0; y < 8; y++) for (unsigned x = 0; x < 8; x++) {
        pattern_pixel(1, x, y, 1);                                      // open sky
        pattern_pixel(2, x, y, y > 4u + ((x + 1u) & 2u) ? 5 : 0);       // distant dune crest
        pattern_pixel(3, x, y, y >= 2u + ((x * 3u) & 3u) ? 6 : 0);      // far skyline
        pattern_pixel(4, x, y, y >= 1u + ((x * 5u + 2u) & 5u) ? 8 : 0);// near skyline
        pattern_pixel(5, x, y, y == 0 ? 14 : (y < 3 ? 10 : 9));         // rooftop
        pattern_pixel(6, x, y, ((x + y) & 3u) ? 2 : 3);                 // foreground tiles
        pattern_pixel(7, x, y, (x == 3 || x == 4 || y == 4) ? 12 : 0); // cloud glint
        pattern_pixel(8, x, y, (x == y || x + y == 7) ? 15 : 0);        // magic spark
        pattern_pixel(9, x, y, (x == 0 || x == 7 || y < 2) ? 13 : 6);  // parapet
    }
    for (unsigned frame = 0; frame < 4; frame++) make_runner_frame(frame);
    // A small magic orb used by secondary sprites.
    for (unsigned y = 0; y < 8; y++) for (unsigned x = 0; x < 8; x++) {
        int dx = (int)x - 3, dy = (int)y - 3, d = dx * dx + dy * dy;
        pattern_pixel(128, x, y, d < 5 ? 15 : (d < 13 ? 12 : 0));
    }
}

static void make_map(void) {
    for (unsigned y = 0; y < 32; y++) for (unsigned x = 0; x < 64; x++) {
        unsigned tile, pal;
        if (y < 6) { tile = ((x * 13u + y * 7u) % 29u == 0) ? 8u : 1u; pal = 0; }
        else if (y < 11) { tile = ((x + y * 3u) % 11u < 3u) ? 7u : (((x + y) & 3u) ? 1u : 2u); pal = 1; }
        else if (y < 17) { tile = ((x * 5u + y) & 7u) < 3u ? 3u : 2u; pal = 2; }
        else if (y < 23) { tile = ((x * 3u + y) & 7u) < 5u ? 4u : 3u; pal = 3; }
        else if (y < 27) { tile = (y == 23 || y == 26) ? 5u : (((x + y) & 7u) == 0 ? 9u : 1u); pal = 4; }
        else { tile = 6u; pal = 5; }
        uint16_t entry = (uint16_t)(tile | (pal << 10));
        if (x & 8u) entry |= 1u << 14;
        unsigned n = 2u * (y * 64u + x);
        work[n] = (uint8_t)entry; work[n + 1] = (uint8_t)(entry >> 8);
    }
}

static void palette_set(unsigned pal, unsigned colour, uint16_t rgb) {
    unsigned n = 2u * (pal * 16u + colour);
    work[n] = (uint8_t)rgb; work[n + 1] = (uint8_t)(rgb >> 8);
}

static void make_palette(unsigned frame) {
    memset(work, 0, 512);
    unsigned glow = (unsigned)(wave64(frame) + 64) >> 5;
    // Cool moonlit palette: keep the silhouettes readable without turning
    // every animated highlight into an orange flame.
    palette_set(0, 1, (uint16_t)(0x125u + glow));
    palette_set(0, 15, 0xeff); palette_set(0, 12, 0x9cf);
    palette_set(1, 1, 0x125); palette_set(1, 5, 0x547); palette_set(1, 12, 0x9bd); palette_set(1, 15, 0xeff);
    palette_set(2, 5, 0x426); palette_set(2, 6, 0x214); palette_set(2, 12, 0x769);
    palette_set(3, 6, 0x112); palette_set(3, 8, 0x225); palette_set(3, 13, 0x54a);
    palette_set(4, 1, 0x111); palette_set(4, 6, 0x223); palette_set(4, 9, 0x345); palette_set(4, 10, 0x8bd); palette_set(4, 13, 0x457); palette_set(4, 14, 0xbef);
    palette_set(5, 2, 0x011); palette_set(5, 3, 0x133);
    // Runner/orb palette bank 8.
    palette_set(8, 3, 0x213); palette_set(8, 5, 0xeee); palette_set(8, 7, 0xb65);
    palette_set(8, 9, 0x078); palette_set(8, 11, 0xe24); palette_set(8, 12, 0x6ef);
    palette_set(8, 13, 0xffd); palette_set(8, 15, 0xfff);
}

static void make_oam(unsigned frame, unsigned height) {
    memset(work, 0, 512);
    unsigned cycle = frame % 180u;
    bool jumping = cycle >= 72u && cycle < 120u;
    unsigned pose = jumping ? (cycle < 96u ? 2u : 3u) : ((frame / 7u) & 1u);
    int jump = jumping ? -(wave64((cycle - 72u) * 32u / 48u) * 58 / 64) : 0;
    int runner_x = 92 + wave64(frame / 3u) / 8;
    int runner_y = (int)height - 70 + jump;
    for (unsigned i = 0; i < 4; i++) {
        int x = runner_x + (int)(i & 1u) * 16;
        int y = runner_y + (int)(i >> 1) * 16;
        unsigned tile = 64u + pose * 16u + i * 4u;
        unsigned n = i * 8u;
        work[n] = (uint8_t)x; work[n + 1] = (uint8_t)((x >> 8) & 3);
        work[n + 2] = (uint8_t)y; work[n + 3] = (uint8_t)(((y >> 8) & 3) | (3u << 2));
        work[n + 4] = (uint8_t)tile;
        work[n + 5] = (uint8_t)(((tile >> 8) & 3u) | (8u << 2));
    }
    for (unsigned i = 4; i < 16; i++) {
        unsigned p = (frame * 2u + i * 5u) & 63u;
        int x = 160 + wave64(p + 16u) * (70 + (int)i * 3) / 64;
        int y = (int)height / 2 + wave64(p) * 70 / 64;
        unsigned n = i * 8u, tile = 128;
        work[n] = (uint8_t)x; work[n + 1] = (uint8_t)((x >> 8) & 3);
        work[n + 2] = (uint8_t)y; work[n + 3] = (uint8_t)(((y >> 8) & 3) | (1u << 2));
        work[n + 4] = (uint8_t)tile; work[n + 5] = (uint8_t)(8u << 2);
    }
}

static kh_status set_raster(unsigned frame, unsigned height, bool supported) {
    static const uint8_t line240[8] = {0,48,80,112,144,176,208,224};
    static const uint8_t speed8[8] = {0,1,2,3,4,6,10,14};
    kh_status s = kh_ext_write(KAGURA_EXT_SCROLL_X_L, 0);
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_SCROLL_X_H, 0);
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_SCROLL_Y, 0);
    if (!supported || s != KH_OK) return s;
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_RS_INDEX, 0);
    for (unsigned band = 0; band < 8 && s == KH_OK; band++) {
        unsigned x = (frame * speed8[band] / 4u) & 511u;
        s = kh_ext_write(KAGURA_EXT_RS_LINE, (uint8_t)(line240[band] * height / 240u));
        if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_RS_X_L, (uint8_t)x);
        if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_RS_X_H, (uint8_t)(x >> 8));
        if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_RS_Y, 0);
    }
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_RS_COUNT, 8);
    return s;
}

static kh_status audio_write(unsigned ch, unsigned off, uint8_t value) {
    return kh_audio_write((uint8_t)KAGURA_AUDIO_INDEX(ch, off), value);
}

static kh_status audio_step(unsigned ch, uint32_t step) {
    kh_status s = audio_write(ch, KAGURA_AUDIO_STEP_L, (uint8_t)step);
    if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_STEP_M, (uint8_t)(step >> 8));
    if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_STEP_H, (uint8_t)(step >> 16));
    return s;
}

static void make_waves(void) {
    for (unsigned i = 0; i < 256; i++) {
        work[i] = (uint8_t)(int8_t)(wave64(i >> 2) * 2 - (int)(i & 7u));
        int tri = i < 128 ? (int)i * 2 - 128 : 383 - (int)i * 2;
        work[256 + i] = (uint8_t)(int8_t)tri;
    }
}

static kh_status music_init(void) {
    kh_status s = kh_audio_write(KAGURA_AUDIO_MASTER_GAIN, 42);
    for (unsigned ch = 0; ch < 3 && s == KH_OK; ch++) {
        s = audio_write(ch, KAGURA_AUDIO_DUTY, ch == 0 ? 64 : (ch == 1 ? 128 : 32));
        if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_GAIN_L, ch == 2 ? 12 : 20);
        if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_GAIN_R, ch == 0 ? 12 : 20);
        if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET);
    }
    if (s == KH_OK) s = audio_write(3, KAGURA_AUDIO_NOISE_PERIOD_L, 96);
    if (s == KH_OK) s = audio_write(3, KAGURA_AUDIO_GAIN_L, 6);
    if (s == KH_OK) s = audio_write(3, KAGURA_AUDIO_GAIN_R, 6);
    if (s == KH_OK) s = audio_write(3, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET);
    for (unsigned ch = 4; ch < 6 && s == KH_OK; ch++) {
        s = audio_write(ch, KAGURA_AUDIO_LEN_LOG2, 8);
        if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_GAIN_L, ch == 4 ? 38 : 28);
        if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_GAIN_R, ch == 4 ? 28 : 38);
        if (s == KH_OK) s = audio_write(ch, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET);
    }
    make_waves();
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, work, 512);
    if (s == KH_OK) s = kh_audio_commit(100000);
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, work, 512);
    if (s == KH_OK) s = kh_audio_commit(100000);
    return s;
}

static kh_status music_tick(unsigned beat) {
    static const uint32_t chord[4][3] = {
        {45721,54401,68507}, {36336,45721,54401}, {54401,68507,81460}, {40730,51319,61022}
    };
    static const uint32_t melody[16] = {
        91447,108761,137014,162922,182889,162922,137014,108761,
        96889,121999,145145,182889,162922,145145,121999,108761
    };
    unsigned harmony = (beat / 8u) & 3u;
    kh_status s = audio_step(0, chord[harmony][0]);
    if (s == KH_OK) s = audio_step(1, chord[harmony][1]);
    if (s == KH_OK) s = audio_step(2, chord[harmony][2]);
    if (s == KH_OK) s = audio_step(4, melody[beat & 15u]);
    if (s == KH_OK) s = audio_step(5, chord[harmony][0] / 2u);
    if (s == KH_OK) s = audio_write(3, KAGURA_AUDIO_NOISE_PERIOD_L, (beat & 3u) == 0 ? 24 : 120);
    if (s == KH_OK) s = audio_write(3, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET);
    return s == KH_OK ? kh_audio_commit(100000) : s;
}

static void music_stop(void) {
    kh_status s = KH_OK;
    for (unsigned ch = 0; ch < KAGURA_AUDIO_CHANNELS && s == KH_OK; ch++) s = audio_write(ch, KAGURA_AUDIO_CONTROL, 0);
    if (s == KH_OK) kh_audio_commit(100000);
}

static bool stop_requested(void) {
    for (;;) {
        int c = getchar_timeout_us(0);
        if (c == PICO_ERROR_TIMEOUT) return false;
        // A CRLF terminal may leave the second newline behind after `show`.
        // Ignore line endings so the performance does not stop immediately.
        if (c != '\r' && c != '\n') return true;
    }
}

kh_status kagura_spectacular_demo(uint32_t seconds) {
    kh_status s = kh_wait_ready(2000000);
    uint8_t caps = 0, height = 240;
    if (s == KH_OK) s = kh_read_reg(KAGURA_REG_CAPS, &caps);
    if (s == KH_OK) s = kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT, &height);
    if (s == KH_OK) s = kh_clear_errors();
    if (s != KH_OK) return s;

    printf("SHOW loading moonlit parallax city...\n");
    make_patterns();
    s = kh_vram_write(KAGURA_VRAM_PATTERN_BASE, work, sizeof work);
    make_map();
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_MAP_BASE, work, KAGURA_VRAM_MAP_SIZE);
    make_palette(0);
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_PALETTE_BASE, work, 512);
    make_oam(0, height);
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_OAM_BASE, work, 512);
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_BACKDROP, 1);
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_DISPLAY_CTRL, KAGURA_DISPLAY_CTRL_DISPLAY_ENABLE |
                                      KAGURA_DISPLAY_CTRL_BG_ENABLE | KAGURA_DISPLAY_CTRL_SPR_ENABLE);
    if (s == KH_OK) s = set_raster(0, height, (caps & KAGURA_CAPS_RSCROLL) != 0);
    if (s == KH_OK) s = kh_commit(100000);
    if (s == KH_OK) s = music_init();
    if (s != KH_OK) return s;

    printf("SHOW GO — %s, press any key to stop\n", seconds ? "timed run" : "unlimited run");
    uint64_t end = seconds ? time_us_64() + (uint64_t)seconds * 1000000u : UINT64_MAX;
    unsigned frame = 0;
    while (time_us_64() < end) {
        make_palette(frame);
        s = kh_vram_write(KAGURA_VRAM_PALETTE_BASE, work, 512);
        make_oam(frame, height);
        if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_OAM_BASE, work, 512);
        if (s == KH_OK) s = set_raster(frame, height, (caps & KAGURA_CAPS_RSCROLL) != 0);
        if (s == KH_OK) s = kh_commit(100000);
        if (s == KH_OK && frame % 10u == 0) s = music_tick(frame / 10u);
        if (s != KH_OK || stop_requested()) break;
        frame++;
    }
    music_stop();
    if (s == KH_OK) s = kh_check_errors();
    printf("SHOW %s after %u frames\n", s == KH_OK ? "DONE" : "FAILED", frame);
    return s;
}
