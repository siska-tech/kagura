// SPDX-License-Identifier: Apache-2.0
// KSNG player: exact tick times, order of events, flow effects, envelopes,
// pause/resume, previews, reloads and the HAL it drives (via ka_model.h).
#include "ka_model.h"
#include "ka_test.h"
#include "ks_player.h"

#define CAPS 0x5B
static uint8_t buf[16384];
static kb_song b;
static ks_song song;
static ka_audio hal;
static ka_frame frame;
static ka_model model;
static ks_player p;

static void load(void) {
    size_t n = kb_build(&b, buf, sizeof buf);
    if (!n || ks_song_parse(&song, buf, n) != KS_OK) {
        fprintf(stderr, "fixture does not build\n");
        return;
    }
    ka_init(&hal, CAPS);
    ka_model_init(&model);
    ks_player_init(&p, &hal);
    ks_player_load(&p, &song);
}

static void send(void) {
    ka_flush(&hal, &frame);
    ka_model_send(&model, &hal, &frame);
}

static uint32_t step_of(unsigned v) {
    return hal.want[v][0] | hal.want[v][1] << 8 | (uint32_t)hal.want[v][2] << 16;
}
static bool enabled(unsigned v) { return hal.want[v][6] & 1; }
static unsigned gain_l(unsigned v) { return hal.want[v][4]; }

// Runs exactly one tick at its due time.
static void tick(void) { ks_player_advance(&p, p.next_us); }

static void test_tick_times_are_exact(void) {
    const unsigned tempos[] = {32, 125, 150, 151, 255};
    for (unsigned ti = 0; ti < 5; ti++) {
        kb_init(&b, 1, 64);
        b.tempo = (uint8_t)tempos[ti];
        load();
        uint32_t t0 = 0xFFF00000u + ti;           // the clock wraps during the run
        ks_player_play(&p, t0, KS_MODE_SONG, 0, 0);
        uint32_t seed = 7 + ti, now = t0;
        uint64_t elapsed = 0;
        while (elapsed < 30000000) {              // 30 s of music
            uint32_t dt = 1 + ka_rand(&seed) % 4000;
            now += dt;
            elapsed += dt;
            ks_player_advance(&p, now);
            // Tick k is due at floor(k * U / T): those with k * U < (e + 1) * T.
            uint64_t due = ((elapsed + 1) * tempos[ti] - 1) / KS_TICK_UNITS + 1;
            CHECK_EQ(p.stats.ticks, due);
        }
        CHECK_EQ(p.stats.resyncs, 0);
        CHECK(p.stats.late_max_us < 4000);
    }
    CHECK_EQ(ks_player_tick_us(125), 20000);
    CHECK_EQ(ks_player_tick_us(150), 16667);
}

static void fill_song(void) {
    kb_init(&b, 3, 16);
    b.instruments = 2;
    const uint8_t in1[8] = {KS_KIND_PULSE, 64, 12, 0, 3, 2, 8, 4};
    memcpy(b.instrument[1], in1, 8);
    b.patterns = 2;
    b.orders = 2;
    b.order[0] = 0;
    b.order[1] = 1;
    uint32_t seed = 5;
    for (unsigned pt = 0; pt < 2; pt++)
        for (unsigned r = 0; r < 16; r++)
            for (unsigned t = 0; t < 3; t++) {
                unsigned x = ka_rand(&seed) % 8;
                if (x < 3) kb_note(&b, pt, r, t, 25 + ka_rand(&seed) % 48, ka_rand(&seed) % 2);
                else if (x == 3) kb_cell(&b, pt, r, t)[0] = KS_NOTE_OFF;
                if (ka_rand(&seed) % 6 == 0) kb_fx(&b, pt, r, t, ka_rand(&seed) % 3, ka_rand(&seed) % 256);
                if (ka_rand(&seed) % 9 == 0) kb_cell(&b, pt, r, t)[2] = (uint8_t)(ka_rand(&seed) % 16);
            }
}

