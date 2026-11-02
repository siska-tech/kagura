// SPDX-License-Identifier: Apache-2.0
// Shell: menus, desktop icons, About dialog and the placeholder text viewer.
#include <string.h>

#include "kd_shell.h"

// ---- About dialog ----

kd_rect kd_about_ok_rect(void) { return kd_rect_make(69, 54, 48, 16); }

static void about_draw(kd_window *w, const kd_draw *d) {
    kd_about *a = kd_window_user(w);
    kd_draw_fill(d, 0, 0, d->w, d->h, KD_C_WHITE);
    kd_draw_art(d, 8, 6, &kd_art_studio, KD_C_BLACK, KD_C_WHITE);
    kd_draw_text(d, &kd_font_system, 32, 8, "KAGURA Desktop", KD_C_BLACK, KD_NO_KEY);
    kd_draw_text(d, &kd_font_small, 32, 20, "EXPERIMENTAL C GEM-STYLE SHELL", KD_C_DGREY, KD_NO_KEY);
    kd_draw_text(d, &kd_font_small, 32, 30, "320X200 4BPP, KAGURA TILE4 EXPORT", KD_C_DGREY, KD_NO_KEY);
    kd_draw_text(d, &kd_font_small, 32, 40, "NO GEM CODE, NO EMULATION", KD_C_DGREY, KD_NO_KEY);
    kd_draw_button(d, kd_about_ok_rect(), "OK", KD_BTN_DEFAULT | (a->pressed ? KD_BTN_PRESSED : 0));
}

static void about_press(kd_about *a, bool pressed) {
    if (pressed == a->pressed) return;
    a->pressed = pressed;
    kd_window_invalidate(kd_window_desktop(a->win), a->win, kd_about_ok_rect());
}

static bool about_event(kd_window *w, const kd_event *ev) {
    kd_about *a = kd_window_user(w);
    bool inside = kd_rect_has_point(kd_about_ok_rect(), ev->x, ev->y);
    switch (ev->type) {
    case KD_EV_POINTER_DOWN:
        a->armed = inside;
        about_press(a, inside);
        return true;
    case KD_EV_POINTER_MOVE:
        if (a->armed) about_press(a, inside);
        return true;
    case KD_EV_POINTER_UP:
        if (a->armed && inside) {
            kd_window_close(kd_window_desktop(w), w);
            return true;
        }
        a->armed = false;
        about_press(a, false);
        return true;
    case KD_EV_KEY:
        if (ev->key == KD_KEY_ENTER || ev->key == KD_KEY_ESCAPE || (ev->key == KD_KEY_CHAR && ev->ch == ' ')) {
            kd_window_close(kd_window_desktop(w), w);
            return true;
        }
        return false;
    default: return false;
    }
}

static void about_closed(kd_window *w) {
    kd_about *a = kd_window_user(w);
    a->win = NULL;
    a->pressed = a->armed = false;
}

static const kd_window_class about_class = {about_draw, about_event, about_closed};

kd_window *kd_shell_open_about(kd_shell *s) {
    if (s->about.win) {
        kd_desktop_activate(&s->desk, s->about.win);
        return s->about.win;
    }
    s->about.shell = s;
    s->about.win = kd_window_open(&s->desk, &about_class, &s->about, "About",
                                  kd_rect_make(66, 52, 188, 90), KD_WF_CLOSE | KD_WF_MOVE);
    return s->about.win;
}

// ---- placeholder viewer ----

static void viewer_draw(kd_window *w, const kd_draw *d) {
    kd_viewer *v = kd_window_user(w);
    kd_draw_fill(d, 0, 0, d->w, d->h, KD_C_WHITE);
    kd_draw_text(d, &kd_font_system, 4, 4, v->name, KD_C_BLACK, KD_NO_KEY);
    kd_draw_hline(d, 4, 14, d->w - 8, KD_C_DGREY);
    static const char *const lines[] = {
        "PLACEHOLDER VIEWER.",
        "THE FILE MANAGER IS A MOCK AND",
        "DOES NOT READ ANY FILESYSTEM.",
        "CTRL+W OR THE CLOSE BOX CLOSES IT.",
    };
    for (int i = 0; i < 4; i++)
        kd_draw_text(d, &kd_font_small, 4, 20 + i * 10, lines[i], KD_C_BLACK, KD_NO_KEY);
}

static bool viewer_event(kd_window *w, const kd_event *ev) {
    if (ev->type == KD_EV_KEY && ev->key == KD_KEY_ESCAPE) {
        kd_window_close(kd_window_desktop(w), w);
        return true;
    }
    return false;
}

static void viewer_closed(kd_window *w) {
    kd_viewer *v = kd_window_user(w);
    v->win = NULL;
}

static const kd_window_class viewer_class = {viewer_draw, viewer_event, viewer_closed};

