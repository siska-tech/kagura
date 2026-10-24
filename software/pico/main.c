// SPDX-License-Identifier: Apache-2.0
// KAGURA host diagnostic and VRAM uploader for Raspberry Pi Pico / Pico W.
// Talks to a Tang Nano 9K running the spi/qspi bitstream (wiring in README.md)
// and is driven by line commands over USB CDC; `help` lists them. `diag`
// runs the M2 end-to-end check through the public register interface.
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hardware/clocks.h"
#include "pico/stdlib.h"
#include "kagura_host.h"

#define PIN_IO0 2u    // IO0..IO3 = GP2..GP5
#define PIN_SCK 6u
#define PIN_CS 7u
#define PIN_BUSY 8u
#define PIN_READY 9u
#define PIN_IRQ 10u

static kh_config config = {KH_SPI, 4, PIN_IO0, PIN_SCK, PIN_CS, PIN_BUSY, PIN_READY, PIN_IRQ};
static int failures;
static uint8_t buf[4096], back[4096];

static const char *status_name(kh_status s) {
    switch (s) {
        case KH_OK: return "ok";
        case KH_TIMEOUT_READY: return "READY timeout";
        case KH_TIMEOUT_BUSY: return "BUSY timeout";
        case KH_TIMEOUT_STATUS: return "STATUS timeout";
        case KH_DEVICE_ERROR: return "ERROR_CODE set";
        default: return "bad argument";
    }
}

static void report(const char *step, bool ok, const char *fmt, ...) {
    va_list ap;
    printf("%s %s: ", ok ? "PASS" : "FAIL", step);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    if (!ok) failures++;
}

// Returns false (and reports) when a driver call failed.
static bool check(const char *step, kh_status s) {
    if (s == KH_OK) return true;
    if (s == KH_DEVICE_ERROR) report(step, false, "%s 0x%02x", status_name(s), kh_last_error());
    else report(step, false, "%s", status_name(s));
    return false;
}

static void apply_config(void) {
    kh_deinit();
    kh_init(&config);
}

static uint32_t lfsr = 0x1234567u;
static uint8_t next_random(void) {
    lfsr ^= lfsr << 13; lfsr ^= lfsr >> 17; lfsr ^= lfsr << 5;
    return (uint8_t)lfsr;
}

static uint32_t crc32(const uint8_t *p, size_t n) {
    uint32_t c = 0xffffffffu;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & -(c & 1u));
    }
    return ~c;
}

static void print_rate(const char *what, size_t bytes, uint64_t us) {
    printf("  %s: %u bytes in %llu us (%.1f KB/s)\n", what, (unsigned)bytes, (unsigned long long)us,
           us ? bytes * 1000.0 / us : 0.0);
}

static void palette_word(uint8_t index, uint16_t rgb444, kh_status *s) {
    uint8_t w[2] = {(uint8_t)rgb444, (uint8_t)(rgb444 >> 8)};
    if (*s == KH_OK) *s = kh_vram_write(KAGURA_VRAM_PALETTE_BASE + 2u * index, w, 2);
}

static void oam_entry(uint8_t n, int x, int y, uint16_t tile, uint8_t palette, uint8_t attr, kh_status *s) {
    uint8_t e[8] = {(uint8_t)x, (uint8_t)((x >> 8) & 3), (uint8_t)y, (uint8_t)((y >> 8) & 3),
                    (uint8_t)tile, (uint8_t)(((tile >> 8) & 3) | (palette << 2)), attr, 0};
    if (*s == KH_OK) *s = kh_vram_write(KAGURA_VRAM_OAM_BASE + 8u * n, e, 8);
}

