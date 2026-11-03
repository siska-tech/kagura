// SPDX-License-Identifier: Apache-2.0
#include "ka_audio.h"
#include <string.h>

// Register offsets and bits (software/include/kagura_regs.h, repeated here so
// the HAL builds without the include path; tests/test_hal.c checks they match).
enum {
    STEP_L = 0, STEP_M = 1, STEP_H = 2, DUTY = 3, GAIN_L = 4, GAIN_R = 5,
    CONTROL = 6, LEN_LOG2 = 7, NOISE_L = 8, NOISE_H = 9, FIELDS = 10,
    CONTROL_ENABLE = 1, CONTROL_PHASE_RESET = 2,
    MASTER_GAIN = 0xE0, PCM_BASE = 0x60, PCM_STRIDE = 0x20, PCM_CONTROL = 0x0E, PCM_CMD = 0x0F,
    PCM_CMD_STOP = 2,
    CAPS_HDMI_AUDIO = 1, CAPS_WAVE = 2, CAPS_PSRAM = 8,
};

// round(440 * 2^((n - 69) / 12) * 2^24 / 48000)
static const uint32_t note_steps[KA_NOTES] = {
    2858,3028,3208,3398,3600,3815,4041,4282,4536,4806,
    5092,5395,5715,6055,6415,6797,7201,7629,8083,8563,
    9072,9612,10184,10789,11431,12110,12830,13593,14402,15258,
    16165,17127,18145,19224,20367,21578,22861,24221,25661,27187,
    28803,30516,32331,34253,36290,38448,40734,43156,45722,48441,
    51322,54373,57607,61032,64661,68506,72580,76896,81468,86312,
    91445,96882,102643,108747,115213,122064,129322,137012,145160,153791,
    162936,172625,182890,193765,205287,217494,230426,244128,258645,274025,
    290319,307582,325872,345249,365779,387529,410573,434987,460853,488256,
    517290,548049,580638,615165,651744,690499,731558,775059,821146,869974,
    921705,976513,1034579,1096099,1161276,1230329,1303488,1380998,1463116,1550118,
    1642292,1739948,1843411,1953026,2069159,2192197,2322552,2460658,2606977,2761996,
    2926232,3100235,3284585,3479896,3686822,3906052,4138318,4384395,
};

// round(2^(i / 768) * 65536): i sixty-fourths of a semitone
static const uint32_t fine_q16[KA_FINE] = {
    65536,65595,65654,65714,65773,65832,65892,65951,
    66011,66071,66130,66190,66250,66309,66369,66429,
    66489,66549,66609,66670,66730,66790,66850,66911,
    66971,67032,67092,67153,67213,67274,67335,67395,
    67456,67517,67578,67639,67700,67761,67823,67884,
    67945,68007,68068,68129,68191,68252,68314,68376,
    68438,68499,68561,68623,68685,68747,68809,68871,
    68933,68996,69058,69120,69183,69245,69308,69370,
};

uint32_t ka_note_step(unsigned note, unsigned fine) {
    if (note >= KA_NOTES || fine >= KA_FINE) return 0;
    return (uint32_t)(((uint64_t)note_steps[note] * fine_q16[fine] + 32768u) >> 16);
}

// The LFSR advances every PERIOD+1 samples; a note clocks it at four times
// the note's frequency: PERIOD + 1 = 48000 / (4 f) = 2^22 / STEP.
uint16_t ka_note_noise(unsigned note) {
    uint32_t step = ka_note_step(note, 0);
    if (!step) return 0;
    uint32_t p = ((1u << 22) + step / 2) / step;
    if (p > 65536u) p = 65536u;
    return (uint16_t)(p ? p - 1 : 0);
}

uint32_t ka_hz_step(uint32_t millihertz) {
    uint64_t step = ((uint64_t)millihertz * 16777216u + 24000000u) / 48000000u;
    return step > KA_STEP_MAX ? KA_STEP_MAX : (uint32_t)step;
}

