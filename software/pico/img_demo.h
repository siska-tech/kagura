// SPDX-License-Identifier: Apache-2.0
#ifndef IMG_DEMO_H
#define IMG_DEMO_H

#include <stdbool.h>
#include "kagura_host.h"

// Wire format of `imgdemo recv` after the "IMG READY" line: the magic
// "KIMG", 256 RGB444 palette words (little endian), 1200 cell palettes,
// 38400 tile-native 4bpp pixel bytes, then the CRC-32 (zlib) of those three
// as 4 little-endian bytes.
#define IMG_MAGIC "KIMG"
#define IMG_PAYLOAD (512u + 1200u + 38400u)

// `imgdemo`: a pseudo-256-colour picture (16 palettes x 16 colours, one
// palette per 8x8 cell) on the 480p ABI 0.6 TileFramebuffer, faded in. The
// picture is computed and quantized on the Pico, or received from the PC
// (software/pico/send_image.py) when receive is true. It stays on screen.
kh_status kagura_img_demo(bool receive);

#endif
