// SPDX-License-Identifier: Apache-2.0
// PC harness for img_quant.c and img_scene.c. Writes to stdout: the scene as
// RGB888 (320*240*3), then the quantizer output: 256 RGB444 palette words
// (little endian), 1200 cell palettes and 38400 tile-native pixel bytes.
// Argument: rounds (default 2).
#include <stdio.h>
#include <stdlib.h>

#include "../img_quant.h"
#include "../img_scene.h"

static iq_image image;
static uint8_t pixels[38400];

int main(int argc, char **argv) {
    unsigned rounds = argc > 1 ? (unsigned)atoi(argv[1]) : 2;
    scene_init();
    for (unsigned y = 0; y < 240; y++)
        for (unsigned x = 0; x < 320; x++) {
            uint8_t rgb[3];
            scene_rgb(NULL, x, y, rgb);
            fwrite(rgb, 1, 3, stdout);
        }
    if (iq_quantize(scene_rgb, NULL, rounds, &image, pixels, NULL)) return 1;
    for (unsigned i = 0; i < 256; i++) {
        uint8_t w[2] = {(uint8_t)image.palette[i], (uint8_t)(image.palette[i] >> 8)};
        fwrite(w, 1, 2, stdout);
    }
    fwrite(image.cell, 1, sizeof image.cell, stdout);
    fwrite(pixels, 1, sizeof pixels, stdout);
    return 0;
}
