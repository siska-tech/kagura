// SPDX-License-Identifier: Apache-2.0
// Standalone C on KAGURA-9: the audio HAL and the KSNG player over the C host
// driver, from SRAM (no_flash), loaded and checked by
// tools/rp2040_sram_bench.py run (flash unchanged).
//
//   1. preflight: ID, ABI 0.6, CAPS, ERROR_CODE (reads only);
//   2. a test melody through the HAL alone (pulse 0, then wave 4);
//   3. the demo song (songs/demo.h, exported by 神楽トラッカー), then the
//      click song (songs/click.h, a timing probe) for PLAY_S seconds each;
//      ticks run when due by polling the timer: lateness histogram, send
//      time, CPU share, tick count against the exact tempo;
//   4. the click song with the transport kept busy between ticks (VRAM
//      reads), as a desktop's tile runs would;
//   5. silence, ERROR_CODE and AUDIO_STATUS checked, stack peak.
// Seconds of silence separate the parts, for tools/kagura-audio-timing.py.
// Protocol: host 'g' starts; KDRP_DONE ends; host 'r' reboots into flash.
#include <stdio.h>
#include <string.h>

#include "hardware/clocks.h"
#include "hardware/watchdog.h"
#include "ka_kagura_host.h"
#include "ks_player.h"
#include "pico/stdlib.h"
#include "click.h"
#include "demo.h"

#define PIN_IO0 2u   // as software/pico/main.c
#define PIN_SCK 6u
#define PIN_CS 7u
#define PIN_BUSY 8u
#define PIN_READY 9u
#define PIN_IRQ 10u
#define PLAY_S 20

static const kh_config config = {KH_QSPI, 2, PIN_IO0, PIN_SCK, PIN_CS, PIN_BUSY, PIN_READY, PIN_IRQ};
static ka_audio hal;
static ka_frame frame;
static ks_song song, click;
static ks_player player;
static uint8_t scratch[1024];

extern char __StackBottom, __StackTop;
#define GUARD_WORD 0xC0DEFA11u
static uint32_t *stack_lo, *stack_hi;

static void paint_stack(void) {
    uint32_t sp;
    __asm__ volatile("mov %0, sp" : "=r"(sp));
    stack_lo = (uint32_t *)(((uintptr_t)&__StackBottom + 64u) & ~3u);
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
    kh_read_reg(KAGURA_REG_ERROR_CODE, &error);
    printf("KAPLAY_ERROR %s status %d error_code 0x%02x\n", what, (int)s, error);
    printf("KDRP_DONE\n");
    stdio_flush();
    sleep_ms(200);
    watchdog_reboot(0, 0, 10);
    for (;;) tight_loop_contents();
}

static void wait_char(int want, int seconds) {
    for (int i = 0; i < seconds * 10; i++) {
        watchdog_update();
        if (getchar_timeout_us(100000) == want) return;
    }
    watchdog_reboot(0, 0, 10);
    for (;;) tight_loop_contents();
}

static void send(void) {
    ka_flush(&hal, &frame);
    kh_status s = ka_kh_send(&hal, &frame, KH_DEFAULT_TIMEOUT_US);
    if (s != KH_OK) {
        ka_invalidate(&hal);
        fail("send", s);
    }
}

static void hold_ms(unsigned ms) {
    absolute_time_t end = make_timeout_time_ms(ms);
    while (!time_reached(end)) watchdog_update();
}

