// SPDX-License-Identifier: Apache-2.0
// HAL frames over kagura_host (RP2040, Pico SDK): wave uploads, register
// pairs, then AUDIO_COMMIT, as ka_audio.h describes. After a failure call
// ka_invalidate(): the next frame rewrites everything.
#ifndef KA_KAGURA_HOST_H
#define KA_KAGURA_HOST_H

#include "ka_audio.h"
#include "kagura_host.h"
#include "pico/time.h"

kh_status ka_kh_send(const ka_audio *a, const ka_frame *f, uint32_t timeout_us);
kh_status kh_ka_wait_idle(uint32_t timeout_us);   // AUDIO_STATUS.APPLY_BUSY low

#endif