// The same song played with on-time calls and with erratic, late calls is in
// the same state after the same number of ticks.
static void test_late_calls_do_not_change_the_music(void) {
    fill_song();
    load();
    static uint8_t want_a[200][KA_VOICES][10];
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    for (unsigned k = 0; k < 200; k++) {
        tick();
        memcpy(want_a[k], hal.want, sizeof hal.want);
    }
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    uint32_t seed = 3, now = 0;
    while (p.stats.ticks < 200) {
        // Calls at random times; stop exactly on tick boundaries to compare.
        uint32_t target = now + ka_rand(&seed) % 60000;
        while (p.stats.ticks < 200 && (int32_t)(target - p.next_us) >= 0) {
            unsigned before = p.stats.ticks;
            ks_player_advance(&p, p.next_us);
            CHECK_EQ(p.stats.ticks, before + 1);
            CHECK(!memcmp(want_a[before], hal.want, sizeof hal.want));
        }
        now = target;
    }
    // Folding several ticks into one call ends in the same state too.
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    ks_player_advance(&p, 0);
    for (unsigned k = 1; k < 200; k += 7) {
        unsigned n = k + 7 > 200 ? 200 - k : 7;
        uint32_t t = 0;
        for (unsigned i = 0; i < k + n - 1; i++) t += KS_TICK_UNITS / 125;
        ks_player_advance(&p, t);
        CHECK(!memcmp(want_a[p.stats.ticks - 1], hal.want, sizeof hal.want));
    }
    CHECK(p.stats.folded > 0);
}

static void test_rows_orders_and_loop(void) {
    kb_init(&b, 1, 16);
    b.patterns = 2;
    b.orders = 3;
    b.order[0] = 0;
    b.order[1] = 1;
    b.order[2] = 1;
    b.loop_order = 1;
    b.rows[1] = 32;
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    tick();
    CHECK_EQ(p.play_row, 0);
    for (unsigned i = 0; i < 5; i++) tick();
    CHECK_EQ(p.row, 1);                           // next to run
    CHECK_EQ(p.play_row, 0);                      // still sounding
    tick();
    CHECK_EQ(p.play_row, 1);
    for (unsigned i = 0; i < 15 * 6; i++) tick();
    CHECK_EQ(p.order, 1);
    CHECK_EQ(p.row, 0);
    for (unsigned i = 0; i < 64 * 6; i++) tick();
    CHECK_EQ(p.order, 1);                         // looped to order 1
    CHECK_EQ(p.state, KS_PLAYING);
    // Pattern mode repeats one pattern.
    ks_player_play(&p, p.next_us, KS_MODE_PATTERN, 1, 30);
    for (unsigned i = 0; i < 2 * 6; i++) tick();
    CHECK_EQ(p.order, 1);
    CHECK_EQ(p.row, 0);
}

static void test_end_of_song(void) {
    kb_init(&b, 1, 16);
    b.flags = 0;
    const uint8_t in0[8] = {KS_KIND_PULSE, 128, 15, 128, 0, 0, 15, 3};   // release 3
    memcpy(b.instrument[0], in0, 8);
    kb_note(&b, 0, 0, 0, 49, 0);
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    for (unsigned i = 0; i < 16 * 6; i++) tick();
    CHECK_EQ(p.state, KS_ENDED);
    CHECK(enabled(0));                            // releasing
    tick();
    tick();
    tick();
    CHECK(!enabled(0));
    CHECK(!p.idle_ticking);
    unsigned ticks = p.stats.ticks;
    CHECK_EQ(ks_player_advance(&p, p.next_us + 1000000), 0);
    CHECK_EQ(p.stats.ticks, ticks);
    CHECK_EQ(ks_player_play(&p, p.next_us, KS_MODE_SONG, 0, 0), KA_OK);   // replay
    CHECK_EQ(p.state, KS_PLAYING);
}

static void test_jump_break_speed_tempo(void) {
    kb_init(&b, 2, 16);
    b.patterns = 3;
    b.orders = 3;
    b.order[0] = 0;
    b.order[1] = 1;
    b.order[2] = 2;
    kb_fx(&b, 0, 2, 0, KS_FX_JUMP, 2);
    kb_fx(&b, 0, 2, 1, KS_FX_BREAK, 5);
    kb_fx(&b, 2, 5, 0, KS_FX_SPEED, 3);
    kb_fx(&b, 2, 5, 1, KS_FX_SPEED, 150);
    kb_fx(&b, 2, 6, 0, KS_FX_BREAK, 40);         // past the next pattern: row 0
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    for (unsigned i = 0; i < 3 * 6; i++) tick();
    CHECK_EQ(p.order, 2);
    CHECK_EQ(p.row, 5);
    uint32_t before = p.next_us;
    tick();                                       // row 5: speed 3, tempo 150
    CHECK_EQ(p.speed, 3);
    CHECK_EQ(p.tempo, 150);
    CHECK_EQ(p.next_us - before, KS_TICK_UNITS / 150);
    tick();
    tick();
    CHECK_EQ(p.row, 6);
    for (unsigned i = 0; i < 3; i++) tick();
    CHECK_EQ(p.order, 0);                         // past the last order: loop to 0
    CHECK_EQ(p.row, 0);
}

