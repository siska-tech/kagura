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

// PSRAM slideshow (CAPS PSRAM). Slot n (0..15) at 0x600000 + n * 64 KiB,
// clear of the PCM samples at 0x400000..: patterns (38400 B), then the 30
// map rows (128 B each) at +0x9600, then the palettes at brightness 0..16
// (512 B each) at +0xA500.
#define IMG_SLOTS 16u
#define IMG_SLOT_BASE 0x600000u
#define IMG_SLOT_SIZE 0x10000u

// `imgdemo save n`: stores the picture on screen (from gen or recv, while
// the framebuffer still holds it) in slot n.
kh_status kagura_img_save(unsigned slot);

// `imgdemo slide`: cycles the saved slots for `seconds` (0 = until a key),
// each held hold_ms. A change fades out by COPYing the darker palettes of
// the slot on screen, COPYs patterns and map while black, and fades in the
// same way, so the Pico sends only commands.
kh_status kagura_img_slide(unsigned seconds, unsigned hold_ms);

#endif
