// SPDX-License-Identifier: Apache-2.0
// Pseudo-256-colour picture demo (img_demo.h). The pixels live in the shared
// TileFramebuffer; the map then gives every cell its own palette, which a
// TileFramebuffer alone never does (it uses one palette for all cells).
// Saved pictures live in PSRAM and come back by COPY alone.
#include "img_demo.h"

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "fb_bench.h"
#include "img_quant.h"
#include "img_scene.h"

#define FADE_FRAMES 24u
#define RECEIVE_TIMEOUT_US 2000000u

#define SLOT_MAP 0x9600u      // slot offsets, see img_demo.h
#define SLOT_FADE 0xA500u
#define PATTERN_LOW 32768u     // tiles 0..1023 at 0x0000, 1024..1199 at 0xB000
#define MAP_BYTES (TFB_ROWS * 128u)

static iq_image image;
static bool shown;             // image and kagura_fb.buffer hold the picture on screen
static uint32_t shown_crc;     // of kagura_fb.buffer then, so save notices other users
static int current = -1;       // slot on screen, -1 if none
static uint16_t saved;         // slots holding a picture

static const uint8_t *palette_bytes(unsigned level) {   // all 16 palettes at level/16
    static uint8_t bytes[512];
    for (unsigned i = 0; i < 256; i++) {
        unsigned v = image.palette[i];
        v = ((v >> 8 & 15u) * level / 16u) << 8 | ((v >> 4 & 15u) * level / 16u) << 4 | (v & 15u) * level / 16u;
        bytes[2 * i] = (uint8_t)v;
        bytes[2 * i + 1] = (uint8_t)(v >> 8);
    }
    return bytes;
}

static kh_status palette_write(unsigned level) {
    return kh_vram_write(KAGURA_VRAM_PALETTE_BASE, palette_bytes(level), 512);
}

// One 64-entry map row: the tile numbers tfb_initialize wrote (so its
// upper-bit table stays valid) with each cell's palette in bits 13..10;
// the 24 cells right of the screen stay 0, as tfb_initialize leaves them.
static const uint8_t *map_row(unsigned y) {
    static uint8_t row[128];
    memset(row, 0, sizeof row);
    for (unsigned x = 0; x < TFB_COLUMNS; x++) {
        unsigned tile = y * TFB_COLUMNS + x;
        uint16_t word = (uint16_t)((tile & 1023u) | (unsigned)(image.cell[tile] & 15u) << 10);
        row[2 * x] = (uint8_t)word;
        row[2 * x + 1] = (uint8_t)(word >> 8);
    }
    return row;
}

static kh_status map_write(void) {
    kh_status s = KH_OK;
    for (unsigned y = 0; s == KH_OK && y < TFB_ROWS; y++) s = kh_vram_write(KAGURA_VRAM_MAP_BASE + y * 128u, map_row(y), 128);
    return s;
}

static kh_status fence(void) {   // a tag other than the current DONE_TAG, as tile_fb_io.c
    uint8_t done;
    kh_status s = kh_read_reg(KAGURA_REG_DONE_TAG, &done);
    if (s == KH_OK) s = kh_fence((uint8_t)(done + 1u), 500000);
    return s != KH_OK ? s : kh_check_errors();
}

// The pixels are already in kagura_fb.buffer (all tiles dirty since reset).
static kh_status show(void) {
    kh_status s = kh_clear_errors();
    if (s == KH_OK) s = palette_write(0);   // tfb_initialize's COMMIT applies it
    if (s == KH_OK) {
        s = tfb_initialize(&kagura_fb, true);
        if (s == KH_BAD_ARGUMENT) printf("IMG FAIL needs a 480p ABI 0.6 bitstream with 1200 patterns\n");
    }
    if (s == KH_OK) s = map_write();
    for (unsigned f = 1; s == KH_OK && f <= FADE_FRAMES; f++) {
        s = palette_write(f * 16u / FADE_FRAMES);
        if (s == KH_OK) s = kh_commit(100000);   // applied at VBlank
    }
    return s == KH_OK ? kh_check_errors() : s;
}

static void stage(const char *name) {
    printf("IMG stage %s at %llu ms\n", name, (unsigned long long)(time_us_64() / 1000u));
}

static uint32_t crc32_update(uint32_t crc, uint8_t b) {
    crc ^= b;
    for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xedb88320u & -(crc & 1u));
    return crc;
}

