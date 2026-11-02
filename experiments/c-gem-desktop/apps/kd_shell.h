// SPDX-License-Identifier: Apache-2.0
// Demonstration shell: menus, desktop icons and the native demo windows
// (About, File Manager mock, KAGURA Studio mock, text viewer placeholder).
// Applications use only kd_app.h; the shell additionally owns the desktop.
// Everything is statically sized: one kd_shell holds all state.
#ifndef KD_SHELL_H
#define KD_SHELL_H

#include "kd_desktop.h"

typedef struct kd_shell kd_shell;

typedef struct {
    kd_shell *shell;
    kd_window *win;
    bool pressed, armed;     // OK button: drawn pressed / pointer went down on it
} kd_about;

#define KD_FM_MAX_ENTRIES 9
typedef struct {
    kd_shell *shell;
    kd_window *win;
    int dir;                 // 0 root, 1 DOCS, 2 SPRITES
    int sel;                 // selected entry or -1
    kd_label info;           // path and selected name
} kd_filemgr;

typedef struct {
    kd_shell *shell;
    kd_window *win;
    char name[16];
} kd_viewer;

typedef struct {
    kd_shell *shell;
    kd_window *win;
    kd_sprite sprite, undo;
    bool has_undo, painting;
    int cx, cy, color;
    kd_label color_label, pos_label;
} kd_studio;

enum { KD_MENU_DESK, KD_MENU_FILE, KD_MENU_OPTIONS };
enum { KD_DESK_ABOUT, KD_DESK_SEP, KD_DESK_FILES, KD_DESK_STUDIO };
enum { KD_FILE_OPEN, KD_FILE_CLOSE, KD_FILE_SEP1, KD_FILE_IMPORT, KD_FILE_EXPORT, KD_FILE_SEP2, KD_FILE_QUIT };
enum { KD_OPT_OUTLINE, KD_OPT_PAINTER, KD_OPT_TILES };
enum { KD_ICON_FILES, KD_ICON_STUDIO, KD_ICON_README, KD_ICON_TRASH, KD_ICON_COUNT };

struct kd_shell {
    kd_desktop desk;
    kd_menu menus[4];
    kd_menu_item desk_items[5], file_items[8], opt_items[4];
    kd_about about;
    kd_filemgr fm;
    kd_studio studio;
    kd_viewer viewers[2];
    int next_viewer, next_sample;
    bool tiles_overlay;      // host draws dirty tiles (Options menu)
    bool quit;
    void (*log)(const char *line);   // optional host console
};

void kd_shell_init(kd_shell *s);
void kd_studio_init(kd_studio *st, kd_shell *shell);
void kd_filemgr_init(kd_filemgr *fm, kd_shell *shell);
kd_window *kd_shell_open_about(kd_shell *s);
kd_window *kd_shell_open_files(kd_shell *s);
kd_window *kd_shell_open_studio(kd_shell *s);
kd_window *kd_shell_open_viewer(kd_shell *s, const char *name);
// The standard scene for tests, screenshots and benchmarks: File Manager and
// Studio overlapping, then rendered.
void kd_shell_demo_scene(kd_shell *s);

// Studio operations (also bound to keys and pointer).
bool kd_studio_put(kd_studio *st, int x, int y, int color);
void kd_studio_set_cursor(kd_studio *st, int x, int y);
void kd_studio_set_color(kd_studio *st, int color);
bool kd_studio_import_hex(kd_studio *st, const char *hex);
void kd_studio_export_hex(const kd_studio *st, char out[KD_SPRITE_HEX + 1]);
void kd_studio_undo(kd_studio *st);
// Studio layout (work-area coordinates), exposed for tests and benchmarks.
#define KD_STUDIO_GX 4
#define KD_STUDIO_GY 4
#define KD_STUDIO_ZOOM 6
#define KD_STUDIO_W 184
#define KD_STUDIO_H 114

#define KD_SAMPLE_SPRITES 2
void kd_sample_sprite(int i, kd_sprite *out);
void kd_sample_sprite_hex(int i, char out[KD_SPRITE_HEX + 1]);

// File Manager layout and entries.
#define KD_FM_W 198
#define KD_FM_H 112
int kd_filemgr_count(const kd_filemgr *fm);
const char *kd_filemgr_name(const kd_filemgr *fm, int i);
kd_rect kd_filemgr_icon_rect(int i);   // work-area icon box
void kd_filemgr_select(kd_filemgr *fm, int i);
void kd_filemgr_open(kd_filemgr *fm, int i);

kd_rect kd_about_ok_rect(void);        // work-area rect of the OK button

#endif
