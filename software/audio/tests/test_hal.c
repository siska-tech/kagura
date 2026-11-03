// SPDX-License-Identifier: Apache-2.0
// Audio HAL: note tables, the write cache, wave banks and recovery, checked
// against a model of the FPGA's AUDIO_COMMIT semantics (ka_model.h).
#include <math.h>
#include "ka_audio.h"
#include "ka_model.h"
#include "ka_render.h"
#include "ka_test.h"
#include "kagura_regs.h"

#define FULL_CAPS (KAGURA_CAPS_HDMI_AUDIO | KAGURA_CAPS_WAVE | KAGURA_CAPS_PSRAM)

static ka_audio a;
static ka_frame f;
static ka_model m;

static void flush_send(void) {
    ka_flush(&a, &f);
    ka_model_send(&m, &a, &f);
}

static void start(uint8_t caps) {
    ka_model_init(&m);
    // Garbage in the hardware from an earlier owner: init must not trust it.
    for (unsigned i = 0; i < 0x60; i++) m.active[i] = m.shadow[i] = (uint8_t)(i * 37 + 1);
    for (unsigned v = 0; v < KA_VOICES; v++) m.shadow[v * 16 + 2] &= 0x7F;
    m.shadow[4 * 16 + 7] = m.shadow[5 * 16 + 7] = 6;
    memset(m.bank, 0x55, sizeof m.bank);
    ka_init(&a, caps);
}

static void test_registers_match_abi(void) {
    // ka_audio.c repeats these to build without the include path.
    CHECK_EQ(KAGURA_AUDIO_CH_STRIDE, 16);
    CHECK_EQ(KAGURA_AUDIO_STEP_L, 0);
    CHECK_EQ(KAGURA_AUDIO_DUTY, 3);
    CHECK_EQ(KAGURA_AUDIO_GAIN_L, 4);
    CHECK_EQ(KAGURA_AUDIO_GAIN_R, 5);
    CHECK_EQ(KAGURA_AUDIO_CONTROL, 6);
    CHECK_EQ(KAGURA_AUDIO_LEN_LOG2, 7);
    CHECK_EQ(KAGURA_AUDIO_NOISE_PERIOD_L, 8);
    CHECK_EQ(KAGURA_AUDIO_NOISE_PERIOD_H, 9);
    CHECK_EQ(KAGURA_AUDIO_MASTER_GAIN, 0xE0);
    CHECK_EQ(KAGURA_AUDIO_CONTROL_ENABLE, 1);
    CHECK_EQ(KAGURA_AUDIO_CONTROL_PHASE_RESET, 2);
    CHECK_EQ(KAGURA_AUDIO_PCM_BASE, 0x60);
    CHECK_EQ(KAGURA_AUDIO_PCM_STRIDE, 0x20);
    CHECK_EQ(KAGURA_AUDIO_PCM_CONTROL, 0x0E);
    CHECK_EQ(KAGURA_AUDIO_PCM_CMD, 0x0F);
    CHECK_EQ(KAGURA_AUDIO_LEN_LOG2_RESET, 5);
    CHECK_EQ(KAGURA_AUDIO_MASTER_GAIN_RESET, 32);
    CHECK_EQ(KA_WAVE_SHADOW, 0x9800);
}

static void test_note_tables(void) {
    for (unsigned n = 0; n < KA_NOTES; n++)
        for (unsigned fine = 0; fine < KA_FINE; fine++) {
            double hz = 440.0 * pow(2.0, ((double)n - 69.0 + fine / 64.0) / 12.0);
            double exact = hz * 16777216.0 / 48000.0;
            CHECK(fabs(ka_note_step(n, fine) - exact) <= 1.0 + exact * 1e-5);
        }
    CHECK_EQ(ka_note_step(69, 0), 153791);   // docs/audio-spec.md: STEP(440 Hz)
    CHECK_EQ(ka_note_step(128, 0), 0);
    CHECK_EQ(ka_note_step(0, 64), 0);
    CHECK(ka_note_step(127, 63) <= KA_STEP_MAX);
    CHECK_EQ(ka_hz_step(440000), 153791);
    CHECK_EQ(ka_hz_step(0xFFFFFFFFu), KA_STEP_MAX);
    // Higher notes clock the noise faster; the period fits 16 bits.
    for (unsigned n = 1; n < KA_NOTES; n++) CHECK(ka_note_noise(n) <= ka_note_noise(n - 1));
    CHECK(ka_note_noise(0) > 1000);
    CHECK(ka_note_noise(127) == 0);
}

