// SPDX-License-Identifier: Apache-2.0
// PC references for the stage 2 HDMI acceptance (pico/hdmi_main.c).
// Runs the same scene script (bench/hdmi_scenes.h) and writes, per scene, the
// 320x240 output as the KAGURA-9 would show it with top placement (desktop
// on lines 0..199, colour 0 below) as an indexed PNG, and prints the CRC32 of
// the desktop framebuffer, which the RP2040 must report identically.
//
//   kd_hdmi_ref DIR
#include <stdio.h>
#include <stdlib.h>

#include "image.h"
#include "hdmi_scenes.h"

static void render_only(void) { kd_desktop_render(&S.desk); }

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s DIR\n", argv[0]);
        return 2;
    }
    static uint8_t idx[320 * 240];
    workloads_init();
    scene_frame = render_only;
    for (unsigned k = 0; k < KD_SCENE_COUNT; k++) {
        kd_scenes[k].apply();
        kd_desktop_render(&S.desk);
        for (int y = 0; y < 240; y++)
            for (int x = 0; x < 320; x++) idx[y * 320 + x] = y < KD_H ? (uint8_t)kd_fb_get(&S.desk.fb, x, y) : 0;
        char path[512];
        snprintf(path, sizeof path, "%s/%s.png", argv[1], kd_scenes[k].name);
        if (!kd_write_png_indexed(path, idx, 320, 240)) {
            fprintf(stderr, "cannot write %s\n", path);
            return 1;
        }
        printf("SCENE %s fb %08x record %d\n", kd_scenes[k].name,
               (unsigned)crc32_update(0, S.desk.fb.px, KD_FB_BYTES), kd_scenes[k].record);
    }
    return 0;
}
