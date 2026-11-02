// SPDX-License-Identifier: Apache-2.0
// Layers C/D tests: z-order, exposure, movement, closure, focus/dispatch,
// menus, targeted invalidation, Studio/File Manager behaviour, and the
// central invariant: after any sequence of operations the incrementally
// recomposed frame equals both a full region-composed redraw and a full
// painter's-algorithm redraw of the same state.
#include <string.h>

#include "kd_desktop.h"
#include "kd_shell.h"
#include "kd_test.h"

static kd_shell S;
static uint8_t snapshot[KD_FB_BYTES];

static bool same_as_snapshot(kd_desktop *d, const char *what) {
    bool ok = memcmp(snapshot, d->fb.px, sizeof snapshot) == 0;
    if (!ok && !kd_test_quiet) {
        fprintf(stderr, "  %s redraw differs:", what);
        int x0 = KD_W, y0 = KD_H, x1 = -1, y1 = -1;
        for (int i = 0; i < KD_FB_BYTES; i++)
            if (snapshot[i] != d->fb.px[i]) {
                int x = (i % KD_STRIDE) * 2, y = i / KD_STRIDE;
                if (x < x0) x0 = x;
                if (x > x1) x1 = x + 1;
                if (y < y0) y0 = y;
                if (y > y1) y1 = y;
            }
        fprintf(stderr, "  diff box x %d..%d y %d..%d; menu %d drag %d; z:", x0, x1, y0, y1, d->menu_open, d->drag);
        for (int i = 0; i < d->zn; i++) {
            kd_rect f = d->win[d->z[i]].frame;
            fprintf(stderr, " [%s %d,%d %dx%d]", d->win[d->z[i]].title, f.x, f.y, f.w, f.h);
        }
        fprintf(stderr, "\n");
    }
    return ok;
}

// Renders pending damage, then checks full redraws (region and painter).
static bool frame_consistent(kd_shell *s) {
    kd_desktop *d = &s->desk;
    kd_desktop_render(d);
    memcpy(snapshot, d->fb.px, sizeof snapshot);
    bool painter = d->painter;
    d->painter = false;
    kd_desktop_invalidate(d, kd_rect_make(0, 0, KD_W, KD_H));
    kd_desktop_render(d);
    bool ok = same_as_snapshot(d, "region");
    d->painter = true;
    kd_desktop_invalidate(d, kd_rect_make(0, 0, KD_W, KD_H));
    kd_desktop_render(d);
    ok = same_as_snapshot(d, "painter") && ok;
    d->painter = painter;
    return ok;
}

static kd_event ev_key(uint8_t key, char ch, uint8_t mods) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = KD_EV_KEY;
    e.key = key;
    e.ch = ch;
    e.mods = mods;
    return e;
}

static kd_event ev_ptr(uint8_t type, int x, int y, uint32_t t) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.button = KD_BUTTON_LEFT;
    e.x = (int16_t)x;
    e.y = (int16_t)y;
    e.time_ms = t;
    return e;
}

static void send_ev(kd_shell *s, kd_event e) { kd_desktop_event(&s->desk, &e); }

static void click(kd_shell *s, int x, int y, uint32_t t) {
    send_ev(s, ev_ptr(KD_EV_POINTER_MOVE, x, y, t));
    send_ev(s, ev_ptr(KD_EV_POINTER_DOWN, x, y, t));
    send_ev(s, ev_ptr(KD_EV_POINTER_UP, x, y, t));
}

// ---- recording window class for dispatch tests ----

typedef struct {
    int count, last_type, last_key, last_x, last_y, last_clicks;
    uint8_t color;
} recorder;

static void rec_draw(kd_window *w, const kd_draw *d) {
    recorder *r = kd_window_user(w);
    kd_draw_fill(d, 0, 0, d->w, d->h, r->color);
}

static bool rec_event(kd_window *w, const kd_event *ev) {
    recorder *r = kd_window_user(w);
    r->count++;
    r->last_type = ev->type;
    r->last_key = ev->key;
    r->last_x = ev->x;
    r->last_y = ev->y;
    r->last_clicks = ev->clicks;
    return true;
}

static const kd_window_class rec_class = {rec_draw, rec_event, NULL};

// ---- tests ----