static void test_init_writes_everything_once(void) {
    start(FULL_CAPS);
    CHECK_EQ(ka_init(&a, KAGURA_CAPS_HDMI_AUDIO), KA_ENOTSUP);
    CHECK_EQ(ka_init(&a, FULL_CAPS), KA_OK);
    flush_send();
    CHECK_EQ(f.npairs, 41);          // 3x7 pulse + 5 noise + 2x7 wave + master
    CHECK(f.commit);
    CHECK_EQ(f.wave_mask, 3);
    CHECK_EQ(f.wave_bytes[0], 32);
    CHECK(ka_model_matches(&m, &a));
    flush_send();
    CHECK_EQ(f.npairs, 0);
    CHECK(!f.commit);
    CHECK_EQ(f.wave_mask, 0);        // no commit: the second bank waits
    CHECK_EQ(m.rejected, 0);
}

static void test_cache_sends_only_changes(void) {
    start(FULL_CAPS);
    flush_send();
    ka_set_gain(&a, 1, 100, 50);
    flush_send();
    CHECK_EQ(f.npairs, 2);
    CHECK_EQ(f.pairs[0], 0x14);
    CHECK_EQ(f.pairs[1], 100);
    CHECK_EQ(f.pairs[2], 0x15);
    CHECK_EQ(f.pairs[3], 50);
    CHECK(f.commit);
    ka_set_gain(&a, 1, 100, 50);     // same value: nothing to send
    flush_send();
    CHECK_EQ(f.npairs, 0);
    ka_set_pitch(&a, 0, 69, 0);
    flush_send();
    CHECK_EQ(f.npairs, 3);           // STEP L/M/H
    ka_set_pitch(&a, 0, 69, 1);
    flush_send();
    CHECK(f.npairs >= 1 && f.npairs <= 2);   // STEP_H is the same
    CHECK(ka_model_matches(&m, &a));
}

static void test_retrigger_and_phase_reset(void) {
    start(FULL_CAPS);
    ka_set_enable(&a, 2, true);
    flush_send();
    unsigned before = m.phase_resets[2];
    ka_retrigger(&a, 2);             // CONTROL unchanged, but the reset is sent
    flush_send();
    CHECK_EQ(f.npairs, 1);
    CHECK_EQ(f.pairs[0], 0x26);
    CHECK_EQ(f.pairs[1], 3);
    CHECK_EQ(m.phase_resets[2], before + 1);
    CHECK_EQ(m.shadow[0x26], 1);     // cleared by the commit, as the hardware does
    flush_send();
    CHECK_EQ(f.npairs, 0);
    CHECK(ka_model_matches(&m, &a));
}

static void test_wave_banks(void) {
    start(FULL_CAPS);
    flush_send();
    ka_set_master(&a, 33);           // a second commit fills the other bank
    flush_send();
    CHECK_EQ(f.wave_mask, 3);
    uint8_t w[64];
    for (unsigned i = 0; i < 64; i++) w[i] = (uint8_t)(i * 4);
    CHECK_EQ(ka_set_wave(&a, 4, w, 64), KA_OK);
    flush_send();                    // LEN_LOG2 changed: a commit, first upload
    CHECK_EQ(f.wave_mask, 1);
    CHECK_EQ(f.wave_bytes[0], 64);
    CHECK(ka_model_matches(&m, &a));
    flush_send();                    // nothing else changed: no commit, no upload
    CHECK_EQ(f.wave_mask, 0);
    ka_set_gain(&a, 0, 1, 1);        // any later commit swaps banks: second upload
    flush_send();
    CHECK_EQ(f.wave_mask, 1);
    CHECK(ka_model_matches(&m, &a));
    ka_set_gain(&a, 0, 2, 2);
    flush_send();
    CHECK_EQ(f.wave_mask, 0);        // both banks hold it now
    CHECK(ka_model_matches(&m, &a));
    CHECK_EQ(ka_set_wave(&a, 4, w, 64), KA_OK);   // same wave: no upload
    ka_set_gain(&a, 0, 3, 3);
    flush_send();
    CHECK_EQ(f.wave_mask, 0);
    CHECK_EQ(ka_set_wave(&a, 3, w, 64), KA_EINVAL);
    CHECK_EQ(ka_set_wave(&a, 5, w, 48), KA_EINVAL);
}