static void melody(void) {
    static const uint8_t notes[] = {60, 62, 64, 65, 67, 69, 71, 72, 67, 64, 60};
    ka_set_duty(&hal, 0, 128);
    ka_set_gain(&hal, 0, 160, 160);
    for (unsigned i = 0; i < sizeof notes; i++) {
        ka_set_pitch(&hal, 0, notes[i], 0);
        ka_set_enable(&hal, 0, true);
        ka_retrigger(&hal, 0);
        send();
        hold_ms(180);
        ka_set_enable(&hal, 0, false);
        send();
        hold_ms(40);
    }
    // The same phrase on wave voice 4 with a sine-like table.
    uint8_t wave[32];
    for (unsigned i = 0; i < 32; i++) {
        int t = (int)(i & 15) * 16 - 128;
        wave[i] = (uint8_t)(int8_t)(i < 16 ? t : -t);
    }
    ka_set_wave(&hal, 4, wave, sizeof wave);
    ka_set_gain(&hal, 4, 200, 200);
    for (unsigned i = 0; i < sizeof notes; i++) {
        ka_set_pitch(&hal, 4, notes[i] - 12, 0);
        ka_set_enable(&hal, 4, true);
        send();
        hold_ms(140);
    }
    ka_silence(&hal, false);
    send();
    printf("KAPLAY_MELODY notes %u frames %lu wave_uploads %lu\n", (unsigned)(2 * sizeof notes),
           (unsigned long)hal.frames, (unsigned long)hal.wave_uploads);
}

// Plays for PLAY_S seconds; with busy, keeps the transport busy between ticks.
static void play(const char *name, const ks_song *s, bool busy) {
    static const uint32_t edges[] = {50, 100, 200, 500, 1000, 2000, 5000};
    uint32_t hist[8] = {0};
    uint64_t send_us = 0, work_us = 0, busy_us = 0;
    uint32_t send_max = 0, frames0 = hal.frames, pairs0 = hal.pairs_sent;
    ks_player_load(&player, s);
    memset(&player.stats, 0, sizeof player.stats);
    uint32_t start = time_us_32();
    ks_player_play(&player, start, KS_MODE_SONG, 0, 0);
    uint32_t end = start + PLAY_S * 1000000u;
    while ((int32_t)(time_us_32() - end) < 0) {
        watchdog_update();
        uint32_t due = player.next_us;
        uint32_t now = time_us_32();
        if ((int32_t)(now - due) < 0) {
            if (busy && (int32_t)(due - now) > 1500) {
                // A desktop-like transfer: about 1 ms of transport time.
                uint32_t t = time_us_32();
                kh_status s = kh_vram_read(0x000000, scratch, 96);
                if (s != KH_OK) fail("busy read", s);
                busy_us += time_us_32() - t;
            }
            continue;
        }
        uint32_t t0 = time_us_32();
        unsigned n = ks_player_advance(&player, t0);
        uint32_t t1 = time_us_32();
        send();
        uint32_t t2 = time_us_32();
        if (n) {
            uint32_t late = t0 - due;
            unsigned b = 0;
            while (b < 7 && late >= edges[b]) b++;
            hist[b]++;
        }
        send_us += t2 - t1;
        work_us += t2 - t0;
        if (t2 - t1 > send_max) send_max = t2 - t1;
    }
    uint32_t elapsed = player.next_us - start;   // exact time of the ticks run
    uint64_t expect = ((uint64_t)elapsed * s->tempo + KS_TICK_UNITS - 1) / KS_TICK_UNITS;
    const ks_stats *st = &player.stats;
    uint32_t frames = hal.frames - frames0;
    printf("KAPLAY_SONG %s seconds %u ticks %lu expected %llu late_max_us %lu late_mean_us %lu folded %lu "
           "resyncs %lu frames %lu pairs_per_frame %lu send_mean_us %lu send_max_us %lu cpu_pct %lu.%lu "
           "busy_pct %lu\n",
           name, PLAY_S, (unsigned long)st->ticks, (unsigned long long)expect, (unsigned long)st->late_max_us,
           (unsigned long)(st->calls ? st->late_sum_us / st->calls : 0), (unsigned long)st->folded,
           (unsigned long)st->resyncs, (unsigned long)frames,
           (unsigned long)(frames ? (hal.pairs_sent - pairs0) / frames : 0),
           (unsigned long)(frames ? send_us / frames : 0), (unsigned long)send_max,
           (unsigned long)(work_us * 100 / (PLAY_S * 1000000u)),
           (unsigned long)(work_us * 1000 / (PLAY_S * 1000000u) % 10),
           (unsigned long)(busy_us * 100 / (PLAY_S * 1000000u)));
    printf("KAPLAY_LATE %s <50 %lu <100 %lu <200 %lu <500 %lu <1000 %lu <2000 %lu <5000 %lu >=5000 %lu\n", name,
           (unsigned long)hist[0], (unsigned long)hist[1], (unsigned long)hist[2], (unsigned long)hist[3],
           (unsigned long)hist[4], (unsigned long)hist[5], (unsigned long)hist[6], (unsigned long)hist[7]);
    ks_player_stop(&player);
    send();
    hold_ms(2500);
}

