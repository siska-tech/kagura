// SPDX-License-Identifier: Apache-2.0
// A synthesized picture of what the HAL wants the voices to play, for an
// oscilloscope view. It is NOT the hardware's output: KAGURA-9 has no audio
// capture path. Each voice starts at phase 0 (a stable, "triggered" picture),
// and the noise LFSR starts from its reset state. Pure function, no hardware.
#include "ka_render.h"

static int voice_sample(const ka_audio *a, unsigned v, uint32_t phase, uint16_t *lfsr, uint32_t *count) {
    const uint8_t *r = a->want[v];
    if (v < KA_PULSE_VOICES) return (phase >> 16 & 255) < r[3] ? 127 : -127;
    if (v == KA_NOISE_VOICE) {
        // docs/audio-spec.md: the sample is state[14] before the update; the
        // LFSR advances every PERIOD+1 samples.
        int s = (*lfsr >> 14 & 1u) ? 127 : -127;
        uint32_t period = r[8] | (uint32_t)r[9] << 8;
        if (*count == 0) {
            *lfsr = (uint16_t)(((*lfsr << 1) | ((*lfsr >> 14 ^ *lfsr >> 13) & 1u)) & 0x7FFF);
            *count = period;
        } else {
            (*count)--;
        }
        return s;
    }
    unsigned log2 = r[7];
    return (int8_t)a->wave[v - KA_WAVE_FIRST][phase >> (24 - log2)];
}

unsigned ka_render(const ka_audio *a, uint8_t voices, int8_t *out, unsigned n, unsigned span) {
    if (!n || !span) return 0;
    unsigned active = 0;
    for (unsigned v = 0; v < KA_VOICES; v++)
        if ((voices >> v & 1u) && (a->want[v][6] & 1u)) active |= 1u << v;
    for (unsigned i = 0; i < n; i++) out[i] = 0;
    if (!active) return 0;
    bool single = (active & (active - 1)) == 0;
    // Mixed: two voices at full gain fill the height. Single: the voice's own level.
    int32_t div = single ? 255 : 2 * 255;
    uint32_t phase[KA_VOICES] = {0}, count[KA_VOICES] = {0};
    uint16_t lfsr = 1;
    unsigned at = 0;
    for (unsigned s = 0; s < span && at < n; s++) {
        int32_t acc = 0;
        for (unsigned v = 0; v < KA_VOICES; v++) {
            if (!(active >> v & 1u)) continue;
            const uint8_t *r = a->want[v];
            int gain = (r[4] + r[5]) / 2;
            acc += voice_sample(a, v, phase[v], &lfsr, &count[v]) * gain;
            uint32_t step = r[0] | (uint32_t)r[1] << 8 | (uint32_t)r[2] << 16;
            phase[v] = (phase[v] + step) & 0xFFFFFFu;
        }
        // Point i shows sample floor(i * span / n).
        while (at < n && (uint64_t)at * span / n == s) {
            int32_t y = acc / div;
            out[at++] = (int8_t)(y > 127 ? 127 : y < -127 ? -127 : y);
        }
    }
    return active;
}