static void test_scene_renders(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    CHECK_EQ(d->zn, 2);
    CHECK(kd_desktop_top(d) == S.studio.win);
    CHECK(frame_consistent(&S));
    // Menu bar is white, desktop colour 0 visible, top window title striped.
    CHECK_EQ(kd_fb_get(&d->fb, 300, 2), KD_C_WHITE);
    CHECK_EQ(kd_fb_get(&d->fb, 2, 120), KD_C_DESK);
    kd_rect t = kd_frame_title(S.studio.win->frame);
    CHECK_EQ(kd_fb_get(&d->fb, t.x + 14, t.y + 1), KD_C_BLACK);
    CHECK_EQ(kd_fb_get(&d->fb, t.x + 14, t.y + 2), KD_C_WHITE);
    // The inactive File Manager title has no stripes.
    kd_rect ft = kd_frame_title(S.fm.win->frame);
    CHECK_EQ(kd_fb_get(&d->fb, ft.x + 14, ft.y + 1), KD_C_WHITE);
    CHECK(!kd_desktop_render(d));   // nothing pending
    // Redrawing an unchanged screen leaves no dirty tiles despite overdraw.
    kd_fb_clear_dirty(&d->fb);
    kd_desktop_invalidate(d, kd_rect_make(0, 0, KD_W, KD_H));
    kd_desktop_render(d);
    CHECK_EQ(kd_fb_dirty_count(&d->fb), 0);
    CHECK(d->stats.suppressed > 0);
    // A one-pixel sprite edit dirties exactly the tiles whose bytes change.
    static uint8_t before[KD_FB_BYTES];
    memcpy(before, d->fb.px, sizeof before);
    kd_studio_put(&S.studio, 9, 9, 2);
    kd_desktop_render(d);
    for (unsigned tile = 0; tile < KD_TILES; tile++) {
        unsigned base = (tile / KD_TILE_COLS) * 8 * KD_STRIDE + (tile % KD_TILE_COLS) * 4;
        bool changed = false;
        for (int r = 0; r < 8; r++) changed |= memcmp(before + base + r * KD_STRIDE, d->fb.px + base + r * KD_STRIDE, 4) != 0;
        CHECK_EQ(kd_fb_tile_dirty(&d->fb, tile), changed);
    }
}

static void test_z_order_and_hit(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    kd_window *fm = S.fm.win, *st = S.studio.win, *ab = kd_shell_open_about(&S);
    CHECK_EQ(kd_desktop_z_index(d, fm), 0);
    CHECK_EQ(kd_desktop_z_index(d, st), 1);
    CHECK_EQ(kd_desktop_z_index(d, ab), 2);
    kd_desktop_activate(d, fm);
    CHECK_EQ(kd_desktop_z_index(d, st), 0);
    CHECK_EQ(kd_desktop_z_index(d, ab), 1);
    CHECK(kd_desktop_top(d) == fm);
    // A point inside all three resolves to the top one.
    kd_rect o = kd_rect_intersect(kd_rect_intersect(fm->frame, st->frame), ab->frame);
    CHECK(!kd_rect_empty(o));
    CHECK(kd_desktop_window_at(d, o.x, o.y) == fm);
    kd_desktop_activate(d, st);
    CHECK(kd_desktop_window_at(d, o.x, o.y) == st);
    CHECK(kd_desktop_window_at(d, 2, 150) == NULL);
    CHECK(frame_consistent(&S));
}

static void test_exposure_on_raise_move_close(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    kd_desktop_activate(d, S.fm.win);
    CHECK(frame_consistent(&S));
    kd_desktop_move(d, S.fm.win, 130, 70);
    CHECK(frame_consistent(&S));
    kd_desktop_move(d, S.fm.win, -150, 15);
    CHECK_EQ(S.fm.win->frame.x, -150);
    CHECK(frame_consistent(&S));
    kd_desktop_move(d, S.fm.win, 0, 0);            // clamped below the menu bar
    CHECK_EQ(S.fm.win->frame.y, KD_MENU_H);
    CHECK(frame_consistent(&S));
    kd_rect old = S.studio.win->frame;
    kd_window_close(d, S.studio.win);
    CHECK(S.studio.win == NULL);
    CHECK_EQ(d->zn, 1);
    CHECK(frame_consistent(&S));
    // Pixels of the closed frame that no window covers are desktop again.
    int desk = 0;
    for (int y = old.y; y < old.y + old.h; y++)
        for (int x = old.x; x < old.x + old.w; x++)
            if (!kd_desktop_window_at(d, x, y) && kd_fb_get(&d->fb, x, y) == KD_C_DESK) desk++;
    CHECK(desk > 1000);
}