static void diag(void) {
    failures = 0;
    kh_stats *st = kh_get_stats();
    memset(st, 0, sizeof *st);
    printf("DIAG %s, SCK %.2f MHz\n", config.lanes == KH_QSPI ? "QSPI" : "SPI", 10.0 / config.clkdiv);

    // 1. READY, then identification through an INC read (offsets 18..1C).
    if (!check("ready", kh_wait_ready(2000000))) { printf("DIAG FAIL %d\n", failures); return; }
    uint8_t id[5];
    if (!check("id", kh_read(KAGURA_REG_ID0, true, id, 5))) { printf("DIAG FAIL %d\n", failures); return; }
    bool wide = id[4] & KAGURA_CAPS_WIDE;
    report("id", id[0] == KAGURA_ID0 && id[1] == KAGURA_ID1 && id[2] == KAGURA_ABI_MAJOR && id[3] == KAGURA_ABI_MINOR &&
           (id[4] == KAGURA_CAPS_VALUE_FULL || id[4] == KAGURA_CAPS_VALUE_WIDE),
           "ID %02x %02x ABI %u.%u CAPS 0x%02x", id[0], id[1], id[2], id[3], id[4]);
    if (config.lanes == KH_SPI)
        report("fifo-header", (kh_last_fifo_status() & KAGURA_FIFO_STATUS_FREE_MASK) == 32,
               "FIFO_STATUS in header 0x%02x", kh_last_fifo_status());
    uint8_t height = 0;
    if (check("screen-height", kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT, &height)))
        report("screen-height", height == (wide ? KAGURA_EXT_SCREEN_HEIGHT_WIDE : KAGURA_EXT_SCREEN_HEIGHT_FULL),
               "%u lines", height);
    check("clear-errors", kh_clear_errors());

    // 2. Plain register write/read-back.
    static const uint8_t patterns[] = {0x00, 0xff, 0xa5, 0x5a, 0x01, 0x80};
    bool regs_ok = true;
    for (size_t i = 0; i < sizeof patterns; i++) {
        uint8_t v = 0;
        if (!check("register", kh_write_reg(KAGURA_REG_FILL_VALUE, patterns[i])) ||
            !check("register", kh_read_reg(KAGURA_REG_FILL_VALUE, &v))) { regs_ok = false; break; }
        if (v != patterns[i]) { regs_ok = false; report("register", false, "FILL_VALUE wrote %02x read %02x", patterns[i], v); break; }
    }
    if (regs_ok) report("register", true, "FILL_VALUE write/read %u patterns", (unsigned)sizeof patterns);

    // 3. VRAM write and read-back in the last 64 patterns (0x7800..0x7FFF).
    const uint32_t vaddr = KAGURA_VRAM_PATTERN_BASE + KAGURA_VRAM_PATTERN_SIZE - 2048u;
    for (size_t i = 0; i < 2048; i++) buf[i] = next_random();
    uint64_t t0 = time_us_64();
    bool vram_ok = check("vram-write", kh_vram_write(vaddr, buf, 2048));
    uint64_t t_write = time_us_64() - t0;
    t0 = time_us_64();
    if (vram_ok) vram_ok = check("vram-read", kh_vram_read(vaddr, back, 256));
    uint64_t t_read = time_us_64() - t0;
    if (vram_ok) {
        size_t bad = 0;
        for (size_t i = 0; i < 256; i++) bad += back[i] != buf[i];
        report("vram", bad == 0, "2048 bytes written, first 256 read back, %u mismatches", (unsigned)bad);
        print_rate("VRAM write", 2048, t_write);
        print_rate("VRAM read (READ_REQUEST per byte)", 256, t_read);
    }

    // 4. FILL then FENCE, checked at both ends of the range.
    if (check("fill", kh_fill(vaddr, 1024, 0x3c)) && check("fence", kh_fence(0x5a, 200000))) {
        uint8_t first = 0, last = 0;
        if (check("fill", kh_vram_read(vaddr, &first, 1)) && check("fill", kh_vram_read(vaddr + 1023, &last, 1)))
            report("fill", first == 0x3c && last == 0x3c, "1024 bytes of 0x3c, ends %02x %02x, FENCE tag 5a", first, last);
    }

    // 5. Backdrop and a 16x16 sprite moved through COMMIT, one per frame.
    kh_status s = KH_OK;
    palette_word(0, 0x036, &s);                 // backdrop: dark teal
    palette_word(16 + 1, 0xfc0, &s);            // sprite palette 1, colour 1: amber
    memset(buf, 0x11, 128);                     // tiles 1020..1023 solid colour 1
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_PATTERN_BASE + 32u * 1020u, buf, 128);
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_BACKDROP, 0);
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_DISPLAY_CTRL, KAGURA_DISPLAY_CTRL_DISPLAY_ENABLE |
                                     KAGURA_DISPLAY_CTRL_BG_ENABLE | KAGURA_DISPLAY_CTRL_SPR_ENABLE);
    if (check("display", s)) {
        uint8_t f0 = 0, f1 = 0;
        kh_read_reg(KAGURA_REG_FRAME_COUNT_L, &f0);
        t0 = time_us_64();
        int frames = 120, done = 0;
        for (; done < frames; done++) {
            oam_entry(0, 40 + 2 * done, height / 2 - 8, 1020, 1, 0x03, &s);  // enable | size16
            if (s == KH_OK) s = kh_commit(100000);
            if (!check("sprite", s)) break;
        }
        uint64_t dt = time_us_64() - t0;
        kh_read_reg(KAGURA_REG_FRAME_COUNT_L, &f1);
        if (done == frames)
            report("sprite", true, "%d COMMITs in %llu ms, FRAME_COUNT +%u (check: amber square moves right on teal)",
                   frames, (unsigned long long)(dt / 1000), (uint8_t)(f1 - f0));
    }

    // 6. Audio: 440Hz pulse on ch0 for one second.
    uint32_t step = 153791u;   // round(440 * 2^24 / 48000), docs/audio-spec.md
    uint8_t ch0[] = {KAGURA_AUDIO_STEP_L, (uint8_t)step, KAGURA_AUDIO_STEP_M, (uint8_t)(step >> 8),
                     KAGURA_AUDIO_STEP_H, (uint8_t)(step >> 16), KAGURA_AUDIO_DUTY, 128,
                     KAGURA_AUDIO_GAIN_L, 64, KAGURA_AUDIO_GAIN_R, 64,
                     KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE};
    s = KH_OK;
    for (size_t i = 0; s == KH_OK && i < sizeof ch0; i += 2) s = kh_audio_write(KAGURA_AUDIO_INDEX(0, ch0[i]), ch0[i + 1]);
    if (s == KH_OK) s = kh_audio_commit(100000);
    if (check("audio", s)) {
        sleep_ms(1000);
        s = kh_audio_write(KAGURA_AUDIO_INDEX(0, KAGURA_AUDIO_CONTROL), 0);
        if (s == KH_OK) s = kh_audio_commit(100000);
        uint8_t ast = 0xff;
        if (s == KH_OK) s = kh_audio_read(KAGURA_AUDIO_STATUS, &ast);
        if (check("audio", s))
            report("audio", (ast & (KAGURA_AUDIO_STATUS_FIFO_UNDERFLOW | KAGURA_AUDIO_STATUS_OVERFLOW)) == 0,
                   "440Hz on ch0 for 1s, AUDIO_STATUS 0x%02x (check: tone heard)", ast);
    }

    // 7. VBLANK IRQ on the /IRQ pin: assert, then release after W1C.
    s = kh_write_reg(KAGURA_REG_IRQ_STATUS, 0xff);
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_IRQ_ENABLE, KAGURA_IRQ_STATUS_VBLANK);
    if (check("irq", s)) {
        absolute_time_t end = make_timeout_time_ms(50);
        while (!kh_irq_asserted() && !time_reached(end)) tight_loop_contents();
        bool asserted = kh_irq_asserted();
        uint8_t irq_status = 0;
        kh_write_reg(KAGURA_REG_IRQ_ENABLE, 0);
        kh_read_reg(KAGURA_REG_IRQ_STATUS, &irq_status);
        kh_write_reg(KAGURA_REG_IRQ_STATUS, 0xff);
        sleep_us(10);
        report("irq", asserted && (irq_status & KAGURA_IRQ_STATUS_VBLANK) && !kh_irq_asserted(),
               "/IRQ asserted %d, IRQ_STATUS 0x%02x, released after W1C %d", asserted, irq_status, !kh_irq_asserted());
    }

    // 8. Queue pressure: short FILLs back to back plus a long stream, no FIFO_FULL.
    uint64_t waits_before = st->busy_waits;
    s = KH_OK;
    for (int i = 0; s == KH_OK && i < 64; i++) s = kh_fill(vaddr + 16u * i, 16, (uint8_t)i);
    for (size_t i = 0; i < 4096; i++) buf[i] = (uint8_t)i;
    if (s == KH_OK) s = kh_vram_write(vaddr - 4096u, buf, 4096);
    if (s == KH_OK) s = kh_fence(0xa5, 500000);
    if (check("busy", s)) {
        uint8_t mid = 0;
        if (check("busy", kh_vram_read(vaddr - 4096u + 1234u, &mid, 1)))
            report("busy", mid == (uint8_t)1234u, "64 FILLs + 4096-byte stream, BUSY waits %llu, read-back %02x",
                   (unsigned long long)(st->busy_waits - waits_before), mid);
    }

    // 9. Nothing left in ERROR_CODE.
    uint8_t e = 0xff;
    if (check("errors", kh_read_reg(KAGURA_REG_ERROR_CODE, &e))) report("errors", e == 0, "ERROR_CODE 0x%02x", e);
    printf("  stats: %llu bytes, %llu transactions, %llu BUSY waits (%llu us, sampled by software)\n",
           (unsigned long long)st->bytes_sent, (unsigned long long)st->transactions,
           (unsigned long long)st->busy_waits, (unsigned long long)st->busy_wait_us);
    printf("  check board LED2 (led_n[1], adapter `late`): it must stay off\n");
    printf(failures ? "DIAG FAIL %d\n" : "DIAG PASS\n", failures);
}

