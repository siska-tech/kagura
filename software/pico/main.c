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
#include "spectacular_demo.h"
#include "pcm_demo.h"

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

static void report_pressure_failure(const char *operation, int index, kh_status s) {
    uint8_t status = 0xff, fifo = 0xff, error = kh_last_error();
    // Diagnostic reads remain legal while the command queue is full. Preserve
    // the error that caused the driver call to fail before reading it again.
    kh_read_reg(KAGURA_REG_STATUS, &status);
    kh_read_reg(KAGURA_REG_FIFO_STATUS, &fifo);
    kh_read_reg(KAGURA_REG_ERROR_CODE, &error);
    if (index >= 0)
        report("busy", false, "%s %d failed: %s 0x%02x, STATUS 0x%02x FIFO_STATUS 0x%02x",
               operation, index, status_name(s), error, status, fifo);
    else
        report("busy", false, "%s failed: %s 0x%02x, STATUS 0x%02x FIFO_STATUS 0x%02x",
               operation, status_name(s), error, status, fifo);
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

static void audio_reg(unsigned ch, uint8_t off, uint8_t value, kh_status *s) {
    if (*s == KH_OK) *s = kh_audio_write(KAGURA_AUDIO_INDEX(ch, off), value);
}

static void audio_step(unsigned ch, uint32_t step, kh_status *s) {
    audio_reg(ch, KAGURA_AUDIO_STEP_L, (uint8_t)step, s);
    audio_reg(ch, KAGURA_AUDIO_STEP_M, (uint8_t)(step >> 8), s);
    audio_reg(ch, KAGURA_AUDIO_STEP_H, (uint8_t)(step >> 16), s);
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
           (id[4] == KAGURA_CAPS_VALUE_FULL || id[4] == KAGURA_CAPS_VALUE_WIDE ||
            id[4] == KAGURA_CAPS_VALUE_FULL_PSRAM || id[4] == KAGURA_CAPS_VALUE_WIDE_PSRAM),
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

    // 6. All six voices and both wavetable banks. After committing A then B,
    // A must be visible again in the shadow address range.
    s = KH_OK;
    for (size_t i = 0; i < 512; i++) { buf[i] = (uint8_t)i; back[i] = (uint8_t)~i; }
    const uint32_t steps[5] = {91669u, 115501u, 137349u, 183338u, 230999u};
    for (unsigned ch = 0; ch < 3; ch++) {
        audio_step(ch, steps[ch], &s);
        audio_reg(ch, KAGURA_AUDIO_DUTY, 128, &s);
        audio_reg(ch, KAGURA_AUDIO_GAIN_L, ch == 2 ? 24 : 48, &s);
        audio_reg(ch, KAGURA_AUDIO_GAIN_R, ch == 0 ? 24 : 48, &s);
        audio_reg(ch, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET, &s);
    }
    audio_reg(3, KAGURA_AUDIO_NOISE_PERIOD_L, 31, &s);
    audio_reg(3, KAGURA_AUDIO_NOISE_PERIOD_H, 0, &s);
    audio_reg(3, KAGURA_AUDIO_GAIN_L, 16, &s);
    audio_reg(3, KAGURA_AUDIO_GAIN_R, 16, &s);
    audio_reg(3, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET, &s);
    for (unsigned ch = 4; ch < 6; ch++) {
        audio_step(ch, steps[ch - 1], &s);
        audio_reg(ch, KAGURA_AUDIO_LEN_LOG2, 8, &s);
        audio_reg(ch, KAGURA_AUDIO_GAIN_L, ch == 4 ? 48 : 20, &s);
        audio_reg(ch, KAGURA_AUDIO_GAIN_R, ch == 5 ? 48 : 20, &s);
        audio_reg(ch, KAGURA_AUDIO_CONTROL, KAGURA_AUDIO_CONTROL_ENABLE | KAGURA_AUDIO_CONTROL_PHASE_RESET, &s);
    }
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, buf, 512);
    if (s == KH_OK) s = kh_audio_commit(100000);
    if (s == KH_OK) s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, back, 512);
    if (s == KH_OK) s = kh_audio_commit(100000);
    if (s == KH_OK) s = kh_vram_read(KAGURA_VRAM_WAVE_BASE, back + 512, 512);
    if (check("audio", s)) {
        sleep_ms(1000);
        size_t wave_bad = 0;
        for (size_t i = 0; i < 512; i++) wave_bad += back[512 + i] != buf[i];
        report("wave-swap", wave_bad == 0, "512-byte previous bank read-back, %u mismatches", (unsigned)wave_bad);
        // Put the current waveform in both banks, then disable all voices.
        for (size_t i = 0; i < 512; i++) back[i] = (uint8_t)~i;
        s = kh_vram_write(KAGURA_VRAM_WAVE_BASE, back, 512);
        for (unsigned ch = 0; s == KH_OK && ch < KAGURA_AUDIO_CHANNELS; ch++)
            s = kh_audio_write(KAGURA_AUDIO_INDEX(ch, KAGURA_AUDIO_CONTROL), 0);
        if (s == KH_OK) s = kh_audio_commit(100000);
        uint8_t ast = 0xff;
        if (s == KH_OK) s = kh_audio_read(KAGURA_AUDIO_STATUS, &ast);
        if (check("audio", s))
            report("audio", (ast & (KAGURA_AUDIO_STATUS_FIFO_UNDERFLOW | KAGURA_AUDIO_STATUS_OVERFLOW)) == 0,
                   "6 voices for 1s, AUDIO_STATUS 0x%02x (check: chord/noise heard)", ast);
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
    // Set the FILL parameters once, then send 64 COMMAND bytes in one
    // transaction. With no parameter/header gaps between descriptors this
    // must fill the 32-entry queue and exercise the BUSY gate in the PIO.
    uint8_t fill_params[3] = {0x00, 0x04, 0x3c}; // length 1024, value 0x3c
    uint8_t fill_commands[64];
    memset(fill_commands, KAGURA_CMD_FILL, sizeof fill_commands);
    s = kh_set_vram_addr(vaddr);
    if (s == KH_OK) s = kh_write(KAGURA_REG_LENGTH_L, true, fill_params, sizeof fill_params);
    if (s == KH_OK) s = kh_write(KAGURA_REG_COMMAND, false, fill_commands, sizeof fill_commands);
    if (s == KH_OK) s = kh_check_errors();
    for (size_t i = 0; i < 4096; i++) buf[i] = (uint8_t)i;
    if (s != KH_OK) {
        report_pressure_failure("FILL burst", -1, s);
    } else {
        s = kh_vram_write(vaddr - 4096u, buf, 4096);
        if (s != KH_OK) report_pressure_failure("VRAM_WRITE", -1, s);
    }
    if (s == KH_OK) {
        s = kh_fence(0xa5, 500000);
        if (s != KH_OK) report_pressure_failure("FENCE", -1, s);
    }
    if (s == KH_OK) {
        uint8_t mid = 0;
        if (check("busy", kh_vram_read(vaddr - 4096u + 1234u, &mid, 1)))
            report("busy", mid == (uint8_t)1234u, "64 FILLs + 4096-byte stream, BUSY waits %llu, read-back %02x",
                   (unsigned long long)(st->busy_waits - waits_before), mid);
    }

    // 9. Nothing left in ERROR_CODE.
    uint8_t e = 0xff;
    if (check("errors", kh_read_reg(KAGURA_REG_ERROR_CODE, &e))) report("errors", e == 0, "ERROR_CODE 0x%02x", e);
    printf("  stats: %llu bytes, %llu transactions, %llu BUSY waits (%llu us, GPIO edge IRQ)\n",
           (unsigned long long)st->bytes_sent, (unsigned long long)st->transactions,
           (unsigned long long)st->busy_waits, (unsigned long long)st->busy_wait_us);
    printf("  check board LED2 (adapter `late`): it must stay off; LED1 (reset released) stays on\n");
    printf(failures ? "DIAG FAIL %d\n" : "DIAG PASS\n", failures);
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

static void abort_test(void) {
    const uint8_t sentinel = 0x5a, attempted = 0xa5;
    uint8_t after_header = 0, after_data = 0, id[2] = {0};
    kh_status s = kh_clear_errors();
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_FILL_VALUE, sentinel);
    if (s == KH_OK) {
        kh_abort_write(true, KAGURA_REG_FILL_VALUE, attempted);
        s = kh_read_reg(KAGURA_REG_FILL_VALUE, &after_header);
    }
    if (s == KH_OK) {
        kh_abort_write(false, KAGURA_REG_FILL_VALUE, attempted);
        s = kh_read_reg(KAGURA_REG_FILL_VALUE, &after_data);
    }
    if (s == KH_OK) s = kh_read(KAGURA_REG_ID0, true, id, sizeof id);
    if (s == KH_OK) s = kh_check_errors();
    bool ok = s == KH_OK && after_header == sentinel && after_data == sentinel &&
              id[0] == KAGURA_ID0 && id[1] == KAGURA_ID1;
    printf("%s abort: header %02x, data %02x, recovery ID %02x %02x%s\n",
           ok ? "PASS" : "FAIL", after_header, after_data, id[0], id[1],
           s == KH_OK ? "" : " (transport/error failure)");
}

