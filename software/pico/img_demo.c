// SPDX-License-Identifier: Apache-2.0
// Pseudo-256-colour picture demo (img_demo.h). The pixels live in the shared
// TileFramebuffer; the map then gives every cell its own palette, which a
// TileFramebuffer alone never does (it uses one palette for all cells).
#include "img_demo.h"

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "fb_bench.h"
#include "img_quant.h"
#include "img_scene.h"

#define FADE_FRAMES 24u
#define RECEIVE_TIMEOUT_US 2000000u

static iq_image image;

static kh_status palette_write(unsigned level) {   // all 16 palettes at level/16
    static uint8_t bytes[512];
    for (unsigned i = 0; i < 256; i++) {
        unsigned v = image.palette[i];
        v = ((v >> 8 & 15u) * level / 16u) << 8 | ((v >> 4 & 15u) * level / 16u) << 4 | (v & 15u) * level / 16u;
        bytes[2 * i] = (uint8_t)v;
        bytes[2 * i + 1] = (uint8_t)(v >> 8);
    }
    return kh_vram_write(KAGURA_VRAM_PALETTE_BASE, bytes, sizeof bytes);
}

// Same tile numbers as tfb_initialize wrote (so its upper-bit table stays
// valid), with each cell's palette in bits 13..10.
static kh_status map_write(void) {
    static uint8_t row[2 * TFB_COLUMNS];
    kh_status s = KH_OK;
    for (unsigned y = 0; s == KH_OK && y < TFB_ROWS; y++) {
        for (unsigned x = 0; x < TFB_COLUMNS; x++) {
            unsigned tile = y * TFB_COLUMNS + x;
            uint16_t word = (uint16_t)((tile & 1023u) | (unsigned)(image.cell[tile] & 15u) << 10);
            row[2 * x] = (uint8_t)word;
            row[2 * x + 1] = (uint8_t)(word >> 8);
        }
        s = kh_vram_write(KAGURA_VRAM_MAP_BASE + y * 128u, row, sizeof row);
    }
    return s;
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
    printf("IMG %s %s prepare_ms=%llu show_ms=%llu palettes_used=%u\n", s == KH_OK ? "DONE" : "FAILED",
           receive_image ? "received" : "generated", (unsigned long long)((t1 - t0) / 1000u),
           (unsigned long long)((time_us_64() - t1) / 1000u), used);
    return s;
}
