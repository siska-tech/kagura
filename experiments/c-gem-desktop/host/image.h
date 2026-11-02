// SPDX-License-Identifier: Apache-2.0
// Host-only image output: indexed PNG (stored deflate, no zlib dependency).
#ifndef KD_IMAGE_H
#define KD_IMAGE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "kd_fb.h"

// Writes w x h palette indices (one byte each) with the desktop palette.
bool kd_write_png_indexed(const char *path, const uint8_t *idx, int w, int h);
// The framebuffer at an integer scale; when kagura240 is set the 320x200
// plane is placed in a 320x240 frame as on hardware (centre placement,
// border lines show palette entry 0 = BACKDROP).
bool kd_write_fb_png(const char *path, const kd_fb *fb, int scale, bool kagura240);
uint32_t kd_crc32(const uint8_t *data, size_t n);

#endif
