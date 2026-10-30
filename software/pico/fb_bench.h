// SPDX-License-Identifier: Apache-2.0
#ifndef FB_BENCH_H
#define FB_BENCH_H

#include "tile_fb.h"

// The one framebuffer, shared with `fbdemo`: a RAM-only build has no room
// for a second 39.6 KB instance.
extern tile_fb kagura_fb;

#define FB_BENCH_FULL 1u   // read back all 38400 pattern bytes
#define FB_BENCH_PCM 2u    // PCM 2ch looping triangles from PSRAM, as framebuffer_diagnostic pcm_start()
#define FB_BENCH_PSG 4u    // pulse 3 + noise + wavetable 2, held for the whole run

// `fbbench`: C TileFramebuffer benchmark on a 480p ABI 0.6 bitstream. Takes
// over the whole screen; reps 1..256 per measurement, seconds 0..600 for the
// continuous loop. Audio enabled by flags plays throughout and is stopped at
// the end; its status is checked after every section and loop iteration.
void kagura_fb_bench(unsigned reps, unsigned seconds, unsigned flags);

#endif