// Long-run load: 64 registered sprites (16 on one line band) moved by COMMIT
// every frame, all six audio voices playing, and once a second a 1KB random
// VRAM write with a 32-byte read-back sample. Errors are counted and cleared,
// not fatal, so an hour-long run reports how often each one happened.
static void soak(unsigned minutes) {
    kh_stats *st = kh_get_stats();
    memset(st, 0, sizeof *st);
    printf("SOAK %s, SCK %.2f MHz, %u min (any key stops)\n", config.lanes == KH_QSPI ? "QSPI" : "SPI",
           10.0 / config.clkdiv, minutes);
    if (!check("soak", kh_wait_ready(2000000))) { printf("SOAK FAIL\n"); return; }
    uint8_t height = 240;
    kh_ext_read(KAGURA_EXT_SCREEN_HEIGHT, &height);
    kh_clear_errors();

    // Display: backdrop, sprite palette 1 colours 1..3, tiles 1020..1023 striped.
    kh_status s = KH_OK;
    palette_word(0, 0x013, &s);
    palette_word(16 + 1, 0xfc0, &s);
    palette_word(16 + 2, 0x0cf, &s);
    palette_word(16 + 3, 0xf4a, &s);
    for (int i = 0; i < 128; i++) buf[i] = (uint8_t)(0x11 * (1 + (i / 4) % 3));
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_PATTERN_BASE + 32u * 1020u, buf, 128);
    if (s == KH_OK) s = kh_ext_write(KAGURA_EXT_BACKDROP, 0);
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_DISPLAY_CTRL, KAGURA_DISPLAY_CTRL_DISPLAY_ENABLE |
                                     KAGURA_DISPLAY_CTRL_BG_ENABLE | KAGURA_DISPLAY_CTRL_SPR_ENABLE);
    // Audio: three pulses, noise and two wavetables at low gain.
    for (int i = 0; i < 256; i++) buf[i] = (uint8_t)(int8_t)(i < 128 ? i - 64 : 191 - i);   // triangle
    for (int i = 0; i < 256; i++) buf[256 + i] = (uint8_t)(int8_t)(i < 128 ? 48 : -48);     // square
    static const uint32_t steps[6] = {153791u, 193771u, 230456u, 0, 76896u, 115344u};       // A4 C#5 E5 - A3 E4
    for (int bank = 0; s == KH_OK && bank < 2; bank++) {   // fill both wave banks (docs/audio-spec.md)
        s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, buf, 512);
        for (int c = 0; s == KH_OK && c < 6; c++) {
            uint8_t regs[] = {KAGURA_AUDIO_STEP_L, (uint8_t)steps[c], KAGURA_AUDIO_STEP_M, (uint8_t)(steps[c] >> 8),
                              KAGURA_AUDIO_STEP_H, (uint8_t)(steps[c] >> 16), KAGURA_AUDIO_DUTY, 96,
                              KAGURA_AUDIO_GAIN_L, 24, KAGURA_AUDIO_GAIN_R, 24, KAGURA_AUDIO_LEN_LOG2, 8,
                              KAGURA_AUDIO_NOISE_PERIOD_L, 40, KAGURA_AUDIO_NOISE_PERIOD_H, 0,
                              KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE};
            for (size_t i = 0; s == KH_OK && i < sizeof regs; i += 2) s = kh_audio_write(KAGURA_AUDIO_INDEX(c, regs[i]), regs[i + 1]);
        }
        if (s == KH_OK) s = kh_audio_commit(100000);
    }
    if (!check("soak-setup", s)) { printf("SOAK FAIL\n"); return; }

    uint64_t start = time_us_64(), end = start + (uint64_t)minutes * 60000000u, next_report = start + 10000000u;
    uint64_t next_vram = start + 1000000u;
    unsigned long frames = 0, vram_checks = 0, mismatches = 0, driver_failures = 0, ready_drops = 0, audio_flags = 0;
    unsigned long error_bits[8] = {0};
    const uint32_t scratch = KAGURA_VRAM_PATTERN_BASE + 32u * 960u;   // patterns 960..1019
    uint8_t oam[64 * 8];
    for (;;) {
        // 64 sprites: 16 on a band at mid-screen (line limit), the rest spread above and below.
        for (int n = 0; n < 64; n++) {
            int x = (int)((n * 20 + frames * (1 + n % 3)) % 352) - 16;
            int y = n < 16 ? height / 2 - 8 : (int)((n * 37 + frames) % (height + 16)) - 16;
            uint8_t e[8] = {(uint8_t)x, (uint8_t)((x >> 8) & 3), (uint8_t)y, (uint8_t)((y >> 8) & 3),
                            (uint8_t)1020, (uint8_t)(3 | (1 << 2)), 0x03, 0};
            memcpy(&oam[8 * n], e, 8);
        }
        s = kh_vram_write(KAGURA_VRAM_OAM_BASE, oam, sizeof oam);
        if (s == KH_OK) s = kh_commit(100000);
        frames++;
        if (s != KH_OK) {
            driver_failures++;
            if (s == KH_DEVICE_ERROR)
                for (int b = 0; b < 8; b++) if (kh_last_error() & (1u << b)) error_bits[b]++;
            kh_clear_errors();
        }
        if (!kh_ready_pin()) { ready_drops++; kh_wait_ready(2000000); }
        uint64_t now = time_us_64();
        if (now >= next_vram) {
            next_vram += 1000000u;
            for (int i = 0; i < 1024; i++) buf[i] = next_random();
            uint32_t off = (uint32_t)(next_random() % (1024u - 32u));
            s = kh_vram_write(scratch, buf, 1024);
            if (s == KH_OK) s = kh_vram_read(scratch + off, back, 32);
            if (s == KH_OK) { vram_checks++; for (int i = 0; i < 32; i++) mismatches += back[i] != buf[off + i]; }
            else { driver_failures++; kh_clear_errors(); }
            uint8_t ast = 0;
            if (kh_audio_read(KAGURA_AUDIO_STATUS, &ast) == KH_OK &&
                (ast & (KAGURA_AUDIO_STATUS_FIFO_UNDERFLOW | KAGURA_AUDIO_STATUS_OVERFLOW))) {
                audio_flags++;
                kh_audio_write(KAGURA_AUDIO_ERROR_CLEAR, KAGURA_AUDIO_ERROR_CLEAR_FIFO_UNDERFLOW | KAGURA_AUDIO_ERROR_CLEAR_OVERFLOW);
            }
        }
        bool stop = getchar_timeout_us(0) != PICO_ERROR_TIMEOUT || now >= end;
        if (now >= next_report || stop) {
            next_report += 10000000u;
            printf("  %4llus frames %lu (%.1f/s) vram-checks %lu mismatches %lu driver-failures %lu ready-drops %lu "
                   "audio-flags %lu busy-waits %llu errors[b0..7] %lu %lu %lu %lu %lu %lu %lu %lu\n",
                   (unsigned long long)((now - start) / 1000000u), frames, frames * 1e6 / (double)(now - start),
                   vram_checks, mismatches, driver_failures, ready_drops, audio_flags,
                   (unsigned long long)st->busy_waits, error_bits[0], error_bits[1], error_bits[2], error_bits[3],
                   error_bits[4], error_bits[5], error_bits[6], error_bits[7]);
        }
        if (stop) break;
    }
    for (int c = 0; c < 6; c++) kh_audio_write(KAGURA_AUDIO_INDEX(c, KAGURA_AUDIO_CONTROL), 0);
    kh_audio_commit(100000);
    bool ok = mismatches == 0 && driver_failures == 0 && ready_drops == 0 && audio_flags == 0;
    printf(ok ? "SOAK PASS\n" : "SOAK FAIL\n");
    printf("  check board LED2 (led_n[1], adapter `late`): it must stay off\n");
}

