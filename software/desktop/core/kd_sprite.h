// SPDX-License-Identifier: Apache-2.0
// 16x16 4bpp sprite in TILE4 order, byte-compatible with KAGURA-UI Sprite4
// and with a 16x16 hardware sprite (four patterns: TL, TR, BL, BR). Pixel
// (x,y) is byte ((y/8)*2 + x/8)*32 + (y%8)*4 + (x%8)/2, even x high nibble.
// In sprite data colour 0 means transparent; the desktop draws sprites with
// an explicit key when it wants that meaning.
#ifndef KD_SPRITE_H_INCLUDED
#define KD_SPRITE_H_INCLUDED

#include <stdbool.h>
#include <stdint.h>

#define KD_SPRITE_W 16
#define KD_SPRITE_H 16
#define KD_SPRITE_BYTES (KD_SPRITE_W * KD_SPRITE_H / 2)
#define KD_SPRITE_HEX (KD_SPRITE_BYTES * 2)

typedef struct {
    uint8_t data[KD_SPRITE_BYTES];
} kd_sprite;

int kd_sprite_get(const kd_sprite *s, int x, int y);      // -1 outside
// Returns true when the pixel changed. Out-of-range input changes nothing.
bool kd_sprite_set(kd_sprite *s, int x, int y, int color);
// Lower-case hex, 256 characters plus NUL.
void kd_sprite_export_hex(const kd_sprite *s, char out[KD_SPRITE_HEX + 1]);
// Accepts exactly 256 hex digits (either case). On error the sprite is
// unchanged and false is returned. changed (optional) receives the number of
// pixels that differ from the previous content.
bool kd_sprite_import_hex(kd_sprite *s, const char *hex, int *changed);

#endif