static void test_targeted_invalidation(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    kd_window *fm = S.fm.win, *st = S.studio.win;
    // A File Manager rect entirely under the Studio produces no damage.
    kd_rect o = kd_rect_intersect(kd_frame_work(fm->frame), st->frame);
    kd_rect hidden = kd_rect_make(o.x + 2, o.y + 2, 10, 10);
    CHECK(kd_rect_contains(st->frame, hidden));
    kd_window_invalidate(d, fm, kd_rect_make(hidden.x - kd_frame_work(fm->frame).x,
                                             hidden.y - kd_frame_work(fm->frame).y, 10, 10));
    CHECK_EQ(d->damage.n, 0);
    // A rect straddling the Studio edge damages only its visible part.
    kd_rect work = kd_frame_work(fm->frame);
    kd_window_invalidate(d, fm, kd_rect_make(st->frame.x - work.x - 5, 40, 10, 4));
    CHECK_EQ(kd_damage_area(&d->damage), 5 * 4);
    CHECK(frame_consistent(&S));
}

static void test_focus_and_dispatch(void) {
    static recorder ra, rb;
    kd_shell_init(&S);
    kd_desktop *d = &S.desk;
    memset(&ra, 0, sizeof ra);
    memset(&rb, 0, sizeof rb);
    ra.color = KD_C_CYAN;
    rb.color = KD_C_YELLOW;
    kd_window *a = kd_window_open(d, &rec_class, &ra, "A", kd_rect_make(20, 20, 120, 80), KD_WF_CLOSE | KD_WF_MOVE);
    kd_window *b = kd_window_open(d, &rec_class, &rb, "B", kd_rect_make(80, 50, 120, 80), KD_WF_CLOSE | KD_WF_MOVE);
    CHECK_EQ(ra.last_type, KD_EV_BLUR);
    CHECK_EQ(rb.last_type, KD_EV_FOCUS);
    ra.count = rb.count = 0;
    send_ev(&S, ev_key(KD_KEY_CHAR, 'x', 0));
    CHECK_EQ(rb.count, 1);
    CHECK_EQ(ra.count, 0);
    CHECK_EQ(rb.last_key, KD_KEY_CHAR);
    // Pointer coordinates arrive relative to the work area.
    kd_rect wb = kd_frame_work(b->frame);
    click(&S, wb.x + 7, wb.y + 9, 1000);
    CHECK_EQ(rb.last_type, KD_EV_POINTER_UP);
    CHECK_EQ(rb.last_x, 7);
    CHECK_EQ(rb.last_y, 9);
    // First click on the background window only raises it.
    kd_rect wa = kd_frame_work(a->frame);
    ra.count = 0;
    click(&S, wa.x + 3, wa.y + 3, 2000);
    CHECK(kd_desktop_top(d) == a);
    CHECK_EQ(ra.count, 1);                     // FOCUS only
    CHECK_EQ(ra.last_type, KD_EV_FOCUS);
    CHECK_EQ(rb.last_type, KD_EV_BLUR);
    click(&S, wa.x + 3, wa.y + 3, 3000);
    CHECK_EQ(ra.last_type, KD_EV_POINTER_UP);
    // Double click: two downs within 400 ms at the same place.
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, wa.x + 5, wa.y + 5, 5000));
    CHECK_EQ(ra.last_clicks, 1);
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, wa.x + 5, wa.y + 5, 5050));
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, wa.x + 5, wa.y + 5, 5200));
    CHECK_EQ(ra.last_clicks, 2);
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, wa.x + 5, wa.y + 5, 5250));
    // An open menu captures the keyboard; Escape closes it.
    ra.count = 0;
    send_ev(&S, ev_key(KD_KEY_F10, 0, 0));
    CHECK_EQ(d->menu_open, 0);
    send_ev(&S, ev_key(KD_KEY_DOWN, 0, 0));
    send_ev(&S, ev_key(KD_KEY_ESCAPE, 0, 0));
    CHECK_EQ(d->menu_open, -1);
    CHECK_EQ(ra.count, 0);
    // F6 cycles to the bottom window; Ctrl+W closes the active one.
    send_ev(&S, ev_key(KD_KEY_F6, 0, 0));
    CHECK(kd_desktop_top(d) == b);
    send_ev(&S, ev_key(KD_KEY_CHAR, 'w', KD_MOD_CTRL));
    CHECK(!b->open);
    CHECK(kd_desktop_top(d) == a);
    CHECK_EQ(ra.last_type, KD_EV_FOCUS);
    // Ctrl+arrow moves the active window by 8 pixels.
    int x0 = a->frame.x;
    send_ev(&S, ev_key(KD_KEY_RIGHT, 0, KD_MOD_CTRL));
    CHECK_EQ(a->frame.x, x0 + 8);
    CHECK(frame_consistent(&S));
}