// `w <addr> <len>` then len raw bytes; `c <addr> <len>` reads back and prints CRC32.
static void upload(uint32_t addr, size_t len) {
    if (len == 0 || len > sizeof buf) { printf("ERR length 1..%u\n", (unsigned)sizeof buf); return; }
    printf("READY %u\n", (unsigned)len);
    for (size_t i = 0; i < len; i++) {
        int c = getchar_timeout_us(2000000);
        if (c == PICO_ERROR_TIMEOUT) { printf("ERR timeout after %u bytes\n", (unsigned)i); return; }
        buf[i] = (uint8_t)c;
    }
    uint64_t t0 = time_us_64();
    kh_status s = kh_vram_write(addr, buf, len);
    uint64_t dt = time_us_64() - t0;
    if (s != KH_OK) printf("ERR %s 0x%02x\n", status_name(s), kh_last_error());
    else printf("OK %u %llu %08lx\n", (unsigned)len, (unsigned long long)dt, (unsigned long)crc32(buf, len));
}

static void readback(uint32_t addr, size_t len) {
    if (len == 0 || len > sizeof back) { printf("ERR length 1..%u\n", (unsigned)sizeof back); return; }
    uint64_t t0 = time_us_64();
    kh_status s = kh_vram_read(addr, back, len);
    uint64_t dt = time_us_64() - t0;
    if (s != KH_OK) printf("ERR %s 0x%02x\n", status_name(s), kh_last_error());
    else printf("CRC %u %llu %08lx\n", (unsigned)len, (unsigned long long)dt, (unsigned long)crc32(back, len));
}