int main(void) {
    watchdog_enable(8000, true);           // also clears the boot-to-RAM magic
    set_sys_clock_khz(120000, true);       // kagura_host.c: 12 PIO cycles per SCK
    paint_stack();
    stdio_init_all();
    for (int i = 0; i < 300 && !stdio_usb_connected(); i++) {
        watchdog_update();
        sleep_ms(100);
    }
    if (!stdio_usb_connected()) watchdog_reboot(0, 0, 10);
    wait_char('g', 60);

    kh_init(&config);
    uint8_t id[5] = {0}, error = 0xFF, ast = 0xFF;
    kh_status s = kh_wait_ready(KH_DEFAULT_TIMEOUT_US);
    if (s == KH_OK) s = kh_read(KAGURA_REG_ID0, true, id, sizeof id);
    if (s == KH_OK) s = kh_read_reg(KAGURA_REG_ERROR_CODE, &error);
    if (s == KH_OK) s = kh_audio_read(KAGURA_AUDIO_STATUS, &ast);
    printf("KAPLAY_PREFLIGHT status %d id %02x%02x abi %u.%u caps 0x%02x error_code 0x%02x audio_status 0x%02x "
           "clk_sys_khz %lu\n", (int)s, id[0], id[1], id[2], id[3], id[4], error, ast,
           (unsigned long)frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLK_SYS));
    bool ok = s == KH_OK && id[0] == KAGURA_ID0 && id[1] == KAGURA_ID1 && id[2] == 0 && id[3] == 6;
    if (!ok || ka_init(&hal, id[4]) != KA_OK) fail("preflight", s);
    if (error) kh_clear_errors();
    if (ks_song_parse(&song, ksng_demo, sizeof ksng_demo) || ks_song_parse(&click, ksng_click, sizeof ksng_click))
        fail("song", KH_BAD_ARGUMENT);
    ks_player_init(&player, &hal);
    printf("KAPLAY_SIZES hal %u player %u frame %u song_bytes %u\n", (unsigned)sizeof hal,
           (unsigned)sizeof player, (unsigned)sizeof frame, (unsigned)sizeof ksng_demo);
    send();   // everything, silent

    melody();
    hold_ms(2500);
    play("demo", &song, false);
    play("click_idle", &click, false);
    play("click_busy", &click, true);

    ka_silence(&hal, true);
    send();
    s = kh_ka_wait_idle(KH_DEFAULT_TIMEOUT_US);
    if (s == KH_OK) s = kh_read_reg(KAGURA_REG_ERROR_CODE, &error);
    if (s == KH_OK) s = kh_audio_read(KAGURA_AUDIO_STATUS, &ast);
    printf("KAPLAY_END status %d error_code 0x%02x audio_status 0x%02x commits %lu stack_peak %lu\n", (int)s, error,
           ast, (unsigned long)hal.commits, (unsigned long)stack_peak());
    printf("KDRP_DONE\n");
    stdio_flush();
    wait_char('r', 60);
    watchdog_reboot(0, 0, 10);
    for (;;) tight_loop_contents();
}