static void test_menus(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    int fx = kd_menu_title_x(d->menus, KD_MENU_FILE);
    click(&S, fx + 2, 4, 100);
    CHECK_EQ(d->menu_open, KD_MENU_FILE);
    CHECK(frame_consistent(&S));
    // Hover over "Close window" and release there.
    kd_rect r = kd_menu_dropdown_rect(d->menus, KD_MENU_FILE);
    int iy = r.y + 1 + KD_FILE_CLOSE * KD_MENU_ITEM_H + 4;
    send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, r.x + 10, iy, 150));
    CHECK_EQ(d->menu_hot, KD_FILE_CLOSE);
    CHECK(frame_consistent(&S));
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, r.x + 10, iy, 200));
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, r.x + 10, iy, 210));
    CHECK_EQ(d->menu_open, -1);
    CHECK(S.studio.win == NULL);              // the top window was closed
    CHECK(frame_consistent(&S));
    // Keyboard: F10, Enter opens About (first item of Desk).
    send_ev(&S, ev_key(KD_KEY_F10, 0, 0));
    CHECK_EQ(d->menu_hot, KD_DESK_ABOUT);
    send_ev(&S, ev_key(KD_KEY_DOWN, 0, 0));    // skips the separator
    CHECK_EQ(d->menu_hot, KD_DESK_FILES);
    send_ev(&S, ev_key(KD_KEY_UP, 0, 0));
    send_ev(&S, ev_key(KD_KEY_ENTER, 0, 0));
    CHECK(S.about.win != NULL);
    CHECK(frame_consistent(&S));
    // Switching menus by hovering titles while open, then clicking outside.
    click(&S, kd_menu_title_x(d->menus, 0) + 2, 4, 300);
    send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, kd_menu_title_x(d->menus, KD_MENU_OPTIONS) + 2, 4, 310));
    CHECK_EQ(d->menu_open, KD_MENU_OPTIONS);
    click(&S, 300, 190, 320);
    CHECK_EQ(d->menu_open, -1);
    CHECK(frame_consistent(&S));
}

static void test_studio_edit_and_import(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    kd_studio *st = &S.studio;
    kd_rect work = kd_frame_work(st->win->frame);
    kd_fb_clear_dirty(&d->fb);
    CHECK(kd_studio_put(st, 5, 6, 9));
    CHECK(frame_consistent(&S));
    kd_fb_clear_dirty(&d->fb);
    CHECK(kd_studio_put(st, 5, 7, 9));
    kd_desktop_render(d);
    CHECK(kd_fb_dirty_count(&d->fb) <= 4);      // one cell + two preview pixels
    int px = work.x + KD_STUDIO_GX + 5 * KD_STUDIO_ZOOM + 3, py = work.y + KD_STUDIO_GY + 7 * KD_STUDIO_ZOOM + 3;
    CHECK_EQ(kd_fb_get(&d->fb, px, py), 9);
    CHECK(frame_consistent(&S));
    // Transparent pixels show the checkerboard, not palette colour 0.
    CHECK(kd_studio_put(st, 3, 5, 0));
    CHECK(frame_consistent(&S));
    int cx = work.x + KD_STUDIO_GX + 3 * KD_STUDIO_ZOOM + 2, cy = work.y + KD_STUDIO_GY + 5 * KD_STUDIO_ZOOM + 2;
    CHECK(kd_fb_get(&d->fb, cx, cy) == KD_C_WHITE || kd_fb_get(&d->fb, cx, cy) == KD_C_LGREY);
    char hex[KD_SPRITE_HEX + 1], back[KD_SPRITE_HEX + 1], other[KD_SPRITE_HEX + 1];
    kd_studio_export_hex(st, hex);
    kd_sample_sprite_hex(1, other);
    CHECK(kd_studio_import_hex(st, other));
    CHECK(frame_consistent(&S));
    kd_studio_export_hex(st, back);
    CHECK(strcmp(back, other) == 0);
    kd_studio_undo(st);
    kd_studio_export_hex(st, back);
    CHECK(strcmp(back, hex) == 0);
    CHECK(frame_consistent(&S));
    CHECK(!kd_studio_import_hex(st, "12"));
    // Keyboard editing through the desktop (Studio is active).
    send_ev(&S, ev_key(KD_KEY_RIGHT, 0, 0));
    send_ev(&S, ev_key(KD_KEY_CHAR, '7', 0));
    send_ev(&S, ev_key(KD_KEY_CHAR, ' ', 0));
    CHECK_EQ(st->cx, 1);
    CHECK_EQ(st->color, 7);
    CHECK_EQ(kd_sprite_get(&st->sprite, 1, 0), 7);
    CHECK(frame_consistent(&S));
    // Painting by dragging across the grid.
    int gx = work.x + KD_STUDIO_GX + 2, gy = work.y + KD_STUDIO_GY + 10 * KD_STUDIO_ZOOM + 2;
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, gx, gy, 9000));
    for (int i = 1; i < 6; i++) send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, gx + i * KD_STUDIO_ZOOM, gy, 9000 + (uint32_t)i));
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, gx + 5 * KD_STUDIO_ZOOM, gy, 9010));
    for (int x = 0; x < 6; x++) CHECK_EQ(kd_sprite_get(&st->sprite, x, 10), 7);
    CHECK(frame_consistent(&S));
}

