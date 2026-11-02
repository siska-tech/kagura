// SPDX-License-Identifier: Apache-2.0
// Stage 2: the C desktop on the KAGURA-9 display, from SRAM (no_flash).
//
// Same loading procedure and safety model as main.c (stage 1): watchdog first,
// no flash code, no reboot-to-BOOTSEL paths. Transport is the repository's
// validated C TileFramebuffer (software/pico/tile_fb.c, tile_fb_io.c) over
// kagura_host.c, QSPI at 5 MHz with clk_sys 120 MHz as that driver requires.
// The 320x200 desktop occupies tfb tiles 0..999 (top placement); tiles
// 1000..1199 stay colour 0 and show BACKDROP (palette entry 0, the desk).
//
// Protocol (USB CDC, host tools/rp2040_hdmi_test.py):
//   host 'g'  -> KDHD_PREFLIGHT ... (register reads only, nothing written)
//   host 'w'  -> palette + tfb_initialize; host 'x' aborts without writes
//   per scene: KDHD_READY i name record -> host 'g' -> scene applied ->
//              KDHD_SCENE i name ... (CRCs, readback, ERROR_CODE) -> host 'n'
//   timing:    KDHD_TIME lines, KDHD_DONE -> host 'r' -> flash boot
// Any error prints KDHD_ERROR and reboots into flash without further writes.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hardware/clocks.h"
#include "hardware/structs/systick.h"
#include "hardware/sync.h"
#include "hardware/watchdog.h"
#include "kagura_host.h"
#include "pico/stdlib.h"
#include "tile_fb.h"
#include "hdmi_scenes.h"

#define PIN_IO0 2u   // as software/pico/main.c
#define PIN_SCK 6u
#define PIN_CS 7u
#define PIN_BUSY 8u
#define PIN_READY 9u
#define PIN_IRQ 10u
#define SAMPLES 64
#define WARM 4

static const kh_config config = {KH_QSPI, 2, PIN_IO0, PIN_SCK, PIN_CS, PIN_BUSY, PIN_READY, PIN_IRQ};
static tile_fb tfb;
static uint8_t readback[256];
static uint8_t tile_staging[KD_TILE_COLS * KD_TILE4_BYTES];   // static: frames nest inside scenes

uint64_t tfb_now_us(void) { return time_us_64(); }

extern char __StackBottom, __StackTop;
#define GUARD_WORD 0xC0DEFA11u
static uint32_t *stack_lo, *stack_hi;   // painted part of the stack

static void paint_stack(void) {
    uint32_t sp;
    __asm__ volatile("mov %0, sp" : "=r"(sp));
    stack_lo = (uint32_t *)(((uintptr_t)&__StackBottom + 64u) & ~3u);   // above the MPU guard
    stack_hi = (uint32_t *)((sp - 256u) & ~3u);
    for (uint32_t *p = stack_lo; p < stack_hi; p++) *p = GUARD_WORD;
}

static uint32_t stack_peak(void) {
    const uint32_t *p = stack_lo;
    while (p < stack_hi && *p == GUARD_WORD) p++;
    return (uint32_t)((uintptr_t)&__StackTop - (uintptr_t)p);
}

static void fail(const char *what, kh_status s) {
    uint8_t error = kh_last_error();
    kh_read_reg(KAGURA_REG_ERROR_CODE, &error);   // diagnostic read only
    printf("KDHD_ERROR %s status %d error_code 0x%02x\n", what, (int)s, error);
    stdio_flush();
    sleep_ms(200);
    watchdog_reboot(0, 0, 10);   // flash boot: MicroPython restores its console
    for (;;) tight_loop_contents();
}

static void wait_char(int want, int seconds) {
    for (int i = 0; i < seconds * 10; i++) {
        watchdog_update();
        int c = getchar_timeout_us(100000);
        if (c == want) return;
        if (c == 'x') fail("host abort", KH_OK);
    }
    fail("host timeout", KH_OK);
}

static bool to_tfb(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    (void)ctx;
    memcpy(tfb.buffer.bytes + first * 32u, data, count * 32u);
    memset(tfb.dirty + first, 1, count);
    return true;
}

typedef struct {
    uint32_t render_cycles, export_us, transfer_us, wait_us, flush_us, total_us;
    uint32_t tiles, bytes, runs;
} frame_stats;

static frame_stats last;