static void test_notes_reach_the_hardware(void) {
    kb_init(&b, 2, 16);
    b.voice[1] = 3;
    b.instruments = 2;
    const uint8_t noise[8] = {KS_KIND_NOISE, 0, 15, 128, 0, 0, 15, 0};
    memcpy(b.instrument[1], noise, 8);
    kb_note(&b, 0, 0, 0, 49, 0);                  // C-4 = MIDI 60
    kb_note(&b, 0, 0, 1, 61, 1);
    kb_cell(&b, 0, 2, 0)[0] = KS_NOTE_OFF;
    kb_cell(&b, 0, 1, 0)[2] = 8;
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    tick();
    send();
    CHECK(ka_model_matches(&model, &hal));
    CHECK_EQ(step_of(0), ka_note_step(60, 0));
    CHECK(enabled(0));
    CHECK_EQ(gain_l(0), 255);
    CHECK_EQ(hal.want[0][3], 128);
    CHECK_EQ(model.phase_resets[0], 1);
    uint16_t period = (uint16_t)(hal.want[3][8] | hal.want[3][9] << 8);
    CHECK_EQ(period, ka_note_noise(72));
    for (unsigned i = 0; i < 6; i++) tick();
    CHECK_EQ(gain_l(0), 8 * 16 * 255 / 240);      // volume column 8
    for (unsigned i = 0; i < 6; i++) tick();
    CHECK(!enabled(0));                           // note off, release 0
    send();
    CHECK(ka_model_matches(&model, &hal));
    CHECK_EQ(model.rejected, 0);
}

static void test_pan(void) {
    kb_init(&b, 2, 16);
    const uint8_t left[8] = {KS_KIND_PULSE, 128, 15, 0, 0, 0, 15, 0};
    b.instruments = 2;
    memcpy(b.instrument[1], left, 8);
    kb_note(&b, 0, 0, 0, 49, 1);
    kb_note(&b, 0, 0, 1, 49, 0);
    kb_fx(&b, 0, 1, 1, KS_FX_PAN, 255);
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    tick();
    CHECK_EQ(gain_l(0), 255);
    CHECK_EQ(hal.want[0][5], 0);                  // instrument pan 0: hard left
    CHECK_EQ(gain_l(1), 255);
    CHECK_EQ(hal.want[1][5], 255);                // centre: both full
    for (unsigned i = 0; i < 6; i++) tick();
    CHECK(gain_l(1) < 3);                         // 8FF: hard right
    CHECK_EQ(hal.want[1][5], 255);
}

static void test_envelope(void) {
    kb_init(&b, 1, 16);
    const uint8_t in0[8] = {KS_KIND_PULSE, 128, 15, 128, 4, 4, 5, 3};
    memcpy(b.instrument[0], in0, 8);
    kb_note(&b, 0, 0, 0, 49, 0);
    kb_cell(&b, 0, 4, 0)[0] = KS_NOTE_OFF;
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    unsigned g[32];
    for (unsigned i = 0; i < 32; i++) {
        tick();
        g[i] = enabled(0) ? gain_l(0) : 0;
    }
    CHECK(g[0] > 0 && g[0] < g[1] && g[1] < g[2] && g[2] < g[3]);   // attack 4 ticks
    CHECK_EQ(g[3], 255);
    CHECK(g[4] < g[3] && g[5] < g[4] && g[6] < g[5]);               // decay 4 ticks
    CHECK_EQ(g[7], 255 * 1365 / 4096);                              // sustain 5/15 of 4096
    CHECK(g[7] == g[15] && g[15] == g[23]);                          // sustain holds
    CHECK(g[24] < g[23] && g[25] < g[24] && g[25] > 0);             // released at row 4
    CHECK_EQ(g[26], 0);                                             // release 3 ticks
    CHECK_EQ(g[31], 0);
}