static void test_filemgr(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    kd_filemgr *fm = &S.fm;
    kd_desktop_activate(d, fm->win);
    kd_rect work = kd_frame_work(fm->win->frame);
    kd_rect c2 = kd_filemgr_icon_rect(2);                       // README.TXT
    click(&S, work.x + c2.x + 30, work.y + c2.y + 8, 1000);
    CHECK_EQ(fm->sel, 2);
    CHECK(frame_consistent(&S));
    send_ev(&S, ev_key(KD_KEY_RIGHT, 0, 0));
    CHECK_EQ(fm->sel, 3);
    send_ev(&S, ev_key(KD_KEY_LEFT, 0, 0));
    // Double click opens the placeholder viewer on top.
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, work.x + c2.x + 30, work.y + c2.y + 8, 2000));
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, work.x + c2.x + 30, work.y + c2.y + 8, 2010));
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, work.x + c2.x + 30, work.y + c2.y + 8, 2100));
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, work.x + c2.x + 30, work.y + c2.y + 8, 2110));
    CHECK(kd_desktop_top(d) == S.viewers[0].win);
    CHECK(strcmp(S.viewers[0].name, "README.TXT") == 0);
    CHECK(frame_consistent(&S));
    send_ev(&S, ev_key(KD_KEY_ESCAPE, 0, 0));
    CHECK(S.viewers[0].win == NULL);
    // Folder navigation and a sprite file loading into the Studio.
    kd_desktop_activate(d, fm->win);
    kd_filemgr_open(fm, 1);                                      // SPRITES
    CHECK_EQ(fm->dir, 2);
    CHECK(strcmp(fm->win->title, "A:\\SPRITES\\") == 0);
    CHECK(frame_consistent(&S));
    kd_filemgr_open(fm, 2);                                      // HEART.SPR
    char hex[KD_SPRITE_HEX + 1], want[KD_SPRITE_HEX + 1];
    kd_studio_export_hex(&S.studio, hex);
    kd_sample_sprite_hex(1, want);
    CHECK(strcmp(hex, want) == 0);
    CHECK(kd_desktop_top(d) == S.studio.win);
    CHECK(frame_consistent(&S));
    kd_desktop_activate(d, fm->win);
    send_ev(&S, ev_key(KD_KEY_BACKSPACE, 0, 0));
    CHECK_EQ(fm->dir, 0);
    CHECK(frame_consistent(&S));
}

