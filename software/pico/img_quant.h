// SPDX-License-Identifier: Apache-2.0
// Pseudo-256-colour quantizer for the 320x240 TileFramebuffer: 16 palettes
// of 16 RGB444 colours, one palette per 8x8 cell (the map's palette field).
// Pure computation, no device I/O, so the PC test can run it.
#ifndef IMG_QUANT_H
#define IMG_QUANT_H

#include <stdint.h>

#define IQ_PALETTES 16
#define IQ_COLOURS 16

// RGB888 of pixel (x, y); called many times per pixel, so it must be pure.
typedef void (*iq_source)(void *ctx, unsigned x, unsigned y, uint8_t rgb[3]);

typedef struct {
    uint16_t palette[IQ_PALETTES * IQ_COLOURS];   // RGB444, palette p colour i at p*16+i
    uint8_t cell[1200];                            // palette of each cell, row-major 40x30
} iq_image;

// Clusters the cells by mean colour into 16 palettes, fits colours 1..15 of
// each palette by k-means (colour 0 is shared by all palettes, since pixel
// value 0 is transparent and shows BACKDROP = palette 0 colour 0), reassigns
// every cell to the palette that reproduces it best (`rounds` times) and
// writes 4x4 ordered-dithered indices into pixels
// (38400 bytes, tile-native 4bpp as tile_fb.h), whose first 3600 bytes also
// serve as work area before that. Returns 0. progress, if not NULL, gets a
// stage name.
int iq_quantize(iq_source source, void *ctx, unsigned rounds, iq_image *out, uint8_t *pixels,
                void (*progress)(const char *stage));

#endif