static void test_invalid_arguments_change_nothing(void) {
    start(FULL_CAPS);
    flush_send();
    ka_audio before = a;
    CHECK_EQ(ka_set_step(&a, 0, KA_STEP_MAX + 1), KA_EINVAL);
    CHECK_EQ(ka_set_step(&a, 3, 100), KA_EINVAL);
    CHECK_EQ(ka_set_step(&a, 6, 100), KA_EINVAL);
    CHECK_EQ(ka_set_duty(&a, 4, 10), KA_EINVAL);
    CHECK_EQ(ka_set_gain(&a, 6, 1, 1), KA_EINVAL);
    CHECK_EQ(ka_set_enable(&a, 9, true), KA_EINVAL);
    CHECK_EQ(ka_retrigger(&a, 6), KA_EINVAL);
    CHECK_EQ(ka_set_pitch(&a, 0, 128, 0), KA_EINVAL);
    CHECK_EQ(ka_set_pitch(&a, 0, 60, 64), KA_EINVAL);
    CHECK(!memcmp(&before, &a, sizeof a));
}

static void test_silence_and_pcm(void) {
    start(FULL_CAPS);
    for (unsigned v = 0; v < KA_VOICES; v++) {
        ka_set_gain(&a, v, 200, 200);
        ka_set_enable(&a, v, true);
    }
    flush_send();
    ka_silence(&a, true);
    flush_send();
    CHECK_EQ(f.npairs, 6 + 4);
    CHECK_EQ(m.pcm_stops, 2);
    for (unsigned v = 0; v < KA_VOICES; v++) CHECK_EQ(m.active[v * 16 + 6] & 1, 0);
    CHECK(ka_model_matches(&m, &a));
    // Without PSRAM the PCM registers do not exist: never written.
    start(KAGURA_CAPS_HDMI_AUDIO | KAGURA_CAPS_WAVE);
    flush_send();
    ka_silence(&a, true);
    flush_send();
    for (unsigned i = 0; i < f.npairs; i++) CHECK(f.pairs[2 * i] < 0x60 || f.pairs[2 * i] == 0xE0);
}

static void test_invalidate_recovers_from_another_owner(void) {
    start(FULL_CAPS);
    ka_set_gain(&a, 4, 9, 9);
    ka_set_enable(&a, 4, true);
    flush_send();
    flush_send();
    // Someone else (kagura.audio.Audio, a crash mid-frame) changes the hardware.
    m.shadow[0x46] = 0;
    m.shadow[0x44] = 255;
    memset(m.bank, 0x11, sizeof m.bank);
    ka_model_commit(&m);
    CHECK(!ka_model_matches(&m, &a));
    ka_invalidate(&a);
    flush_send();
    CHECK(ka_model_matches(&m, &a));
    ka_set_gain(&a, 0, 1, 2);
    flush_send();                    // second bank rewritten with the next commit
    CHECK(ka_model_matches(&m, &a));
}

// Random calls; after every flushed frame the modelled hardware plays exactly
// what the HAL wants and no commit is rejected.
static void test_random_against_model(void) {
    uint32_t seed = 12345;
    start(FULL_CAPS);
    uint8_t w[256];
    unsigned uploads = 0, frames = 0;
    for (unsigned i = 0; i < 200000; i++) {
        unsigned v = ka_rand(&seed) % KA_VOICES, op = ka_rand(&seed) % 12;
        switch (op) {
        case 0: ka_set_pitch(&a, v, ka_rand(&seed) % 128, ka_rand(&seed) % 64); break;
        case 1: ka_set_gain(&a, v, (uint8_t)ka_rand(&seed), (uint8_t)ka_rand(&seed)); break;
        case 2: ka_set_enable(&a, v, ka_rand(&seed) & 1); break;
        case 3: ka_retrigger(&a, v); break;
        case 4: ka_set_duty(&a, v, (uint8_t)ka_rand(&seed)); break;
        case 5: {
            size_t n = (size_t)32 << (ka_rand(&seed) % 4);
            for (size_t k = 0; k < n; k++) w[k] = (uint8_t)ka_rand(&seed);
            ka_set_wave(&a, KA_WAVE_FIRST + v % 2, w, n);
            break;
        }
        case 6: ka_set_master(&a, (uint8_t)ka_rand(&seed)); break;
        case 7: ka_set_noise_period(&a, (uint16_t)ka_rand(&seed)); break;
        case 8: if (ka_rand(&seed) % 50 == 0) ka_silence(&a, true); break;
        case 9: if (ka_rand(&seed) % 200 == 0) ka_invalidate(&a); break;
        default: {
            flush_send();
            frames++;
            uploads += (f.wave_mask & 1) + (f.wave_mask >> 1);
            CHECK(f.npairs <= KA_FRAME_PAIRS);
            CHECK(ka_model_matches(&m, &a));
            break;
        }
        }
    }
    CHECK_EQ(m.rejected, 0);
    CHECK(frames > 30000);
    CHECK(uploads > 1000);
}

