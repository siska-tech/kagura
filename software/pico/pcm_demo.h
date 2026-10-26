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
// Looping melody + retriggered recorded piano note on the two PCM channels;
// 0 runs until a key. SWAP puts the note on PCM 0 and the melody on PCM 1,
// MOVE exchanges their PSRAM locations, SOLO leaves the melody off, MUTE
// plays (reads) the melody at gain 0, MUTE_NOTE the note at gain 0, NONOTE
// never starts the note, ZERO uploads silence in place of the note.
// master >= 0 sets MASTER_GAIN first.
#define PCM_DEMO_SWAP 1u
#define PCM_DEMO_MOVE 2u
#define PCM_DEMO_SOLO 4u
#define PCM_DEMO_MUTE 8u
#define PCM_DEMO_MUTE_NOTE 16u
#define PCM_DEMO_NONOTE 32u
#define PCM_DEMO_ZERO 64u
kh_status kagura_pcm_demo(uint32_t seconds, unsigned flags, int master);

#endif