static void test_pitch_effects(void) {
    kb_init(&b, 1, 16);
    kb_note(&b, 0, 0, 0, 49, 0);
    kb_fx(&b, 0, 0, 0, KS_FX_ARPEGGIO, 0x47);
    kb_fx(&b, 0, 1, 0, KS_FX_SLIDE_UP, 16);
    kb_note(&b, 0, 2, 0, 61, 0);
    kb_fx(&b, 0, 2, 0, KS_FX_PORTA, 32);          // from C-5 the tone portamento below
    for (unsigned r = 3; r <= 6; r++) kb_fx(&b, 0, r, 0, KS_FX_PORTA, 32);
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    tick();
    CHECK_EQ(step_of(0), ka_note_step(60, 0));
    tick();
    CHECK_EQ(step_of(0), ka_note_step(64, 0));
    tick();
    CHECK_EQ(step_of(0), ka_note_step(67, 0));
    for (unsigned i = 0; i < 3; i++) tick();
    tick();                                       // row 1 tick 0: no slide yet
    CHECK_EQ(step_of(0), ka_note_step(60, 0));
    tick();
    CHECK_EQ(step_of(0), ka_note_step(60, 16));
    for (unsigned i = 0; i < 4; i++) tick();
    CHECK_EQ(step_of(0), ka_note_step(61, 16));   // 5 ticks x 16
    tick();                                       // row 2: portamento towards 72
    send();
    unsigned retriggers = model.phase_resets[0];
    for (unsigned i = 0; i < 11; i++) tick();
    CHECK_EQ(p.track[0].pitch, 61 * 64 + 16 + 10 * 32);
    for (unsigned i = 0; i < 20; i++) tick();
    CHECK_EQ(p.track[0].pitch, 72 * 64);          // reached, not overshot
    send();
    CHECK_EQ(model.phase_resets[0], retriggers);  // no retrigger under portamento
}

static void test_pause_resume(void) {
    fill_song();
    load();
    ks_player_play(&p, 1000, KS_MODE_SONG, 0, 0);
    ks_player_advance(&p, 1000 + 25000);
    unsigned ticks = p.stats.ticks, order = p.order, row = p.row;
    uint32_t due = p.next_us;
    ks_player_pause(&p, 1000 + 30000);
    for (unsigned v = 0; v < 3; v++) CHECK(!enabled(v));
    CHECK_EQ(ks_player_advance(&p, 9000000), 0);
    CHECK_EQ(p.stats.ticks, ticks);
    ks_player_resume(&p, 5000000);
    CHECK_EQ(p.next_us, 5000000 + (due - 31000));
    CHECK_EQ(p.order, order);
    CHECK_EQ(p.row, row);
    bool any = false;
    for (unsigned t = 0; t < 3; t++)
        if (p.track[t].on) any = any || enabled(t);
    CHECK(any || !(p.track[0].on || p.track[1].on || p.track[2].on));
}

static void test_preview_while_stopped(void) {
    kb_init(&b, 2, 16);
    b.voice[1] = 4;
    b.instruments = 2;
    b.waves = 1;
    b.wave_log2[0] = 6;
    for (unsigned i = 0; i < 64; i++) b.wave[0][i] = (uint8_t)(i * 3);
    const uint8_t wave_in[8] = {KS_KIND_WAVE, 0, 15, 128, 0, 0, 15, 2};
    memcpy(b.instrument[1], wave_in, 8);
    load();
    CHECK_EQ(ks_player_preview(&p, 500, 0, 49, 1, 4), KA_EINVAL);   // wave on a pulse voice
    CHECK_EQ(ks_player_preview(&p, 500, 1, 49, 1, 4), KA_OK);
    CHECK_EQ(ks_player_preview(&p, 500, 1, 49, 0, 4), KA_EINVAL);  // refused: the wave note goes on
    CHECK(p.track[1].on && p.track[1].inst == 1);
    CHECK_EQ(ks_player_advance(&p, 500), 1);
    send();
    CHECK(enabled(4));
    CHECK_EQ(hal.want[4][7], 6);
    CHECK(ka_model_matches(&model, &hal));        // the wave reached the active bank
    for (unsigned i = 0; i < 3; i++) tick();
    CHECK(enabled(4));
    tick();
    tick();                                       // hold 4, release 2
    CHECK(!enabled(4));
    CHECK(!p.idle_ticking);
    CHECK_EQ(p.state, KS_STOPPED);
    send();
    CHECK(ka_model_matches(&model, &hal));
}

static void test_mute_and_voice_mask(void) {
    kb_init(&b, 2, 16);
    kb_note(&b, 0, 0, 0, 49, 0);
    kb_note(&b, 0, 0, 1, 53, 0);
    load();
    ka_set_gain(&hal, 1, 77, 77);                 // a game's sound effect on voice 1
    ks_player_set_voice_mask(&p, 0x3D);
    ks_player_set_mute(&p, 1);
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    for (unsigned i = 0; i < 20; i++) tick();
    CHECK(!enabled(0));                           // muted
    CHECK_EQ(gain_l(1), 77);                      // never touched
    ks_player_set_mute(&p, 0);
    tick();
    CHECK(enabled(0));
}