static uint32_t buffer_crc(void) {
    uint32_t crc = 0xffffffffu;
    for (unsigned i = 0; i < TFB_BYTES; i++) crc = crc32_update(crc, kagura_fb.buffer.bytes[i]);
    return ~crc;
}

static int next_byte(uint32_t *crc) {
    int c = getchar_timeout_us(RECEIVE_TIMEOUT_US);
    if (c == PICO_ERROR_TIMEOUT) return -1;
    if (crc) *crc = crc32_update(*crc, (uint8_t)c);
    return c;
}

// Payload straight into the image and the framebuffer; nothing is shown
// unless the length, the CRC and every value check out.
static bool receive(void) {
    printf("IMG READY %u\n", IMG_PAYLOAD);
    const char *magic = IMG_MAGIC;
    unsigned matched = 0;
    while (matched < 4) {   // skips a stray line ending before the magic
        int c = next_byte(NULL);
        if (c < 0) { printf("IMG FAIL timeout before magic\n"); return false; }
        matched = c == magic[matched] ? matched + 1 : (c == magic[0] ? 1u : 0u);
    }
    uint32_t crc = 0xffffffffu;
    for (unsigned i = 0; i < IMG_PAYLOAD; i++) {
        int c = next_byte(&crc);
        if (c < 0) { printf("IMG FAIL timeout after %u bytes\n", i); return false; }
        if (i < 512) {
            unsigned w = i / 2;
            image.palette[w] = (uint16_t)(i & 1 ? (image.palette[w] & 0xffu) | (unsigned)c << 8 : (unsigned)c);
        } else if (i < 512 + 1200) {
            image.cell[i - 512] = (uint8_t)c;
        } else {
            kagura_fb.buffer.bytes[i - 1712] = (uint8_t)c;
        }
    }
    uint32_t sent = 0;
    for (unsigned i = 0; i < 4; i++) {
        int c = next_byte(NULL);
        if (c < 0) { printf("IMG FAIL timeout in CRC\n"); return false; }
        sent |= (uint32_t)c << (8 * i);
    }
    crc = ~crc;
    if (crc != sent) { printf("IMG FAIL crc32 %08lx expected %08lx\n", (unsigned long)crc, (unsigned long)sent); return false; }
    for (unsigned i = 0; i < 256; i++)
        if (image.palette[i] > 0x0fffu) { printf("IMG FAIL palette word %u\n", i); return false; }
    for (unsigned i = 0; i < 1200; i++)
        if (image.cell[i] > 15u) { printf("IMG FAIL cell %u palette %u\n", i, image.cell[i]); return false; }
    printf("IMG received crc32=%08lx\n", (unsigned long)crc);
    return true;
}

kh_status kagura_img_demo(bool receive_image) {
    shown = false;
    current = -1;
    tfb_reset(&kagura_fb, 0);
    uint64_t t0 = time_us_64();
    if (receive_image) {
        if (!receive()) return KH_OK;   // reported; the screen is unchanged
    } else {
        scene_init();
        iq_quantize(scene_rgb, NULL, 1, &image, kagura_fb.buffer.bytes, stage);
    }
    uint64_t t1 = time_us_64();
    unsigned used = 0;
    for (unsigned p = 0; p < 16; p++) {
        bool any = false;
        for (unsigned i = 0; i < 1200 && !any; i++) any = image.cell[i] == p;
        used += any;
    }
    kh_status s = show();
    if (s == KH_OK) {
        shown = true;
        shown_crc = buffer_crc();
    }
    printf("IMG %s %s prepare_ms=%llu show_ms=%llu palettes_used=%u\n", s == KH_OK ? "DONE" : "FAILED",
           receive_image ? "received" : "generated", (unsigned long long)((t1 - t0) / 1000u),
           (unsigned long long)((time_us_64() - t1) / 1000u), used);
    return s;
}

static bool have_psram(void) {
    uint8_t caps = 0;
    if (kh_read_reg(KAGURA_REG_CAPS, &caps) == KH_OK && (caps & KAGURA_CAPS_PSRAM)) return true;
    printf("IMG FAIL needs a PSRAM bitstream (CAPS 0x%02x)\n", caps);
    return false;
}