static void test_outline_drag(void) {
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    d->outline_drag = true;
    kd_desktop_set_cursor(d, true);
    kd_window *st = S.studio.win;
    kd_rect f0 = st->frame;
    int gx = f0.x + 60, gy = f0.y + 4;
    send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, gx, gy, 0));
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, gx, gy, 0));
    CHECK_EQ(d->drag, KD_DRAG_OUTLINE);
    for (int i = 1; i <= 5; i++) {
        send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, gx - 9 * i, gy - 4 * i, (uint32_t)i));
        CHECK(st->frame.x == f0.x && st->frame.y == f0.y);   // only the outline moves
        CHECK(frame_consistent(&S));
    }
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, gx - 45, gy - 20, 10));
    CHECK_EQ(st->frame.x, f0.x - 45);
    CHECK_EQ(st->frame.y, f0.y - 20);
    CHECK_EQ(d->drag, KD_DRAG_NONE);
    CHECK(frame_consistent(&S));
    // Live drag moves the window on every pointer move.
    d->outline_drag = false;
    f0 = st->frame;
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, f0.x + 60, f0.y + 4, 100));
    send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, f0.x + 70, f0.y + 14, 101));
    CHECK_EQ(st->frame.x, f0.x + 10);
    CHECK(frame_consistent(&S));
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, f0.x + 70, f0.y + 14, 102));
    // Close box: press and release inside closes the window.
    kd_rect cb = kd_frame_close(st->frame);
    click(&S, cb.x + 3, cb.y + 3, 200);
    CHECK(S.studio.win == NULL);
    CHECK(frame_consistent(&S));
}

static void test_window_slots(void) {
    static recorder r;
    kd_shell_init(&S);
    memset(&r, 0, sizeof r);
    for (int i = 0; i < KD_MAX_WINDOWS; i++)
        CHECK(kd_window_open(&S.desk, &rec_class, &r, "W", kd_rect_make(20 + i * 8, 20 + i * 8, 80, 60), 0) != NULL);
    CHECK(kd_window_open(&S.desk, &rec_class, &r, "X", kd_rect_make(0, 20, 80, 60), 0) == NULL);
    CHECK(frame_consistent(&S));
}

static void test_desktop_icons_keyboard(void) {
    kd_shell_init(&S);
    kd_desktop *d = &S.desk;
    send_ev(&S, ev_key(KD_KEY_DOWN, 0, 0));
    CHECK_EQ(d->icon_sel, 0);
    send_ev(&S, ev_key(KD_KEY_DOWN, 0, 0));
    CHECK_EQ(d->icon_sel, 1);
    CHECK(frame_consistent(&S));
    send_ev(&S, ev_key(KD_KEY_ENTER, 0, 0));
    CHECK(S.studio.win != NULL);
    CHECK(frame_consistent(&S));
    // Double click on the FILES icon opens the File Manager.
    const kd_desk_icon *ic = &d->icons[KD_ICON_FILES];
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, ic->x + 8, ic->y + 8, 100));
    send_ev(&S, ev_ptr(KD_EV_POINTER_UP, ic->x + 8, ic->y + 8, 110));
    send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, ic->x + 8, ic->y + 8, 300));
    CHECK(S.fm.win != NULL);
    CHECK(frame_consistent(&S));
}