// Render pending damage, export dirty tiles into the tfb buffer, send them.
static void frame(void) {
    kd_tile4_stats ex;
    uint32_t t0 = time_us_32();
    uint32_t irq = save_and_disable_interrupts();
    uint32_t c0 = systick_hw->cvr;
    kd_desktop_render(&S.desk);
    uint32_t c1 = systick_hw->cvr;
    restore_interrupts(irq);
    uint32_t t1 = time_us_32();
    kd_tile4_flush(&S.desk.fb, 0, tile_staging, KD_TILE_COLS, to_tfb, NULL, &ex);
    uint32_t t2 = time_us_32();
    kh_status s = tfb_flush(&tfb, 0);
    uint32_t t3 = time_us_32();
    if (s != KH_OK) fail("tfb_flush", s);
    last.render_cycles = (t1 - t0) > 100000u ? (t1 - t0) * 120u : ((c0 - c1) & 0xFFFFFFu);
    last.export_us = t2 - t1;
    last.transfer_us = (uint32_t)tfb.last_flush.transfer_us;
    last.wait_us = (uint32_t)tfb.last_flush.wait_us;
    last.flush_us = t3 - t2;
    last.total_us = t3 - t0;
    last.tiles = tfb.last_flush.tiles;
    last.bytes = tfb.last_flush.bytes;
    last.runs = tfb.last_flush.runs;
    watchdog_update();
}

// CRC32 of the kd framebuffer, of its TILE4 export, of what was sent (tfb
// buffer) and of the patterns read back from the FPGA, plus ERROR_CODE.
static void verify(const char *tag, const char *name) {
    uint32_t crc_fb = crc32_update(0, S.desk.fb.px, KD_FB_BYTES), crc_kd = 0, crc_sent, crc_dev = 0;
    uint8_t tile[KD_TILE4_BYTES];
    for (unsigned t = 0; t < KD_TILES; t++) {
        kd_tile4_pack_tile(&S.desk.fb, t, tile);
        crc_kd = crc32_update(crc_kd, tile, sizeof tile);
    }
    crc_sent = crc32_update(0, tfb.buffer.bytes, TFB_BYTES);
    for (unsigned off = 0; off < TFB_BYTES; off += sizeof readback) {
        unsigned tile_no = off / 32u;
        uint32_t addr = tile_no < 1024 ? KAGURA_VRAM_PATTERN_BASE + off : KAGURA_VRAM_PATTERN_EXT_BASE + (off - 1024u * 32u);
        kh_status s = kh_vram_read(addr, readback, sizeof readback);
        if (s != KH_OK) fail("readback", s);
        crc_dev = crc32_update(crc_dev, readback, sizeof readback);
        watchdog_update();
    }
    uint32_t crc_sent_kd = crc32_update(0, tfb.buffer.bytes, KD_TILE4_TOTAL);
    uint8_t error = 0xFF;
    kh_status s = kh_read_reg(KAGURA_REG_ERROR_CODE, &error);
    if (s != KH_OK) fail("ERROR_CODE read", s);
    bool ok = crc_sent_kd == crc_kd && crc_dev == crc_sent && error == 0;
    printf("%s %s fb %08lx tile4 %08lx sent %08lx vram %08lx error_code 0x%02x %s\n", tag, name,
           (unsigned long)crc_fb, (unsigned long)crc_kd, (unsigned long)crc_sent, (unsigned long)crc_dev, error,
           ok ? "OK" : "MISMATCH");
    if (!ok) fail("verification", KH_OK);
}

static void show_full(void) {
    kd_fb_mark_dirty_all(&S.desk.fb);
    frame();
}

static int cmp_u32(const void *a, const void *b) {
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return x < y ? -1 : x > y;
}

static uint32_t samples[9][SAMPLES];

static void print_dist(const char *name, const char *metric, uint32_t *v) {
    qsort(v, SAMPLES, sizeof *v, cmp_u32);
    printf("KDHD_TIME %s %s n %d p50 %lu p95 %lu p99 %lu max %lu\n", name, metric, SAMPLES,
           (unsigned long)v[SAMPLES / 2], (unsigned long)v[SAMPLES * 95 / 100], (unsigned long)v[SAMPLES * 99 / 100],
           (unsigned long)v[SAMPLES - 1]);
}

static void measure(const workload *w) {
    w->setup();
    show_full();
    for (int i = -WARM; i < SAMPLES; i++) {
        if (w->pre) {
            w->pre(i);
            frame();
        }
        w->op(i);
        frame();
        if (i < 0) continue;
        samples[0][i] = last.render_cycles;
        samples[1][i] = last.export_us;
        samples[2][i] = last.transfer_us;
        samples[3][i] = last.wait_us;
        samples[4][i] = last.flush_us;
        samples[5][i] = last.total_us;
        samples[6][i] = last.tiles;
        samples[7][i] = last.bytes;
        samples[8][i] = last.runs;
    }
    static const char *const metrics[] = {"render_cycles", "export_us", "transfer_us", "fence_wait_us",
                                          "flush_us", "end_to_end_us", "tiles", "bytes", "runs"};
    for (int m = 0; m < 9; m++) print_dist(w->name, metrics[m], samples[m]);
    verify("KDHD_VERIFY", w->name);
}