kh_status kagura_img_save(unsigned slot) {
    if (slot >= IMG_SLOTS) { printf("IMG FAIL slot 0..%u\n", IMG_SLOTS - 1); return KH_OK; }
    if (!shown || buffer_crc() != shown_crc) { printf("IMG FAIL show a picture first (imgdemo gen or recv)\n"); return KH_OK; }
    if (!have_psram()) return KH_OK;
    uint64_t t0 = time_us_64();
    const uint32_t base = IMG_SLOT_BASE + slot * IMG_SLOT_SIZE;
    kh_status s = kh_vram_write(base, kagura_fb.buffer.bytes, TFB_BYTES);
    for (unsigned y = 0; s == KH_OK && y < TFB_ROWS; y++) s = kh_vram_write(base + SLOT_MAP + y * 128u, map_row(y), 128);
    for (unsigned level = 0; s == KH_OK && level <= 16; level++)
        s = kh_vram_write(base + SLOT_FADE + level * 512u, palette_bytes(level), 512);
    if (s == KH_OK) s = fence();   // later COPYs read what was written
    if (s == KH_OK) {
        saved |= (uint16_t)(1u << slot);
        current = (int)slot;
    }
    printf("IMG %s slot=%u ms=%llu\n", s == KH_OK ? "SAVED" : "FAILED", slot, (unsigned long long)((time_us_64() - t0) / 1000u));
    return s;
}

// The palettes of `slot` at one brightness, applied at the next VBlank.
static kh_status slot_palette(unsigned slot, unsigned level) {
    kh_status s = kh_copy(IMG_SLOT_BASE + slot * IMG_SLOT_SIZE + SLOT_FADE + level * 512u, KAGURA_VRAM_PALETTE_BASE, 512);
    return s == KH_OK ? kh_commit(100000) : s;
}

static bool key_pressed(void) {
    for (int c; (c = getchar_timeout_us(0)) != PICO_ERROR_TIMEOUT;)
        if (c != '\r' && c != '\n') return true;   // ignore the command's line ending
    return false;
}

kh_status kagura_img_slide(unsigned seconds, unsigned hold_ms) {
    if (!saved) { printf("IMG FAIL no saved slot (imgdemo save n)\n"); return KH_OK; }
    if (current < 0) { printf("IMG FAIL show a saved picture first (imgdemo save n)\n"); return KH_OK; }
    if (!have_psram()) return KH_OK;
    shown = false;   // from here the screen no longer matches kagura_fb.buffer
    printf("IMG SLIDE slots=0x%04x hold_ms=%u, press any key to stop\n", saved, hold_ms);
    const uint64_t end = seconds ? time_us_64() + (uint64_t)seconds * 1000000u : UINT64_MAX;
    kh_status s = KH_OK;
    unsigned changes = 0;
    bool stop = false;
    while (s == KH_OK && !stop && time_us_64() < end) {
        uint64_t until = time_us_64() + (uint64_t)hold_ms * 1000u;
        while (!(stop = key_pressed()) && time_us_64() < until && time_us_64() < end) sleep_ms(10);
        if (stop || time_us_64() >= end) break;
        unsigned next = (unsigned)current;
        do next = (next + 1u) % IMG_SLOTS; while (!(saved & (1u << next)));
        for (int level = 15; s == KH_OK && level >= 0; level--) s = slot_palette((unsigned)current, (unsigned)level);
        // Patterns and map change while every palette is black.
        const uint32_t base = IMG_SLOT_BASE + next * IMG_SLOT_SIZE;
        uint64_t t0 = time_us_64();
        if (s == KH_OK) s = kh_copy(base, KAGURA_VRAM_PATTERN_BASE, PATTERN_LOW);
        if (s == KH_OK) s = kh_copy(base + PATTERN_LOW, KAGURA_VRAM_PATTERN_EXT_BASE, TFB_BYTES - PATTERN_LOW);
        if (s == KH_OK) s = kh_copy(base + SLOT_MAP, KAGURA_VRAM_MAP_BASE, MAP_BYTES);
        if (s == KH_OK) s = fence();
        uint64_t copy_us = time_us_64() - t0;
        for (unsigned level = 1; s == KH_OK && level <= 16; level++) s = slot_palette(next, level);
        if (s == KH_OK) {
            current = (int)next;
            changes++;
            printf("IMG slot=%u copy_us=%llu\n", next, (unsigned long long)copy_us);
        }
    }
    printf("IMG SLIDE %s after %u changes\n", s == KH_OK ? "DONE" : "FAILED", changes);
    return s;
}