static void help(void) {
    printf("commands:\n"
           "  info                 ID, ABI, CAPS, STATUS, pins\n"
           "  diag                 end-to-end check (ID, registers, VRAM, FILL/FENCE, sprite, audio, IRQ, BUSY)\n"
           "  abort                abort mid-header and mid-data; verify no side effect and recovery\n"
           "  show [seconds]       moonlit parallax runner demo; default 30s, 0 runs until a key\n"
           "  mode spi|qspi        must match the bitstream (build-nano9k.tcl spi / qspi)\n"
           "  div <n>              SCK = 10MHz / n (1..250, default 4)\n"
           "  rd <off> [n]         read n registers from offset (hex), INC\n"
           "  wr <off> <val>       write one register (hex)\n"
           "  w <addr> <len>       upload len raw bytes to VRAM (hex addr), replies READY then OK len us crc32\n"
           "  c <addr> <len>       read VRAM back, replies CRC len us crc32\n"
           "  psram [len]          PSRAM upload/FENCE/readback compare (CAPS PSRAM, default 2048)\n"
           "  pcm [seconds]        PCM loop + retriggered one-shot from PSRAM; default 10s, 0 runs until a key\n"
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
        else if (!strcmp(cmd, "abort")) abort_test();
        else if (!strcmp(cmd, "show")) {
            unsigned seconds = a1 ? (unsigned)strtoul(a1, NULL, 0) : 30u;
            if (seconds > 600u) { printf("ERR seconds 0..600\n"); continue; }
            kh_status s = kagura_spectacular_demo(seconds);
            if (s != KH_OK) printf("ERR show: %s 0x%02x\n", status_name(s), kh_last_error());
        }
        else if (!strcmp(cmd, "psram")) kagura_psram_test(a1 ? (size_t)strtoul(a1, NULL, 0) : 2048u);
        else if (!strcmp(cmd, "pcm")) {
            unsigned seconds = a1 ? (unsigned)strtoul(a1, NULL, 0) : 10u;
            if (seconds > 600u) { printf("ERR seconds 0..600\n"); continue; }
            kagura_pcm_demo(seconds);
        }
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
