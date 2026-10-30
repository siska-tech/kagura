// SPDX-License-Identifier: Apache-2.0
// Procedural 320x240 RGB888 picture for the pseudo-256-colour demo: a sunset
// sky with stars, three hazy mountain ridges and a lake that mirrors them.
// Pure computation (an iq_source), so the PC test can render it too.
#ifndef IMG_SCENE_H
#define IMG_SCENE_H

#include <stdint.h>

void scene_init(void);   // fills the ridge and sine tables; call once first
void scene_rgb(void *ctx, unsigned x, unsigned y, uint8_t rgb[3]);

#endif
