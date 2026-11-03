// SPDX-License-Identifier: Apache-2.0
// A synthesized picture of what the HAL wants the voices to play, for an
// oscilloscope view. It is NOT the hardware's output: KAGURA-9 has no audio
// capture path. Each voice starts at phase 0 (a stable, "triggered" picture),
// and the noise LFSR starts from its reset state. Pure function, no hardware.
#include "ka_render.h"

// The noise voice's sample at each sample index, advanced one sample at a
// time (docs/audio-spec.md: the output is state[14] before the update; the
// LFSR advances every PERIOD+1 samples).
typedef struct {
    uint16_t lfsr;
    uint32_t count, period, at;
} noise_state;

static int noise_at(noise_state *ns, uint32_t s) {
    while (ns->at < s) {
        if (ns->count == 0) {
            ns->lfsr = (uint16_t)(((ns->lfsr << 1) | ((ns->lfsr >> 14 ^ ns->lfsr >> 13) & 1u)) & 0x7FFF);
            ns->count = ns->period;
        } else {
            ns->count--;
        }
        ns->at++;
    }
    return (ns->lfsr >> 14 & 1u) ? 127 : -127;
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
    const uint8_t *nr = a->want[KA_NOISE_VOICE];
    noise_state ns = {1, 0, (uint32_t)(nr[8] | nr[9] << 8), 0};
    // Point i shows sample floor(i * span / n). A pulse or wave voice's phase
    // at sample s is s * STEP (mod 2^24), so only the points are computed;
    // the noise LFSR is stepped through the samples between them.
    for (unsigned i = 0; i < n; i++) {
        uint32_t s = (uint32_t)((uint64_t)i * span / n);
        int32_t acc = 0;
        for (unsigned v = 0; v < KA_VOICES; v++) {
            if (!(active >> v & 1u)) continue;
            const uint8_t *r = a->want[v];
            int gain = (r[4] + r[5]) / 2, x;
            if (v == KA_NOISE_VOICE) {
                x = noise_at(&ns, s);
            } else {
                uint32_t step = r[0] | (uint32_t)r[1] << 8 | (uint32_t)r[2] << 16;
                uint32_t phase = (uint32_t)((uint64_t)s * step) & 0xFFFFFFu;
                x = v < KA_PULSE_VOICES ? ((phase >> 16 & 255) < r[3] ? 127 : -127)
                                        : (int8_t)a->wave[v - KA_WAVE_FIRST][phase >> (24 - r[7])];
            }
            acc += x * gain;
        }
        int32_t y = acc / div;
        out[i] = (int8_t)(y > 127 ? 127 : y < -127 ? -127 : y);
    }
    return active;
}