static void info(void) {
    uint8_t id[5] = {0}, st = 0, fifo = 0, err = 0;
    kh_read(KAGURA_REG_ID0, true, id, 5);
    kh_read_reg(KAGURA_REG_STATUS, &st);
    kh_read_reg(KAGURA_REG_FIFO_STATUS, &fifo);
    kh_read_reg(KAGURA_REG_ERROR_CODE, &err);
    printf("mode %s, SCK %.2f MHz, READY %d, /IRQ %s\n", config.lanes == KH_QSPI ? "qspi" : "spi",
           10.0 / config.clkdiv, kh_ready_pin(), kh_irq_asserted() ? "low" : "high");
    printf("ID %02x %02x ABI %u.%u CAPS 0x%02x STATUS 0x%02x FIFO_STATUS 0x%02x ERROR_CODE 0x%02x\n",
           id[0], id[1], id[2], id[3], id[4], st, fifo, err);
}

static void help(void) {
    printf("commands:\n"
           "  info                 ID, ABI, CAPS, STATUS, pins\n"
           "  diag                 end-to-end check (ID, registers, VRAM, FILL/FENCE, sprite, audio, IRQ, BUSY)\n"
           "  soak [min]           long run (default 60): 64 sprites, 6 voices, VRAM write/verify; counts errors\n"
           "  mode spi|qspi        must match the bitstream (build-nano9k.tcl spi / qspi)\n"
           "  div <n>              SCK = 10MHz / n (1..250, default 4)\n"
           "  rd <off> [n]         read n registers from offset (hex), INC\n"
           "  wr <off> <val>       write one register (hex)\n"
           "  w <addr> <len>       upload len raw bytes to VRAM (hex addr), replies READY then OK len us crc32\n"
           "  c <addr> <len>       read VRAM back, replies CRC len us crc32\n"
           "  clear                clear ERROR_CODE and IRQ.ERROR\n");
}

