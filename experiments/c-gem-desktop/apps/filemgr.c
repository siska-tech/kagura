// SPDX-License-Identifier: Apache-2.0
// File Manager mock: a fixed, in-memory directory tree shown as GEM icons.
// No filesystem is accessed. Opening a folder navigates in place, a text
// file opens a placeholder viewer and a sprite file loads into the Studio.
#include <string.h>

#include "kd_shell.h"

enum { FOLDER, UP, TEXT, PRG, SPRITE, DATA };

typedef struct {
    const char *name;
    uint8_t kind;
    int8_t arg;      // folder: directory; sprite: sample index (-1 next)
} entry;

static const entry dir_root[] = {
    {"DOCS", FOLDER, 1}, {"SPRITES", FOLDER, 2}, {"README.TXT", TEXT, 0},
    {"KAGURA.PRG", PRG, 0}, {"STUDIO.PRG", PRG, 1}, {"PALETTE.PAL", DATA, 0},
    {"NOTES.TXT", TEXT, 0}, {"DEMO.SPR", SPRITE, -1}, {NULL, 0, 0},
};
static const entry dir_docs[] = {
    {"..", UP, 0}, {"MANUAL.TXT", TEXT, 0}, {"LICENSE.TXT", TEXT, 0}, {"PLAN.TXT", TEXT, 0},
    {NULL, 0, 0},
};
static const entry dir_sprites[] = {
    {"..", UP, 0}, {"SLIME.SPR", SPRITE, 0}, {"HEART.SPR", SPRITE, 1}, {NULL, 0, 0},
};
static const entry *const dirs[] = {dir_root, dir_docs, dir_sprites};
static const char *const dir_names[] = {"A:\\", "A:\\DOCS\\", "A:\\SPRITES\\"};

static const kd_art *art_for(uint8_t kind) {
    switch (kind) {
    case FOLDER: case UP: return &kd_art_folder;
    case TEXT: return &kd_art_text;
    case PRG: return &kd_art_app;
    case SPRITE: return &kd_art_studio;
    default: return &kd_art_file;
    }
}

int kd_filemgr_count(const kd_filemgr *fm) {
    int n = 0;
    while (dirs[fm->dir][n].name) n++;
    return n;
}

const char *kd_filemgr_name(const kd_filemgr *fm, int i) { return dirs[fm->dir][i].name; }

kd_rect kd_filemgr_icon_rect(int i) {
    return kd_rect_make(2 + (i % 3) * 64, 13 + (i / 3) * 32, 60, 28);
}

static void info_text(const kd_filemgr *fm, char out[KD_LABEL_MAX + 1]) {
    memset(out, 0, KD_LABEL_MAX + 1);
    strncpy(out, dir_names[fm->dir], KD_LABEL_MAX);
    if (fm->sel >= 0) {
        size_t n = strlen(out);
        out[n++] = ' ';
        strncpy(out + n, kd_filemgr_name(fm, fm->sel), KD_LABEL_MAX - n);
    }
}


static void invalidate(kd_filemgr *fm, kd_rect r) {
    if (fm->win) kd_window_invalidate(kd_window_desktop(fm->win), fm->win, r);
}

static void update_info(kd_filemgr *fm) {
    char text[KD_LABEL_MAX + 1];
    info_text(fm, text);
    if (fm->win) kd_label_set(kd_window_desktop(fm->win), fm->win, &fm->info, text);
    else kd_label_init(&fm->info, 2, 1, KD_LABEL_MAX, text);
}

void kd_filemgr_select(kd_filemgr *fm, int i) {
    if (i < -1 || i >= kd_filemgr_count(fm) || i == fm->sel) return;
    if (fm->sel >= 0) invalidate(fm, kd_filemgr_icon_rect(fm->sel));
    if (i >= 0) invalidate(fm, kd_filemgr_icon_rect(i));
    fm->sel = i;
    update_info(fm);
}

static void change_dir(kd_filemgr *fm, int dir) {
    fm->dir = dir;
    fm->sel = -1;
    update_info(fm);
    if (fm->win) {
        kd_window_invalidate_all(kd_window_desktop(fm->win), fm->win);
        kd_window_set_title(kd_window_desktop(fm->win), fm->win, dir_names[dir]);
    }
}

