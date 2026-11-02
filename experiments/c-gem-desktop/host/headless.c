// SPDX-License-Identifier: Apache-2.0
// Headless host: scripted scenario with screenshots and framebuffer dumps.
//
//   kd_headless --scenario DIR [--scale N]   PNG per step, TILE4 + linear dumps
//   kd_headless --png FILE [--scale N]       the standard scene only
//   kd_headless --tile4 FILE                 TILE4 patterns 0..999 (32,000 B)
//
// Each scenario step prints the CRC32 of the framebuffer and the number of
// tiles that changed, so runs are comparable across machines and builds.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "image.h"
#include "kd_shell.h"
#include "kd_tile4.h"

static kd_shell S;
static int scale = 3;
static const char *outdir;
static int failures;

static void send(kd_event e) { kd_desktop_event(&S.desk, &e); }

static void ptr(uint8_t type, int x, int y, uint32_t t) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.button = KD_BUTTON_LEFT;
    e.x = (int16_t)x;
    e.y = (int16_t)y;
    e.time_ms = t;
    send(e);
}

static void key(uint8_t k, char ch) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = KD_EV_KEY;
    e.key = k;
    e.ch = ch;
    send(e);
}

static bool write_file(const char *path, const void *data, size_t n) {
    FILE *f = fopen(path, "wb");
    bool ok = f && fwrite(data, 1, n, f) == n;
    if (f) ok = fclose(f) == 0 && ok;
    return ok;
}

static void step(const char *name) {
    kd_desktop_render(&S.desk);
    unsigned tiles = kd_fb_dirty_count(&S.desk.fb);
    kd_fb_clear_dirty(&S.desk.fb);
    printf("%-22s crc32 %08x  changed tiles %4u\n", name, kd_crc32(S.desk.fb.px, KD_FB_BYTES), tiles);
    if (!outdir) return;
    char path[512];
    snprintf(path, sizeof path, "%s/%s.png", outdir, name);
    if (!kd_write_fb_png(path, &S.desk.fb, scale, false)) {
        fprintf(stderr, "cannot write %s\n", path);
        failures++;
    }
}

static void check_full_redraw(const char *where) {
    static uint8_t copy[KD_FB_BYTES];
    kd_desktop_render(&S.desk);   // pending damage first: the incremental frame
    memcpy(copy, S.desk.fb.px, sizeof copy);
    kd_desktop_invalidate(&S.desk, kd_rect_make(0, 0, KD_W, KD_H));
    kd_desktop_render(&S.desk);
    if (memcmp(copy, S.desk.fb.px, sizeof copy) != 0) {
        fprintf(stderr, "%s: incremental frame differs from full redraw\n", where);
        failures++;
    }
}