int main(void) {
    watchdog_enable(8000, true);           // also clears the boot-to-RAM magic
    set_sys_clock_khz(120000, true);       // kagura_host.c: 12 PIO cycles per SCK
    paint_stack();
    systick_hw->rvr = 0xFFFFFFu;
    systick_hw->cvr = 0;
    systick_hw->csr = 5;
    stdio_init_all();
    for (int i = 0; i < 300 && !stdio_usb_connected(); i++) {
        watchdog_update();
        sleep_ms(100);
    }
    if (!stdio_usb_connected()) watchdog_reboot(0, 0, 10);
    wait_char('g', 60);

    // Preflight: reads only.
    kh_init(&config);
    uint8_t id[5] = {0}, status = 0, error = 0xFF, height = 0, count_l = 0, count_h = 0, display = 0;
    kh_status s = kh_wait_ready(KH_DEFAULT_TIMEOUT_US);
    if (s == KH_OK) s = kh_read(KAGURA_REG_ID0, true, id, sizeof id);
    if (s == KH_OK) s = kh_read_reg(KAGURA_REG_STATUS, &status);
    if (s == KH_OK) s = kh_read_reg(KAGURA_REG_ERROR_CODE, &error);
    if (s == KH_OK) s = kh_read_reg(KAGURA_REG_DISPLAY_CTRL, &display);
    if (s == KH_OK) s = kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT, &height);
    if (s == KH_OK) s = kh_ext_read(KAGURA_EXT_PATTERN_COUNT_L, &count_l);
    if (s == KH_OK) s = kh_ext_read(KAGURA_EXT_PATTERN_COUNT_H, &count_h);
    printf("KDHD_PREFLIGHT status_call %d id %02x%02x abi %u.%u caps 0x%02x status 0x%02x error_code 0x%02x "
           "display_ctrl 0x%02x height %u patterns %u clk_sys_khz %lu lanes %u sck_div %u\n",
           (int)s, id[0], id[1], id[2], id[3], id[4], status, error, display, height, count_l | count_h << 8,
           (unsigned long)frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLK_SYS), config.lanes, config.clkdiv);
    bool compatible = s == KH_OK && id[0] == KAGURA_ID0 && id[1] == KAGURA_ID1 && id[2] == 0 && id[3] == 6 &&
                      height == TFB_HEIGHT && (count_l | count_h << 8) == TFB_TILES && error == 0;
    printf("KDHD_COMPATIBLE %s\n", compatible ? "yes" : "no");
    if (!compatible) fail("preflight", s);
    wait_char('w', 60);   // the host checked the preflight line too

    // Palette bank 0 (applied by tfb_initialize's COMMIT), then the desktop.
    for (uint8_t i = 0; i < 16; i++) {
        uint8_t word[2] = {(uint8_t)kd_palette_rgb444[i], (uint8_t)(kd_palette_rgb444[i] >> 8)};
        s = kh_vram_write(KAGURA_VRAM_PALETTE_BASE + 2u * i, word, 2);
        if (s != KH_OK) fail("palette", s);
    }
    workloads_init();
    tfb_reset(&tfb, 0);
    scene_frame = frame;
    kd_scenes[0].apply();
    kd_desktop_render(&S.desk);
    kd_fb_mark_dirty_all(&S.desk.fb);
    kd_tile4_stats ex;
    kd_tile4_flush(&S.desk.fb, 0, tile_staging, KD_TILE_COLS, to_tfb, NULL, &ex);
    uint32_t t0 = time_us_32();
    s = tfb_initialize(&tfb, true);
    if (s != KH_OK) fail("tfb_initialize", s);
    printf("KDHD_INIT us %lu\n", (unsigned long)(time_us_32() - t0));

    for (unsigned k = 0; k < KD_SCENE_COUNT; k++) {
        const kd_scene *sc = &kd_scenes[k];
        printf("KDHD_READY %u %s %d\n", k, sc->name, sc->record);
        wait_char('g', 60);
        sleep_ms(300);
        if (k > 0) sc->apply();
        frame();
        printf("KDHD_FRAME %s render_cycles %lu export_us %lu transfer_us %lu fence_wait_us %lu end_to_end_us %lu "
               "tiles %lu bytes %lu runs %lu\n", sc->name, (unsigned long)last.render_cycles,
               (unsigned long)last.export_us, (unsigned long)last.transfer_us, (unsigned long)last.wait_us,
               (unsigned long)last.total_us, (unsigned long)last.tiles, (unsigned long)last.bytes,
               (unsigned long)last.runs);
        verify("KDHD_SCENE", sc->name);
        wait_char('n', 120);
    }

    for (unsigned k = 0; k < KD_WORKLOAD_COUNT; k++) measure(&workloads[k]);

    printf("KDHD_MEM stack_peak_bytes %lu stack_size %lu\n", (unsigned long)stack_peak(),
           (unsigned long)((uintptr_t)&__StackTop - (uintptr_t)&__StackBottom));
    printf("KDHD_DONE\n");
    for (int i = 0; i < 100; i++) {   // 'r' or 10 s
        watchdog_update();
        if (getchar_timeout_us(100000) == 'r') break;
    }
    stdio_flush();
    sleep_ms(50);
    watchdog_reboot(0, 0, 10);
    for (;;) tight_loop_contents();
}
