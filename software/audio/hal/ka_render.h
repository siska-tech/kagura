// SPDX-License-Identifier: Apache-2.0
// A synthesized waveform from the HAL's wanted state, for display only (an
// estimate: the hardware's output cannot be captured without RTL changes).
#ifndef KA_RENDER_H
#define KA_RENDER_H

#include "ka_audio.h"

// Renders n points spanning `span` 48 kHz samples of the enabled voices in
// `voices` (bit per voice), each from phase 0, mixed with their gains:
// one voice is shown at its own level, several so that two full voices fill
// -127..127. Returns the mask of voices drawn (0: silence, out all zero).
unsigned ka_render(const ka_audio *a, uint8_t voices, int8_t *out, unsigned n, unsigned span);

#endif