static void scenario(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    kd_desktop_set_cursor(d, true);
    ptr(KD_EV_POINTER_MOVE, 200, 150, 0);
    step("01-desktop");

    int desk_x = kd_menu_title_x(d->menus, KD_MENU_DESK);
    ptr(KD_EV_POINTER_MOVE, desk_x + 4, 4, 100);
    ptr(KD_EV_POINTER_DOWN, desk_x + 4, 4, 100);
    ptr(KD_EV_POINTER_UP, desk_x + 4, 4, 110);
    kd_rect dd = kd_menu_dropdown_rect(d->menus, KD_MENU_DESK);
    ptr(KD_EV_POINTER_MOVE, dd.x + 30, dd.y + 1 + KD_DESK_STUDIO * KD_MENU_ITEM_H + 4, 150);
    step("02-desk-menu");
    key(KD_KEY_ESCAPE, 0);

    kd_shell_open_about(&S);
    kd_rect ok = kd_about_ok_rect(), work = kd_window_work(S.about.win);
    ptr(KD_EV_POINTER_MOVE, work.x + ok.x + 10, work.y + ok.y + 6, 200);
    ptr(KD_EV_POINTER_DOWN, work.x + ok.x + 10, work.y + ok.y + 6, 200);
    step("03-about-pressed");
    ptr(KD_EV_POINTER_UP, work.x + ok.x + 10, work.y + ok.y + 6, 210);
    check_full_redraw("about closed");

    d->outline_drag = true;
    kd_rect f = S.studio.win->frame;
    ptr(KD_EV_POINTER_MOVE, f.x + 70, f.y + 5, 300);
    ptr(KD_EV_POINTER_DOWN, f.x + 70, f.y + 5, 300);
    ptr(KD_EV_POINTER_MOVE, f.x + 30, f.y - 25, 320);
    step("04-outline-drag");
    ptr(KD_EV_POINTER_UP, f.x + 30, f.y - 25, 330);
    d->outline_drag = false;
    step("05-dropped");
    check_full_redraw("dropped");

    char hex[KD_SPRITE_HEX + 1];
    kd_sample_sprite_hex(1, hex);
    kd_studio_import_hex(&S.studio, hex);
    step("06-studio-import");
    key(KD_KEY_CHAR, 'e');
    for (int i = 0; i < 4; i++) {
        key(KD_KEY_RIGHT, 0);
        key(KD_KEY_DOWN, 0);
        key(KD_KEY_CHAR, ' ');
    }
    key(KD_KEY_CHAR, '9');
    step("07-studio-edit");
    check_full_redraw("studio edit");

    kd_desktop_activate(d, S.fm.win);
    kd_filemgr_open(&S.fm, 1);
    kd_filemgr_select(&S.fm, 2);
    step("08-filemgr-sprites");
    kd_filemgr_open(&S.fm, 0);
    kd_filemgr_open(&S.fm, 2);
    step("09-viewer");
    check_full_redraw("end");

    if (outdir) {
        static uint8_t tiles[KD_TILE4_TOTAL];
        char path[512];
        kd_tile4_pack_all(&d->fb, tiles);
        snprintf(path, sizeof path, "%s/desktop.tile4", outdir);
        if (!write_file(path, tiles, sizeof tiles)) failures++;
        snprintf(path, sizeof path, "%s/desktop.linear4", outdir);
        if (!write_file(path, d->fb.px, KD_FB_BYTES)) failures++;
        snprintf(path, sizeof path, "%s/10-kagura-320x240.png", outdir);
        if (!kd_write_fb_png(path, &d->fb, 2, true)) failures++;
        snprintf(path, sizeof path, "%s/desktop-1x.png", outdir);
        if (!kd_write_fb_png(path, &d->fb, 1, false)) failures++;
    }
}

int main(int argc, char **argv) {
    const char *png = NULL, *tile4 = NULL;
    bool run_scenario = false;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--scenario") == 0 && i + 1 < argc) {
            run_scenario = true;
            outdir = argv[++i];
        } else if (strcmp(argv[i], "--png") == 0 && i + 1 < argc) {
            png = argv[++i];
        } else if (strcmp(argv[i], "--tile4") == 0 && i + 1 < argc) {
            tile4 = argv[++i];
        } else if (strcmp(argv[i], "--scale") == 0 && i + 1 < argc) {
            scale = atoi(argv[++i]);
            if (scale < 1 || scale > 8) scale = 3;
        } else if (strcmp(argv[i], "--sprite") == 0 && i + 1 < argc) {
            // Sample sprite as hex plus the pixels kd_sprite_get reads back.
            int n = atoi(argv[++i]);
            kd_sprite sp;
            char hex[KD_SPRITE_HEX + 1];
            kd_sample_sprite(n < 0 || n >= KD_SAMPLE_SPRITES ? 0 : n, &sp);
            kd_sprite_export_hex(&sp, hex);
            printf("hex %s\n", hex);
            for (int y = 0; y < KD_SPRITE_H; y++) {
                for (int x = 0; x < KD_SPRITE_W; x++) printf("%x", kd_sprite_get(&sp, x, y));
                printf("\n");
            }
            return 0;
        } else {
            fprintf(stderr, "usage: %s [--scenario DIR] [--png FILE] [--tile4 FILE] [--scale N] [--sprite N]\n",
                    argv[0]);
            return 2;
        }
    }
    if (run_scenario) {
        if (outdir) {
            char probe[512];
            snprintf(probe, sizeof probe, "%s/.probe", outdir);
            FILE *f = fopen(probe, "wb");
            if (!f) {
                fprintf(stderr, "output directory %s is not writable (create it first)\n", outdir);
                return 1;
            }
            fclose(f);
            remove(probe);
        }
        scenario();
    } else {
        kd_shell_demo_scene(&S);
    }
    if (png && !kd_write_fb_png(png, &S.desk.fb, scale, false)) failures++;
    if (tile4) {
        static uint8_t tiles[KD_TILE4_TOTAL];
        kd_tile4_pack_all(&S.desk.fb, tiles);
        if (!write_file(tile4, tiles, sizeof tiles)) failures++;
    }
    if (failures) fprintf(stderr, "%d failure(s)\n", failures);
    return failures ? 1 : 0;
}
