// SPDX-License-Identifier: Apache-2.0
// Sends HAL frames over the RP2040 C host driver (software/pico/kagura_host.c),
// for standalone C programs that own the transport.
#include "ka_kagura_host.h"

kh_status ka_kh_send(const ka_audio *a, const ka_frame *f, uint32_t timeout_us) {
    kh_status s = KH_OK;
    for (unsigned w = 0; w < 2 && s == KH_OK; w++)
        if (f->wave_mask >> w & 1u)
            s = kh_vram_write(KA_WAVE_SHADOW + 256u * w, ka_wave_data(a, KA_WAVE_FIRST + w), f->wave_bytes[w]);
    for (unsigned i = 0; i < f->npairs && s == KH_OK; i++) s = kh_audio_write(f->pairs[2 * i], f->pairs[2 * i + 1]);
    if (s != KH_OK || !f->commit) return s;
    // AUDIO_COMMIT is refused while the previous one applies; wait for it here,
    // not after this one (the next send waits, so this one overlaps the caller).
    s = kh_ka_wait_idle(timeout_us);
    if (s == KH_OK) s = kh_write_reg(KAGURA_REG_COMMAND, KAGURA_CMD_AUDIO_COMMIT);
    if (s == KH_OK) s = kh_check_errors();
    return s;
}

kh_status kh_ka_wait_idle(uint32_t timeout_us) {
    uint32_t start = time_us_32();
    for (;;) {
        uint8_t st;
        kh_status s = kh_audio_read(KAGURA_AUDIO_STATUS, &st);
        if (s != KH_OK) return s;
        if (!(st & KAGURA_AUDIO_STATUS_APPLY_BUSY)) return KH_OK;
        if (time_us_32() - start >= timeout_us) return KH_TIMEOUT_STATUS;
    }
}