kd_window *kd_shell_open_viewer(kd_shell *s, const char *name) {
    for (int i = 0; i < 2; i++)
        if (s->viewers[i].win && strcmp(s->viewers[i].name, name) == 0) {
            kd_desktop_activate(&s->desk, s->viewers[i].win);
            return s->viewers[i].win;
        }
    kd_viewer *v = &s->viewers[s->next_viewer];
    s->next_viewer = (s->next_viewer + 1) % 2;
    if (v->win) kd_window_close(&s->desk, v->win);
    v->shell = s;
    memset(v->name, 0, sizeof v->name);
    strncpy(v->name, name, sizeof v->name - 1);
    int off = s->next_viewer * 12;
    v->win = kd_window_open(&s->desk, &viewer_class, v, name, kd_rect_make(150 - off, 30 + off, 164, 76),
                            KD_WF_CLOSE | KD_WF_MOVE);
    return v->win;
}

// ---- menus and desktop ----

static void log_line(kd_shell *s, const char *line) {
    if (s->log) s->log(line);
}

static void menu_hook(kd_desktop *d, int menu, int item, void *ctx) {
    kd_shell *s = ctx;
    kd_window *top = kd_desktop_top(d);
    char hex[KD_SPRITE_HEX + 1];
    if (menu == KD_MENU_DESK) {
        if (item == KD_DESK_ABOUT) kd_shell_open_about(s);
        else if (item == KD_DESK_FILES) kd_shell_open_files(s);
        else if (item == KD_DESK_STUDIO) kd_shell_open_studio(s);
    } else if (menu == KD_MENU_FILE) {
        switch (item) {
        case KD_FILE_OPEN:
            if (top && top == s->fm.win) kd_filemgr_open(&s->fm, s->fm.sel);
            else if (!top && d->icon_sel >= 0 && d->hooks.icon_open) d->hooks.icon_open(d, d->icon_sel, s);
            break;
        case KD_FILE_CLOSE:
            if (top && (top->flags & KD_WF_CLOSE)) kd_window_close(d, top);
            break;
        case KD_FILE_IMPORT:
            kd_sample_sprite_hex(s->next_sample++ % KD_SAMPLE_SPRITES, hex);
            kd_shell_open_studio(s);
            kd_studio_import_hex(&s->studio, hex);
            break;
        case KD_FILE_EXPORT:
            kd_studio_export_hex(&s->studio, hex);
            log_line(s, hex);
            break;
        case KD_FILE_QUIT: s->quit = true; break;
        default: break;
        }
    } else if (menu == KD_MENU_OPTIONS) {
        if (item == KD_OPT_OUTLINE) d->outline_drag = s->opt_items[item].checked = !d->outline_drag;
        else if (item == KD_OPT_PAINTER) d->painter = s->opt_items[item].checked = !d->painter;
        else if (item == KD_OPT_TILES) s->tiles_overlay = s->opt_items[item].checked = !s->tiles_overlay;
    }
}

static void icon_hook(kd_desktop *d, int icon, void *ctx) {
    kd_shell *s = ctx;
    (void)d;
    if (icon == KD_ICON_FILES) kd_shell_open_files(s);
    else if (icon == KD_ICON_STUDIO) kd_shell_open_studio(s);
    else if (icon == KD_ICON_README) kd_shell_open_viewer(s, "README.TXT");
    else if (icon == KD_ICON_TRASH) kd_shell_open_viewer(s, "TRASH");
}

void kd_shell_init(kd_shell *s) {
    memset(s, 0, sizeof *s);
    static const kd_menu_item desk[] = {
        {"About KAGURA Desktop", false, false}, {"-", false, false},
        {"File Manager", false, false}, {"Sprite Studio", false, false}, {NULL, false, false},
    };
    static const kd_menu_item file[] = {
        {"Open", false, false}, {"Close window", false, false}, {"-", false, false},
        {"Import sample", false, false}, {"Export hex", false, false}, {"-", false, false},
        {"Quit", false, false}, {NULL, false, false},
    };
    static const kd_menu_item opt[] = {
        {"Outline drag", false, false}, {"Painter compose", false, false},
        {"Show dirty tiles", false, false}, {NULL, false, false},
    };
    memcpy(s->desk_items, desk, sizeof desk);
    memcpy(s->file_items, file, sizeof file);
    memcpy(s->opt_items, opt, sizeof opt);
    s->menus[0] = (kd_menu){"Desk", s->desk_items};
    s->menus[1] = (kd_menu){"File", s->file_items};
    s->menus[2] = (kd_menu){"Options", s->opt_items};
    s->menus[3] = (kd_menu){NULL, NULL};
    const kd_desk_icon icons[KD_ICON_COUNT] = {
        {8, 18, &kd_art_drive, "FILES"},
        {8, 50, &kd_art_studio, "STUDIO"},
        {8, 82, &kd_art_text, "README"},
        {8, 166, &kd_art_trash, "TRASH"},
    };
    kd_shell_hooks hooks = {menu_hook, icon_hook, s};
    kd_desktop_init(&s->desk, s->menus, icons, KD_ICON_COUNT, hooks);
    kd_studio_init(&s->studio, s);
    kd_filemgr_init(&s->fm, s);
}

void kd_shell_demo_scene(kd_shell *s) {
    kd_shell_init(s);
    kd_shell_open_files(s);
    kd_shell_open_studio(s);
    kd_desktop_render(&s->desk);
}