static bool is_wave(unsigned v) { return v >= KA_WAVE_FIRST && v < KA_VOICES; }
static bool is_tonal(unsigned v) { return v < KA_PULSE_VOICES || is_wave(v); }

static void want(ka_audio *a, unsigned v, unsigned off, uint8_t value) { a->want[v][off] = value; }

int ka_init(ka_audio *a, uint8_t caps) {
    if ((caps & (CAPS_HDMI_AUDIO | CAPS_WAVE)) != (CAPS_HDMI_AUDIO | CAPS_WAVE)) return KA_ENOTSUP;
    memset(a, 0, sizeof *a);
    a->caps = caps;
    for (unsigned v = 0; v < KA_PULSE_VOICES; v++) want(a, v, DUTY, 128);
    for (unsigned v = KA_WAVE_FIRST; v < KA_VOICES; v++) want(a, v, LEN_LOG2, 5);
    a->want_master = 32;
    ka_invalidate(a);
    return KA_OK;
}

void ka_invalidate(ka_audio *a) {
    memset(a->known, 0, sizeof a->known);
    a->master_known = false;
    a->wave_pending[0] = a->wave_pending[1] = 2;
}

// Offsets each voice kind uses; the others are reserved (writes ignored).
static uint16_t used_fields(unsigned v) {
    uint16_t m = 1u << GAIN_L | 1u << GAIN_R | 1u << CONTROL;
    if (v < KA_PULSE_VOICES) m |= 1u << STEP_L | 1u << STEP_M | 1u << STEP_H | 1u << DUTY;
    else if (v == KA_NOISE_VOICE) m |= 1u << NOISE_L | 1u << NOISE_H;
    else m |= 1u << STEP_L | 1u << STEP_M | 1u << STEP_H | 1u << LEN_LOG2;
    return m;
}

static void pair(ka_frame *f, unsigned index, uint8_t value) {
    f->pairs[2 * f->npairs] = (uint8_t)index;
    f->pairs[2 * f->npairs + 1] = value;
    f->npairs++;
}

int ka_flush(ka_audio *a, ka_frame *f) {
    f->npairs = 0;
    f->wave_mask = 0;
    f->wave_bytes[0] = f->wave_bytes[1] = 0;
    f->commit = false;
    for (unsigned v = 0; v < KA_VOICES; v++) {
        uint16_t used = used_fields(v);
        for (unsigned off = 0; off < FIELDS; off++) {
            if (!(used >> off & 1u)) continue;
            uint8_t value = a->want[v][off];
            bool reset = off == CONTROL && (a->retrigger >> v & 1u);
            if (!reset && (a->known[v] >> off & 1u) && a->have[v][off] == value) continue;
            pair(f, v * 16 + off, (uint8_t)(value | (reset ? CONTROL_PHASE_RESET : 0)));
            // AUDIO_COMMIT clears PHASE_RESET in the shadow once accepted.
            a->have[v][off] = value;
            a->known[v] |= (uint16_t)(1u << off);
        }
    }
    if (!a->master_known || a->have_master != a->want_master) {
        pair(f, MASTER_GAIN, a->want_master);
        a->have_master = a->want_master;
        a->master_known = true;
    }
    if (a->pcm_stop) {
        // CMD acts at once; CONTROL.ENABLE=0 is applied by the commit below.
        for (unsigned p = 0; p < 2; p++) {
            pair(f, PCM_BASE + p * PCM_STRIDE + PCM_CONTROL, 0);
            pair(f, PCM_BASE + p * PCM_STRIDE + PCM_CMD, PCM_CMD_STOP);
        }
        a->pcm_stop = false;
    }
    a->retrigger = 0;
    // A new wave of the same length changes no register but still needs a commit.
    f->commit = f->npairs > 0 || a->wave_changed;
    a->wave_changed = false;
    if (!f->commit) return KA_OK;   // no commit, no bank swap: pending waves wait
    // Every commit swaps the wave banks, so the shadow bank must hold the
    // wanted wave before it: after a change, before each of the next two.
    for (unsigned w = 0; w < 2; w++) {
        if (!a->wave_pending[w]) continue;
        f->wave_mask |= (uint8_t)(1u << w);
        f->wave_bytes[w] = (uint16_t)(1u << a->want[KA_WAVE_FIRST + w][LEN_LOG2]);
        a->wave_pending[w]--;
        a->wave_uploads++;
    }
    a->frames++;
    a->commits++;
    a->pairs_sent += f->npairs;
    return KA_OK;
}

