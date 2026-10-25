// SPDX-License-Identifier: Apache-2.0
#ifndef KAGURA_PCM_DEMO_H
#define KAGURA_PCM_DEMO_H

#include <stddef.h>
#include <stdint.h>
#include "kagura_host.h"

// PSRAM upload/FENCE/readback compare of len (1..2048) random bytes.
kh_status kagura_psram_test(size_t len);
// COMMAND COPY of len (1..2048) random bytes PSRAM -> pattern VRAM, compared, plus a 32 KiB timing copy.
kh_status kagura_copy_test(size_t len);
// Debug bitstreams only: capture and print the PSRAM pins of one write/read.
kh_status kagura_psram_debug(bool on_read, uint8_t value);
// Looping melody + retriggered drum on the two PCM channels; 0 runs until a key.
kh_status kagura_pcm_demo(uint32_t seconds);

#endif
