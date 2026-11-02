// SPDX-License-Identifier: Apache-2.0
// Stage 2 HDMI acceptance scenes, shared by the RP2040 program
// (pico/hdmi_main.c, frames go to the KAGURA-9 display) and the PC reference
// renderer (kd_headless --hdmi-scenes). Include after workloads.h and set
// scene_frame to the platform's "render, export, show" function: scenes call
// it wherever an interactive desktop would present a frame.
#ifndef KD_HDMI_SCENES_H
#define KD_HDMI_SCENES_H

#include "workloads.h"

static void (*scene_frame)(void);
static uint32_t scene_ms;   // event clock: 250 ms apart, so clicks are single clicks

static void scene_ev(uint8_t type, int x, int y, uint8_t key, char ch) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.button = KD_BUTTON_LEFT;
    e.key = key;
    e.ch = ch;
    e.x = (int16_t)x;
    e.y = (int16_t)y;
    e.time_ms = scene_ms += 250;
    kd_desktop_event(&S.desk, &e);
}

static void scene_click(int x, int y) {
    scene_ev(KD_EV_POINTER_MOVE, x, y, 0, 0);
    scene_ev(KD_EV_POINTER_DOWN, x, y, 0, 0);
    scene_ev(KD_EV_POINTER_UP, x, y, 0, 0);
}

static void scene_key(uint8_t key, char ch) { scene_ev(KD_EV_KEY, 0, 0, key, ch); }

// Pointer drag in `steps` moves, presenting a frame after each move.
static void scene_drag(int x0, int y0, int dx, int dy, int steps, bool release) {
    scene_ev(KD_EV_POINTER_MOVE, x0, y0, 0, 0);
    scene_ev(KD_EV_POINTER_DOWN, x0, y0, 0, 0);
    for (int i = 1; i <= steps; i++) {
        scene_ev(KD_EV_POINTER_MOVE, x0 + dx * i / steps, y0 + dy * i / steps, 0, 0);
        scene_frame();
    }
    if (release) scene_ev(KD_EV_POINTER_UP, x0 + dx, y0 + dy, 0, 0);
}

static void s_desktop(void) {
    kd_shell_init(&S);
    scene_ms = 0;
    kd_desktop_set_cursor(&S.desk, true);
    scene_ev(KD_EV_POINTER_MOVE, 200, 150, 0, 0);
}

static void s_files_open(void) {   // double-click the FILES drive icon (second press 100 ms later)
    const kd_desk_icon *ic = &S.desk.icons[KD_ICON_FILES];
    scene_click(ic->x + 8, ic->y + 8);
    scene_frame();
    scene_ms -= 150;
    scene_ev(KD_EV_POINTER_DOWN, ic->x + 8, ic->y + 8, 0, 0);
    scene_ev(KD_EV_POINTER_UP, ic->x + 8, ic->y + 8, 0, 0);
}

static void s_files_closed(void) {
    kd_rect c = kd_frame_close(S.fm.win->frame);
    scene_click(c.x + 4, c.y + 4);
}

static void s_overlap(void) {
    kd_shell_open_files(&S);
    scene_frame();
    kd_shell_open_studio(&S);
}

static void s_activate(void) {   // click the visible part of the File Manager title
    kd_rect t = kd_frame_title(S.fm.win->frame);
    scene_click(t.x + 20, t.y + 4);
}

static void s_menu(void) {
    kd_desktop *d = &S.desk;
    scene_click(kd_menu_title_x(d->menus, KD_MENU_DESK) + 4, 4);
    scene_frame();
    kd_rect r = kd_menu_dropdown_rect(d->menus, KD_MENU_DESK);
    scene_ev(KD_EV_POINTER_MOVE, r.x + 40, r.y + 1 + KD_DESK_STUDIO * KD_MENU_ITEM_H + 4, 0, 0);
}

static void s_menu_closed(void) { scene_key(KD_KEY_ESCAPE, 0); }

static void s_about(void) {   // F10 opens Desk with About highlighted, Enter chooses it
    scene_key(KD_KEY_F10, 0);
    scene_frame();
    scene_key(KD_KEY_ENTER, 0);
}

static void s_about_closed(void) {
    kd_rect ok = kd_about_ok_rect(), w = kd_window_work(S.about.win);
    scene_click(w.x + ok.x + 10, w.y + ok.y + 6);
}

// The Studio title's right end is outside the File Manager (x >= 240).
static void s_move_live(void) {   // first press raises the Studio and starts the drag
    kd_rect t = kd_frame_title(S.studio.win->frame);
    scene_drag(t.x + t.w - 30, t.y + 4, -40, 32, 4, true);
}

static void s_outline_drag(void) {   // the Studio is on top now
    S.desk.outline_drag = true;
    kd_rect t = kd_frame_title(S.studio.win->frame);
    scene_drag(t.x + 60, t.y + 4, 64, -40, 3, false);   // still dragging: outline visible
}

static void s_outline_drop(void) {
    scene_ev(KD_EV_POINTER_UP, S.desk.px, S.desk.py, 0, 0);
    S.desk.outline_drag = false;
}

static void s_sprite_draw(void) {
    kd_studio_import_hex(&S.studio, sample_hex[1]);   // heart
    scene_frame();
    scene_key(KD_KEY_CHAR, 'e');    // orange
    for (int i = 0; i < 5; i++) {
        scene_key(KD_KEY_RIGHT, 0);
        scene_key(KD_KEY_DOWN, 0);
        scene_key(KD_KEY_CHAR, ' ');
        scene_frame();
    }
    scene_key(KD_KEY_CHAR, '5');    // blue stroke with the mouse
    kd_rect w = kd_window_work(S.studio.win);
    int gx = w.x + KD_STUDIO_GX + 2, gy = w.y + KD_STUDIO_GY + 12 * KD_STUDIO_ZOOM + 2;
    scene_drag(gx, gy, 15 * KD_STUDIO_ZOOM, 0, 8, true);
}

typedef struct {
    const char *name;
    void (*apply)(void);
    bool record;   // the host records video during this scene (intermediate frames)
} kd_scene;

static const kd_scene kd_scenes[] = {
    {"01-desktop", s_desktop, false},
    {"02-files-open", s_files_open, false},
    {"03-files-closed", s_files_closed, false},
    {"04-overlap", s_overlap, false},
    {"05-activate", s_activate, true},
    {"06-menu", s_menu, false},
    {"07-menu-closed", s_menu_closed, true},
    {"08-about", s_about, false},
    {"09-about-closed", s_about_closed, false},
    {"10-move-live", s_move_live, false},
    {"11-outline-drag", s_outline_drag, false},
    {"12-outline-drop", s_outline_drop, true},
    {"13-sprite-draw", s_sprite_draw, false},
};
#define KD_SCENE_COUNT (sizeof kd_scenes / sizeof kd_scenes[0])

#endif