// Random operation sequence: the central incremental == full invariant.
// Each seed also varies the options: outline drag, and painter's algorithm
// for the incremental frames themselves.
static void random_run(uint32_t seed, bool outline, bool painter) {
    uint32_t s = seed;
    kd_shell_demo_scene(&S);
    kd_desktop *d = &S.desk;
    kd_desktop_set_cursor(d, true);
    d->outline_drag = outline;
    d->painter = painter;
    uint32_t t = 0;
    for (int op = 0; op < 600; op++) {
        t += 37;
        kd_window *w = d->zn ? &d->win[d->z[kd_rand(&s) % d->zn]] : NULL;
        int kind = (int)(kd_rand(&s) % 14);
        switch (kind) {
        case 0: kd_shell_open_about(&S); break;
        case 1: kd_shell_open_files(&S); break;
        case 2: kd_shell_open_studio(&S); break;
        case 3: if (w) kd_window_close(d, w); break;
        case 4: if (w) kd_desktop_activate(d, w); break;
        case 5:
            if (w) kd_desktop_move(d, w, w->frame.x + kd_rand_range(&s, -30, 30), w->frame.y + kd_rand_range(&s, -20, 20));
            break;
        case 6: send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, kd_rand_range(&s, -5, 324), kd_rand_range(&s, -5, 204), t)); break;
        case 7: {
            int x = kd_rand_range(&s, 0, 319), y = kd_rand_range(&s, 0, 199);
            send_ev(&S, ev_ptr(KD_EV_POINTER_DOWN, x, y, t));
            send_ev(&S, ev_ptr(KD_EV_POINTER_MOVE, x + kd_rand_range(&s, -20, 20), y + kd_rand_range(&s, -20, 20), t + 1));
            send_ev(&S, ev_ptr(KD_EV_POINTER_UP, x, y, t + 2));
            break;
        }
        case 8: {
            static const uint8_t keys[] = {KD_KEY_UP, KD_KEY_DOWN, KD_KEY_LEFT, KD_KEY_RIGHT, KD_KEY_ENTER,
                                           KD_KEY_ESCAPE, KD_KEY_TAB, KD_KEY_F10, KD_KEY_F6, KD_KEY_BACKSPACE};
            send_ev(&S, ev_key(keys[kd_rand(&s) % sizeof keys], 0, (kd_rand(&s) % 5 == 0) ? KD_MOD_CTRL : 0));
            break;
        }
        case 9: send_ev(&S, ev_key(KD_KEY_CHAR, "0123456789abcdefu x"[kd_rand(&s) % 19], 0)); break;
        case 10: kd_studio_put(&S.studio, kd_rand_range(&s, 0, 15), kd_rand_range(&s, 0, 15), kd_rand_range(&s, 0, 15)); break;
        case 11: {
            char hex[KD_SPRITE_HEX + 1];
            kd_sample_sprite_hex((int)(kd_rand(&s) % KD_SAMPLE_SPRITES), hex);
            kd_studio_import_hex(&S.studio, hex);
            break;
        }
        case 12: if (kd_rand(&s) & 1) kd_desktop_open_menu(d, (int)(kd_rand(&s) % 3)); else kd_desktop_close_menu(d); break;
        default: kd_filemgr_select(&S.fm, kd_rand_range(&s, -1, 7)); break;
        }
        S.quit = false;
        if (!frame_consistent(&S)) {
            char msg[80];
            snprintf(msg, sizeof msg, "seed %u: frame differs after op %d (kind %d)", (unsigned)seed, op, kind);
            kd_test_fail(__FILE__, __LINE__, msg);
            return;
        }
    }
    CHECK(frame_consistent(&S));
    CHECK_EQ(d->stats.fallbacks, 0);
}

static void test_random_sequence_equivalence(void) {
    random_run(2026, false, false);
    if (kd_test_failed) return;
    random_run(7, true, false);
    if (kd_test_failed) return;
    random_run(99, false, true);
}

// A desktop without icons (as the MicroPython binding creates) ignores the
// icon keys; Left/Up used to select icon 0 of an empty table.
static void test_keys_without_icons(void) {
    static const kd_menu none[] = {{NULL, NULL}};
    kd_shell_hooks hooks = {NULL, NULL, NULL};
    kd_desktop *d = &S.desk;
    kd_desktop_init(d, none, NULL, 0, hooks);
    kd_desktop_render(d);
    static const uint8_t keys[] = {KD_KEY_LEFT, KD_KEY_UP, KD_KEY_RIGHT, KD_KEY_DOWN, KD_KEY_TAB, KD_KEY_ENTER};
    for (unsigned i = 0; i < sizeof keys; i++) {
        kd_event e;
        memset(&e, 0, sizeof e);
        e.type = KD_EV_KEY;
        e.key = keys[i];
        kd_desktop_event(d, &e);
        CHECK_EQ(d->icon_sel, -1);
    }
    CHECK(!kd_desktop_render(d));
}

const kd_test_case kd_desktop_tests[] = {
    {"scene_renders", test_scene_renders},
    {"z_order_and_hit", test_z_order_and_hit},
    {"exposure_raise_move_close", test_exposure_on_raise_move_close},
    {"targeted_invalidation", test_targeted_invalidation},
    {"focus_and_dispatch", test_focus_and_dispatch},
    {"menus", test_menus},
    {"studio_edit_import", test_studio_edit_and_import},
    {"filemgr", test_filemgr},
    {"drag_outline_live_close", test_outline_drag},
    {"window_slots", test_window_slots},
    {"desktop_icons_keyboard", test_desktop_icons_keyboard},
    {"keys_without_icons", test_keys_without_icons},
    {"random_sequence_equivalence", test_random_sequence_equivalence},
    {NULL, NULL},
};
