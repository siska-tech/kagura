// SPDX-License-Identifier: Apache-2.0
// Device half of the C TileFramebuffer: initialize and flush through
// kagura_host.h, following kagura/framebuffer.py step for step.
#include "tile_fb.h"

#include <string.h>

#define TFB_TIMEOUT_US 500000u

// A tag different from the *current* DONE_TAG, as device.fence() picks it:
// a locally cached counter could match a stale completion.
static kh_status fence_next(void) {
    uint8_t done;
    kh_status s = kh_read_reg(KAGURA_REG_DONE_TAG, &done);
    if (s == KH_OK) s = kh_fence((uint8_t)(done + 1u), TFB_TIMEOUT_US);
    return s != KH_OK ? s : kh_check_errors();
}

static kh_status write_map(const tile_fb *fb) {
    static uint8_t row[128], high[256];
    memset(high, 0, sizeof high);
    kh_status s = KH_OK;
    for (unsigned y = 0; s == KH_OK && y < 32; y++) {
        memset(row, 0, sizeof row);
        for (unsigned x = 0; y < TFB_ROWS && x < TFB_COLUMNS; x++) {
            unsigned tile = y * TFB_COLUMNS + x;
            uint16_t word = (uint16_t)((tile & 1023u) | (unsigned)fb->palette << 10);
            row[2 * x] = (uint8_t)word;
            row[2 * x + 1] = (uint8_t)(word >> 8);
            if (tile >= 1024) {
                unsigned index = y * 64 + x;
                high[index / 8] |= (uint8_t)(1u << (index % 8));
            }
        }
        s = kh_vram_write(KAGURA_VRAM_MAP_BASE + y * 128u, row, sizeof row);
    }
    return s != KH_OK ? s : kh_vram_write(KAGURA_VRAM_MAP_EXT_BASE, high, sizeof high);
}

kh_status tfb_initialize(tile_fb *fb, bool show) {
    fb->initialized = false;
    uint8_t id[5], height = 0, count_l = 0, count_h = 0;
    kh_status s = kh_read(KAGURA_REG_ID0, true, id, sizeof id);
    if (s == KH_OK) s = kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT, &height);
    if (s == KH_OK) s = kh_ext_read(KAGURA_EXT_PATTERN_COUNT_L, &count_l);
    if (s == KH_OK) s = kh_ext_read(KAGURA_EXT_PATTERN_COUNT_H, &count_h);
    if (s != KH_OK) return s;
    if (id[0] != KAGURA_ID0 || id[1] != KAGURA_ID1 || id[2] != 0 || id[3] != 6 ||
        height != TFB_HEIGHT || (count_l | count_h << 8) != TFB_TILES)
        return KH_BAD_ARGUMENT;   // no FPGA state changed

    s = kh_write_reg(KAGURA_REG_DISPLAY_CTRL, 0);
    if (s == KH_OK) s = kh_commit(TFB_TIMEOUT_US);
    memset(fb->dirty, 1, sizeof fb->dirty);
    if (s == KH_OK) s = write_map(fb);
    for (uint8_t reg = KAGURA_EXT_SCROLL_X_L; s == KH_OK && reg <= KAGURA_EXT_SCROLL_Y; reg++)
        s = kh_ext_write(reg, 0);
    if (s == KH_OK && (id[4] & KAGURA_CAPS_RSCROLL)) {
        s = kh_wait_status(KAGURA_STATUS_COMMIT_BUSY, 0, TFB_TIMEOUT_US);
        if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_RS_INDEX, 0);
        if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_RS_COUNT, 0);
    }
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_BACKDROP, (uint8_t)(fb->palette * 16u));
    if (s == KH_OK) s = fence_next();
    if (s == KH_OK) {
        fb->initialized = true;   // tfb_flush refuses otherwise
        s = tfb_flush(fb, 0);
        fb->initialized = false;
    }
    // COMMIT applies display/scroll/palette shadows, not pattern RAM.
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_DISPLAY_CTRL, show ? KAGURA_DISPLAY_CTRL_DISPLAY_ENABLE |
                                                                     KAGURA_DISPLAY_CTRL_BG_ENABLE : 0);
    if (s == KH_OK) s = kh_commit(TFB_TIMEOUT_US);
    if (s == KH_OK) s = kh_check_errors();
    if (s == KH_OK) {
        fb->initialized = true;
        return KH_OK;
    }
    memset(fb->dirty, 1, sizeof fb->dirty);
    // Best effort only; never replay the failed command.
    if (kh_write_reg(KAGURA_REG_DISPLAY_CTRL, 0) == KH_OK) kh_commit(TFB_TIMEOUT_US);
    return s;
}

static size_t find(const uint8_t *dirty, uint8_t value, size_t from) {
    const void *p = memchr(dirty + from, value, TFB_TILES - from);
    return p ? (size_t)((const uint8_t *)p - dirty) : TFB_TILES;
}

kh_status tfb_flush(tile_fb *fb, unsigned max_gap) {
    tfb_flush_stats *st = &fb->last_flush;
    memset(st, 0, sizeof *st);
    if (!fb->initialized || max_gap > TFB_MAX_GAP) return KH_BAD_ARGUMENT;
    uint64_t start = tfb_now_us();
    kh_status s = KH_OK;
    if (max_gap) {
        // Widen runs before any I/O so a failure never leaves gap tiles clean.
        for (size_t first = find(fb->dirty, 1, 0); first < TFB_TILES;) {
            size_t end = find(fb->dirty, 0, first);
            size_t following = end < TFB_TILES ? find(fb->dirty, 1, end) : TFB_TILES;
            if (following >= TFB_TILES) break;
            if (following - end <= max_gap) memset(fb->dirty + end, 1, following - end);
            first = following;
        }
    }
    for (size_t tile = 0; s == KH_OK && tile < TFB_TILES;) {
        size_t first = find(fb->dirty, 1, tile);
        if (first >= TFB_TILES) break;
        tile = find(fb->dirty, 0, first);
        size_t count = tile - first;
        st->runs++;
        st->bytes += (uint32_t)(count * 32u);
        st->writes += 1u + (first < 1024 && tile > 1024);
        uint64_t t0 = tfb_now_us();
        // Patterns 0..1023 at 0x0000, 1024..1199 at 0xB000.
        size_t split = first < 1024 ? (tile < 1024 ? tile : 1024) : first;
        if (split > first)
            s = kh_vram_write(KAGURA_VRAM_PATTERN_BASE + first * 32u, &fb->buffer.bytes[first * 32u], (split - first) * 32u);
        if (s == KH_OK && tile > split)
            s = kh_vram_write(KAGURA_VRAM_PATTERN_EXT_BASE + (split - 1024u) * 32u, &fb->buffer.bytes[split * 32u],
                              (tile - split) * 32u);
        uint64_t t1 = tfb_now_us();
        st->transfer_us += t1 - t0;
        if (s != KH_OK) break;
        st->fences++;
        s = fence_next();
        st->wait_us += tfb_now_us() - t1;
        if (s != KH_OK) break;
        // Only a confirmed run becomes clean.
        memset(fb->dirty + first, 0, count);
        st->tiles += (uint32_t)count;
    }
    st->total_us = tfb_now_us() - start;
    return s;
}