const uint8_t *ka_wave_data(const ka_audio *a, unsigned voice) {
    return is_wave(voice) ? a->wave[voice - KA_WAVE_FIRST] : NULL;
}

int ka_set_step(ka_audio *a, unsigned voice, uint32_t step) {
    if (!is_tonal(voice) || step > KA_STEP_MAX) return KA_EINVAL;
    want(a, voice, STEP_L, (uint8_t)step);
    want(a, voice, STEP_M, (uint8_t)(step >> 8));
    want(a, voice, STEP_H, (uint8_t)(step >> 16));
    return KA_OK;
}

int ka_set_noise_period(ka_audio *a, uint16_t period) {
    want(a, KA_NOISE_VOICE, NOISE_L, (uint8_t)period);
    want(a, KA_NOISE_VOICE, NOISE_H, (uint8_t)(period >> 8));
    return KA_OK;
}

int ka_set_duty(ka_audio *a, unsigned voice, uint8_t duty) {
    if (voice >= KA_PULSE_VOICES) return KA_EINVAL;
    want(a, voice, DUTY, duty);
    return KA_OK;
}

int ka_set_gain(ka_audio *a, unsigned voice, uint8_t left, uint8_t right) {
    if (voice >= KA_VOICES) return KA_EINVAL;
    want(a, voice, GAIN_L, left);
    want(a, voice, GAIN_R, right);
    return KA_OK;
}

int ka_set_enable(ka_audio *a, unsigned voice, bool on) {
    if (voice >= KA_VOICES) return KA_EINVAL;
    want(a, voice, CONTROL, on ? CONTROL_ENABLE : 0);
    return KA_OK;
}

int ka_retrigger(ka_audio *a, unsigned voice) {
    if (voice >= KA_VOICES) return KA_EINVAL;
    a->retrigger |= (uint8_t)(1u << voice);
    return KA_OK;
}

int ka_set_wave(ka_audio *a, unsigned voice, const uint8_t *samples, size_t n) {
    if (!is_wave(voice)) return KA_EINVAL;
    unsigned log2 = n == 32 ? 5 : n == 64 ? 6 : n == 128 ? 7 : n == 256 ? 8 : 0;
    if (!log2) return KA_EINVAL;
    unsigned w = voice - KA_WAVE_FIRST;
    if (a->want[voice][LEN_LOG2] == log2 && !memcmp(a->wave[w], samples, n)) return KA_OK;
    memcpy(a->wave[w], samples, n);
    want(a, voice, LEN_LOG2, (uint8_t)log2);
    a->wave_pending[w] = 2;
    a->wave_changed = true;
    return KA_OK;
}

int ka_set_master(ka_audio *a, uint8_t gain) {
    a->want_master = gain;
    return KA_OK;
}

int ka_set_pitch(ka_audio *a, unsigned voice, unsigned note, unsigned fine) {
    if (voice >= KA_VOICES || note >= KA_NOTES || fine >= KA_FINE) return KA_EINVAL;
    if (voice == KA_NOISE_VOICE) return ka_set_noise_period(a, ka_note_noise(note));
    return ka_set_step(a, voice, ka_note_step(note, fine));
}

void ka_silence(ka_audio *a, bool pcm) {
    for (unsigned v = 0; v < KA_VOICES; v++) want(a, v, CONTROL, 0);
    a->retrigger = 0;
    if (pcm && (a->caps & CAPS_PSRAM)) a->pcm_stop = true;
}