void kd_filemgr_open(kd_filemgr *fm, int i) {
    if (i < 0 || i >= kd_filemgr_count(fm)) return;
    const entry *e = &dirs[fm->dir][i];
    kd_shell *s = fm->shell;
    char hex[KD_SPRITE_HEX + 1];
    switch (e->kind) {
    case FOLDER: change_dir(fm, e->arg); break;
    case UP: change_dir(fm, 0); break;
    case PRG:
        if (e->arg) kd_shell_open_studio(s);
        else kd_shell_open_about(s);
        break;
    case SPRITE:
        kd_sample_sprite_hex(e->arg >= 0 ? e->arg : s->next_sample++ % KD_SAMPLE_SPRITES, hex);
        kd_shell_open_studio(s);
        kd_studio_import_hex(&s->studio, hex);
        break;
    default: kd_shell_open_viewer(s, e->name); break;
    }
}

static void fm_draw(kd_window *w, const kd_draw *d) {
    kd_filemgr *fm = kd_window_user(w);
    kd_draw_fill(d, 0, 0, d->w, 10, KD_C_WHITE);
    kd_draw_label(d, &fm->info, KD_C_BLACK, KD_C_WHITE);
    kd_draw_hline(d, 0, 10, d->w, KD_C_BLACK);
    kd_draw_fill(d, 0, 11, d->w, d->h - 11, KD_C_WHITE);
    for (int i = 0; dirs[fm->dir][i].name; i++) {
        kd_rect c = kd_filemgr_icon_rect(i);
        if (!kd_draw_visible(d, c)) continue;
        const entry *e = &dirs[fm->dir][i];
        kd_draw_icon(d, c.x + 22, c.y + 1, art_for(e->kind), e->name, i == fm->sel);
    }
}

static int hit(const kd_filemgr *fm, int x, int y) {
    for (int i = 0; i < kd_filemgr_count(fm); i++)
        if (kd_rect_has_point(kd_filemgr_icon_rect(i), x, y)) return i;
    return -1;
}

static bool fm_event(kd_window *w, const kd_event *ev) {
    kd_filemgr *fm = kd_window_user(w);
    int n = kd_filemgr_count(fm), sel = fm->sel;
    if (ev->type == KD_EV_POINTER_DOWN) {
        int i = hit(fm, ev->x, ev->y);
        kd_filemgr_select(fm, i);
        if (i >= 0 && ev->clicks == 2) kd_filemgr_open(fm, i);
        return true;
    }
    if (ev->type != KD_EV_KEY) return false;
    switch (ev->key) {
    case KD_KEY_LEFT: kd_filemgr_select(fm, sel <= 0 ? 0 : sel - 1); return true;
    case KD_KEY_RIGHT: kd_filemgr_select(fm, sel + 1 < n ? sel + 1 : n - 1); return true;
    case KD_KEY_UP: kd_filemgr_select(fm, sel >= 3 ? sel - 3 : (sel < 0 ? 0 : sel)); return true;
    case KD_KEY_DOWN: kd_filemgr_select(fm, sel < 0 ? 0 : sel + 3 < n ? sel + 3 : sel); return true;
    case KD_KEY_ENTER: kd_filemgr_open(fm, sel); return true;
    case KD_KEY_BACKSPACE:
        if (fm->dir) change_dir(fm, 0);
        return true;
    default: return false;
    }
}

static void fm_closed(kd_window *w) {
    kd_filemgr *fm = kd_window_user(w);
    fm->win = NULL;
}

static const kd_window_class fm_class = {fm_draw, fm_event, fm_closed};

void kd_filemgr_init(kd_filemgr *fm, kd_shell *shell) {
    memset(fm, 0, sizeof *fm);
    fm->shell = shell;
    fm->sel = -1;
    update_info(fm);
}

kd_window *kd_shell_open_files(kd_shell *s) {
    kd_filemgr *fm = &s->fm;
    if (fm->win) {
        kd_desktop_activate(&s->desk, fm->win);
        return fm->win;
    }
    kd_rect frame = kd_rect_make(40, 22, KD_FM_W + 2, KD_FM_H + KD_TITLE_H + 2);
    fm->win = kd_window_open(&s->desk, &fm_class, fm, dir_names[fm->dir], frame, KD_WF_CLOSE | KD_WF_MOVE);
    return fm->win;
}