static void test_render(void) {
    start(FULL_CAPS);
    int8_t out[64];
    CHECK_EQ(ka_render(&a, 0x3F, out, 64, 512), 0);          // all voices off: silence
    for (unsigned i = 0; i < 64; i++) CHECK_EQ(out[i], 0);
    // Pulse 0, duty 128, a period of exactly 64 samples (STEP 2^24 / 64), full gain.
    ka_set_step(&a, 0, 1u << 18);
    ka_set_duty(&a, 0, 128);
    ka_set_gain(&a, 0, 255, 255);
    ka_set_enable(&a, 0, true);
    CHECK_EQ(ka_render(&a, 0x01, out, 64, 64), 0x01);
    for (unsigned i = 0; i < 64; i++) CHECK_EQ(out[i], i < 32 ? 127 : -127);
    ka_set_duty(&a, 0, 64);                                   // 25 %
    ka_render(&a, 0x01, out, 64, 64);
    CHECK(out[15] > 0 && out[16] < 0);
    ka_set_gain(&a, 0, 128, 128);                             // half gain: half height
    ka_render(&a, 0x01, out, 64, 64);
    CHECK_EQ(out[0], 127 * 128 / 255);
    // Wave 4: its table, 32 samples over 32 points of one period.
    uint8_t w[32];
    for (unsigned i = 0; i < 32; i++) w[i] = (uint8_t)(int8_t)(i * 8 - 128);
    ka_set_wave(&a, 4, w, 32);
    ka_set_step(&a, 4, 1u << 19);                             // 32 samples per period
    ka_set_gain(&a, 4, 255, 255);
    ka_set_enable(&a, 4, true);
    int8_t pts[32];
    CHECK_EQ(ka_render(&a, 0x10, pts, 32, 32), 0x10);
    for (unsigned i = 0; i < 32; i++) {
        int v = (int)(i * 8) - 128;
        CHECK_EQ(pts[i], v < -127 ? -127 : v);                // the picture is clamped to +-127
    }
    // Noise: the spec's LFSR from state 1, PERIOD 0 (a new bit every sample).
    ka_set_noise_period(&a, 0);
    ka_set_gain(&a, 3, 255, 255);
    ka_set_enable(&a, 3, true);
    int8_t nz[40];
    ka_render(&a, 0x08, nz, 40, 40);
    uint16_t s = 1;
    for (unsigned i = 0; i < 40; i++) {
        CHECK_EQ(nz[i], (s >> 14 & 1u) ? 127 : -127);
        s = (uint16_t)(((s << 1) | ((s >> 14 ^ s >> 13) & 1u)) & 0x7FFF);
    }
    // Mixed: two full voices fill the height, the mask names those drawn.
    ka_set_gain(&a, 0, 255, 255);
    ka_set_duty(&a, 0, 128);
    CHECK_EQ(ka_render(&a, 0x3F, out, 64, 64), 0x19);
    ka_set_enable(&a, 3, false);
    ka_set_enable(&a, 4, false);
    CHECK_EQ(ka_render(&a, 0x3F, out, 64, 64), 0x01);
    CHECK_EQ(out[0], 127);                                    // one voice: its own level
    // Rendering never sends anything.
    ka_flush(&a, &f);
    ka_audio before = a;
    ka_render(&a, 0x3F, out, 64, 4096);
    CHECK(!memcmp(&before, &a, sizeof a));
}

int main(void) {
    static const ka_case cases[] = {
        {"registers_match_abi", test_registers_match_abi},
        {"note_tables", test_note_tables},
        {"init_writes_everything_once", test_init_writes_everything_once},
        {"cache_sends_only_changes", test_cache_sends_only_changes},
        {"retrigger_and_phase_reset", test_retrigger_and_phase_reset},
        {"wave_banks", test_wave_banks},
        {"invalid_arguments_change_nothing", test_invalid_arguments_change_nothing},
        {"silence_and_pcm", test_silence_and_pcm},
        {"invalidate_recovers_from_another_owner", test_invalidate_recovers_from_another_owner},
        {"random_against_model", test_random_against_model},
        {"render", test_render},
    };
    return ka_run(cases, sizeof cases / sizeof cases[0], "hal");
}
