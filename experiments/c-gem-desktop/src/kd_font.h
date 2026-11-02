// SPDX-License-Identifier: Apache-2.0
// Monospaced printable-ASCII bitmap fonts (0x20..0x7E, others draw '?').
// Rows are 8 bytes per glyph, MSB is the left pixel.
#ifndef KD_FONT_H
#define KD_FONT_H

#include "kd_fb.h"

typedef struct {
    uint8_t width, height;
    const uint8_t *rows;
} kd_font;

extern const kd_font kd_font_system;   // 8x8, Misaki full-width forms
extern const kd_font kd_font_small;    // 4x8, Misaki half-width forms

// Draws text starting at (x,y); bg KD_NO_KEY leaves background pixels alone.
// Returns the x after the last glyph. Newlines are not interpreted.
int kd_text(kd_fb *fb, const kd_font *f, int x, int y, const char *s, uint8_t fg, int bg);
int kd_text_n(kd_fb *fb, const kd_font *f, int x, int y, const char *s, int n,
              uint8_t fg, int bg);
int kd_text_width(const kd_font *f, const char *s);

#endif
