// SPDX-License-Identifier: Apache-2.0
// PC harness for tile_fb.c / tile_fb_io.c, driven by test_tile_fb.py. The
// kagura_host.h calls are stubs that log every VRAM write ("W addr hex") and
// can fail the n-th VRAM write or FENCE. Commands, one per line on stdin:
//   reset | clean | pixel x y c | fill c | fill_rect x y w h c | hline x y w c
//   vline x y h c | rect x y w h c | line x0 y0 x1 y1 c | circle x y r c
//   mark_dirty x y w h | init | flush gap | failwrite n | failfence n | dump
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "tile_fb.h"

static tile_fb fb;
static uint8_t done_tag = 0x7f;
static int fail_write, fail_fence;   // 1 = the next call fails, 0 = never

uint64_t tfb_now_us(void) { return 0; }

kh_status kh_read(uint8_t offset, bool inc, uint8_t *data, size_t n) {
    (void)inc;
    static const uint8_t id[5] = {KAGURA_ID0, KAGURA_ID1, KAGURA_ABI_MAJOR, KAGURA_ABI_MINOR, KAGURA_CAPS_VALUE_FULL_PSRAM};
    if (offset != KAGURA_REG_ID0 || n != 5) return KH_BAD_ARGUMENT;
    memcpy(data, id, 5);
    return KH_OK;
}

kh_status kh_ext_read(uint8_t index, uint8_t *value) {
    *value = index == KAGURA_EXT_SCREEN_HEIGHT ? 240 : index == KAGURA_EXT_PATTERN_COUNT_L ? 1200 & 255
           : index == KAGURA_EXT_PATTERN_COUNT_H ? 1200 >> 8 : 0;
    return KH_OK;
}

kh_status kh_read_reg(uint8_t offset, uint8_t *value) {
    *value = offset == KAGURA_REG_DONE_TAG ? done_tag : 0;
    return KH_OK;
}

kh_status kh_write_reg(uint8_t offset, uint8_t value) { (void)offset; (void)value; return KH_OK; }
kh_status kh_ext_write(uint8_t index, uint8_t value) { (void)index; (void)value; return KH_OK; }
kh_status kh_commit(uint32_t timeout_us) { (void)timeout_us; return KH_OK; }
kh_status kh_check_errors(void) { return KH_OK; }
uint8_t kh_last_error(void) { return 0; }
kh_status kh_wait_status(uint8_t mask, uint8_t value, uint32_t timeout_us) {
    (void)mask; (void)value; (void)timeout_us;
    return KH_OK;
}

kh_status kh_vram_write(uint32_t addr, const uint8_t *data, size_t n) {
    if (fail_write && --fail_write == 0) { printf("W FAIL\n"); return KH_TIMEOUT_BUSY; }
    printf("W %x ", (unsigned)addr);
    for (size_t i = 0; i < n; i++) printf("%02x", data[i]);
    printf("\n");
    return KH_OK;
}

kh_status kh_fence(uint8_t tag, uint32_t timeout_us) {
    (void)timeout_us;
    if (tag != (uint8_t)(done_tag + 1u)) return KH_BAD_ARGUMENT;
    if (fail_fence && --fail_fence == 0) { printf("F FAIL\n"); return KH_TIMEOUT_STATUS; }
    done_tag = tag;
    printf("F\n");
    return KH_OK;
}

static void hex(const char *tag, const uint8_t *p, size_t n) {
    printf("%s ", tag);
    for (size_t i = 0; i < n; i++) printf("%02x", p[i]);
    printf("\n");
}

int main(void) {
    char line[256];
    tfb_reset(&fb, 0);
    while (fgets(line, sizeof line, stdin)) {
        char cmd[32];
        int a[5] = {0};
        int n = sscanf(line, "%31s %d %d %d %d %d", cmd, &a[0], &a[1], &a[2], &a[3], &a[4]);
        if (n < 1) continue;
        uint8_t c4 = (uint8_t)a[4], c3 = (uint8_t)a[3], c2 = (uint8_t)a[2];
        if (!strcmp(cmd, "reset")) tfb_reset(&fb, (uint8_t)a[0]);
        else if (!strcmp(cmd, "clean")) memset(fb.dirty, 0, sizeof fb.dirty);
        else if (!strcmp(cmd, "pixel")) tfb_pixel(&fb, a[0], a[1], c2);
        else if (!strcmp(cmd, "fill")) tfb_fill(&fb, (uint8_t)a[0]);
        else if (!strcmp(cmd, "fill_rect")) tfb_fill_rect(&fb, a[0], a[1], a[2], a[3], c4);
        else if (!strcmp(cmd, "hline")) tfb_hline(&fb, a[0], a[1], a[2], c3);
        else if (!strcmp(cmd, "vline")) tfb_vline(&fb, a[0], a[1], a[2], c3);
        else if (!strcmp(cmd, "rect")) tfb_rect(&fb, a[0], a[1], a[2], a[3], c4);
        else if (!strcmp(cmd, "line")) tfb_line(&fb, (int16_t)a[0], (int16_t)a[1], (int16_t)a[2], (int16_t)a[3], c4);
        else if (!strcmp(cmd, "circle")) tfb_circle(&fb, (int16_t)a[0], (int16_t)a[1], (uint16_t)a[2], c3);
        else if (!strcmp(cmd, "mark_dirty")) tfb_mark_dirty(&fb, a[0], a[1], a[2], a[3]);
        else if (!strcmp(cmd, "failwrite")) fail_write = a[0];
        else if (!strcmp(cmd, "failfence")) fail_fence = a[0];
        else if (!strcmp(cmd, "init")) printf("INIT %d\n", (int)tfb_initialize(&fb, true));
        else if (!strcmp(cmd, "flush")) {
            kh_status s = tfb_flush(&fb, (unsigned)a[0]);
            const tfb_flush_stats *st = &fb.last_flush;
            printf("FLUSH %d %u %u %u %u %u\n", (int)s, (unsigned)st->tiles, (unsigned)st->bytes,
                   (unsigned)st->runs, (unsigned)st->writes, (unsigned)st->fences);
        } else if (!strcmp(cmd, "dump")) {
            hex("BUF", fb.buffer.bytes, sizeof fb.buffer.bytes);
            hex("DIRTY", fb.dirty, sizeof fb.dirty);
        } else { fprintf(stderr, "unknown command %s\n", cmd); return 2; }
    }
    return 0;
}