static bool read_line(char *line, size_t size) {
    size_t n = 0;
    for (;;) {
        int c = getchar_timeout_us(100000);
        if (c == PICO_ERROR_TIMEOUT) continue;
        if (c == '\r' || c == '\n') { if (n) break; continue; }
        if (n + 1 < size) line[n++] = (char)c;
    }
    line[n] = 0;
    return true;
}

int main(void) {
    set_sys_clock_khz(120000, true);   // 12 PIO cycles per SCK -> 10MHz at div 1
    stdio_init_all();
    kh_init(&config);
    char line[96];
    for (;;) {
        read_line(line, sizeof line);
        char *cmd = strtok(line, " ");
        char *a1 = strtok(NULL, " "), *a2 = strtok(NULL, " ");
        if (!cmd) continue;
        if (!strcmp(cmd, "help")) help();
        else if (!strcmp(cmd, "info")) info();
        else if (!strcmp(cmd, "diag")) diag();
        else if (!strcmp(cmd, "soak")) soak(a1 ? (unsigned)strtoul(a1, NULL, 0) : 60u);
        else if (!strcmp(cmd, "clear")) printf(kh_clear_errors() == KH_OK ? "OK\n" : "ERR\n");
        else if (!strcmp(cmd, "mode") && a1 && (!strcmp(a1, "spi") || !strcmp(a1, "qspi"))) {
            config.lanes = !strcmp(a1, "qspi") ? KH_QSPI : KH_SPI;
            apply_config();
            printf("OK mode %s\n", a1);
        } else if (!strcmp(cmd, "div") && a1 && atoi(a1) >= 1 && atoi(a1) <= 250) {
            config.clkdiv = (unsigned)atoi(a1);
            apply_config();
            printf("OK SCK %.2f MHz\n", 10.0 / config.clkdiv);
        } else if (!strcmp(cmd, "rd") && a1) {
            unsigned n = a2 ? (unsigned)strtoul(a2, NULL, 0) : 1u;
            uint8_t v[32];
            if (n < 1 || n > 32) { printf("ERR n 1..32\n"); continue; }
            kh_status s = kh_read((uint8_t)strtoul(a1, NULL, 16), true, v, n);
            if (s != KH_OK) { printf("ERR %s\n", status_name(s)); continue; }
            for (unsigned i = 0; i < n; i++) printf("%02x%c", v[i], i + 1 < n ? ' ' : '\n');
        } else if (!strcmp(cmd, "wr") && a1 && a2) {
            kh_status s = kh_write_reg((uint8_t)strtoul(a1, NULL, 16), (uint8_t)strtoul(a2, NULL, 16));
            printf(s == KH_OK ? "OK\n" : "ERR %s\n", status_name(s));
        } else if (!strcmp(cmd, "w") && a1 && a2) upload(strtoul(a1, NULL, 16), strtoul(a2, NULL, 0));
        else if (!strcmp(cmd, "c") && a1 && a2) readback(strtoul(a1, NULL, 16), strtoul(a2, NULL, 0));
        else printf("ERR unknown command, try help\n");
    }
}
