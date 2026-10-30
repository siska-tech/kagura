// SPDX-License-Identifier: Apache-2.0
#ifndef FB_DEMO_H
#define FB_DEMO_H

#include "kagura_host.h"

// `fbdemo`: four C TileFramebuffer scenes (palette-cycled plasma and tunnel,
// a rotating tesseract over stars, a rainbow line ribbon) with PSG music, on
// a 480p ABI 0.6 bitstream. Each frame ends with a palette COMMIT, which
// waits for VBlank. seconds 0 runs until a key is received over USB CDC.
kh_status kagura_fb_demo(unsigned seconds);

#endif