static void test_reload_keeps_position(void) {
    fill_song();
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    for (unsigned i = 0; i < 40; i++) tick();
    unsigned order = p.order, row = p.row, tick_ = p.tick;
    uint32_t next = p.next_us;
    static uint8_t buf2[16384];
    kb_note(&b, 0, 15, 0, 13, 0);                 // an edit while playing
    size_t n = kb_build(&b, buf2, sizeof buf2);
    static ks_song s2;
    CHECK_EQ(ks_song_parse(&s2, buf2, n), KS_OK);
    ks_player_reload(&p, &s2);
    CHECK_EQ(p.order, order);
    CHECK_EQ(p.row, row);
    CHECK_EQ(p.tick, tick_);
    CHECK_EQ(p.next_us, next);
    CHECK_EQ(p.state, KS_PLAYING);
    CHECK(p.song == &s2);
    // A different track layout cannot keep the voices: a plain load.
    static uint8_t buf3[16384];
    static ks_song s3;
    b.voice[2] = 5;
    n = kb_build(&b, buf3, sizeof buf3);
    CHECK_EQ(ks_song_parse(&s3, buf3, n), KS_OK);
    ks_player_reload(&p, &s3);
    CHECK_EQ(p.state, KS_STOPPED);
}

static void test_mismatched_instrument_is_silent(void) {
    kb_init(&b, 1, 16);
    b.voice[0] = 4;                               // pulse instrument on a wave voice
    kb_note(&b, 0, 0, 0, 49, 0);
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    tick();
    CHECK(!enabled(4));
    CHECK_EQ(p.stats.mismatched, 1);
}

static void test_whole_song_against_model(void) {
    fill_song();
    load();
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    for (unsigned i = 0; i < 2000; i++) {
        tick();
        send();
        CHECK(frame.npairs <= KA_FRAME_PAIRS);
        CHECK(ka_model_matches(&model, &hal));
    }
    CHECK_EQ(model.rejected, 0);
    CHECK(hal.commits > 500);
}

// The demo song, composed with 神楽トラッカー's keys and exported by it as C
// (software/audio/songs/demo.h): what a standalone game includes.
#include "demo.h"

static void test_exported_demo_song(void) {
    ks_song s;
    CHECK_EQ(ks_song_parse(&s, ksng_demo, sizeof ksng_demo), KS_OK);
    CHECK_EQ(s.tempo, 140);
    CHECK_EQ(s.orders, 2);
    ka_init(&hal, CAPS);
    ka_model_init(&model);
    ks_player_init(&p, &hal);
    ks_player_load(&p, &s);
    ks_player_play(&p, 0, KS_MODE_SONG, 0, 0);
    unsigned loops = 0, sounding = 0, last_order = 0;
    // 2 patterns x 32 rows x 6 ticks, twice round the loop.
    for (unsigned i = 0; i < 2 * 2 * 32 * 6; i++) {
        tick();
        send();
        CHECK(ka_model_matches(&model, &hal));
        if (p.play_order < last_order) loops++;
        last_order = p.play_order;
        for (unsigned v = 0; v < KA_VOICES; v++) sounding += (model.active[v * 16 + 6] & 1);
    }
    CHECK_EQ(loops, 1);
    CHECK_EQ(p.state, KS_PLAYING);
    CHECK(sounding > 1000);
    CHECK_EQ(model.rejected, 0);
    CHECK_EQ(p.stats.mismatched, 0);
    // A frame per tick at most, and small: the cache sends only changes.
    CHECK(hal.commits <= p.stats.ticks + 1);
    CHECK(hal.pairs_sent / hal.commits < 12);
}

int main(void) {
    static const ka_case cases[] = {
        {"tick_times_are_exact", test_tick_times_are_exact},
        {"late_calls_do_not_change_the_music", test_late_calls_do_not_change_the_music},
        {"rows_orders_and_loop", test_rows_orders_and_loop},
        {"end_of_song", test_end_of_song},
        {"jump_break_speed_tempo", test_jump_break_speed_tempo},
        {"notes_reach_the_hardware", test_notes_reach_the_hardware},
        {"pan", test_pan},
        {"envelope", test_envelope},
        {"pitch_effects", test_pitch_effects},
        {"pause_resume", test_pause_resume},
        {"preview_while_stopped", test_preview_while_stopped},
        {"mute_and_voice_mask", test_mute_and_voice_mask},
        {"reload_keeps_position", test_reload_keeps_position},
        {"mismatched_instrument_is_silent", test_mismatched_instrument_is_silent},
        {"whole_song_against_model", test_whole_song_against_model},
        {"exported_demo_song", test_exported_demo_song},
    };
    return ka_run(cases, sizeof cases / sizeof cases[0], "player");
}
