// SPDX-License-Identifier: Apache-2.0
// Model of the FPGA audio registers (docs/audio-spec.md#audio_commit) for the
// host tests: shadow and active registers, two wave banks swapped by every
// AUDIO_COMMIT, PHASE_RESET cleared in the shadow on acceptance, commits with
// a bad STEP or LEN_LOG2 rejected. It receives frames as the transport would.
#ifndef KA_MODEL_H
#define KA_MODEL_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ka_audio.h"

typedef struct {
    uint8_t shadow[256], active[256];
    uint8_t bank[2][512];      // [bank][voice 4 then 5 x 256]
    unsigned shadow_bank;
    unsigned commits, rejected, phase_resets[KA_VOICES], pcm_stops;
} ka_model;

static void ka_model_init(ka_model *m) {
    memset(m, 0, sizeof *m);
    m->shadow[4 * 16 + 7] = m->shadow[5 * 16 + 7] = 5;
    m->shadow[0xE0] = 32;
    memcpy(m->active, m->shadow, sizeof m->active);
}

static int ka_model_commit(ka_model *m) {
    for (unsigned v = 0; v < KA_VOICES; v++) {
        const uint8_t *r = m->shadow + v * 16;
        if (v != KA_NOISE_VOICE && (r[2] & 0x80)) return 0;
        if (v >= KA_WAVE_FIRST && (r[7] < 5 || r[7] > 8)) return 0;
    }
    for (unsigned v = 0; v < KA_VOICES; v++) {
        if (m->shadow[v * 16 + 6] & 2) m->phase_resets[v]++;
        m->shadow[v * 16 + 6] &= (uint8_t)~2;
    }
    memcpy(m->active, m->shadow, 0x60);
    m->active[0xE0] = m->shadow[0xE0];
    m->shadow_bank ^= 1;
    m->commits++;
    return 1;
}

static void ka_model_send(ka_model *m, const ka_audio *a, const ka_frame *f) {
    for (unsigned w = 0; w < 2; w++)
        if (f->wave_mask >> w & 1u)
            memcpy(m->bank[m->shadow_bank] + w * 256, ka_wave_data(a, KA_WAVE_FIRST + w), f->wave_bytes[w]);
    for (unsigned i = 0; i < f->npairs; i++) {
        uint8_t index = f->pairs[2 * i], value = f->pairs[2 * i + 1];
        if (index >= 0x60 && index < 0xA0 && (index - 0x60) % 0x20 == 0x0F) {
            if (value & 2) m->pcm_stops++;
            continue;
        }
        m->shadow[index] = value;
    }
    if (f->commit && !ka_model_commit(m)) m->rejected++;
}

// The active bank (the one not in shadow) holds what each wave voice plays.
static const uint8_t *ka_model_wave(const ka_model *m, unsigned voice) {
    return m->bank[m->shadow_bank ^ 1] + (voice - KA_WAVE_FIRST) * 256;
}

// What the hardware plays equals what the HAL wants (fields each voice uses).
static int ka_model_matches(const ka_model *m, const ka_audio *a) {
    for (unsigned v = 0; v < KA_VOICES; v++)
        for (unsigned off = 0; off < 10; off++) {
            bool used = off == 4 || off == 5 || off == 6 ||
                        (v < 3 && off <= 3) || (v == 3 && off >= 8) || (v >= 4 && (off <= 2 || off == 7));
            if (used && m->active[v * 16 + off] != a->want[v][off]) {
                fprintf(stderr, "voice %u offset %u: hardware %u, wanted %u\n", v, off,
                        m->active[v * 16 + off], a->want[v][off]);
                return 0;
            }
        }
    if (m->active[0xE0] != a->want_master) return 0;
    for (unsigned v = KA_WAVE_FIRST; v < KA_VOICES; v++) {
        size_t n = (size_t)1 << a->want[v][7];
        if (memcmp(ka_model_wave(m, v), ka_wave_data(a, v), n)) {
            fprintf(stderr, "wave %u differs\n", v);
            return 0;
        }
    }
    return 1;
}

#endif
