// SPDX-License-Identifier: Apache-2.0
// kagura_desktop: MicroPython binding of the C desktop (see ../DESIGN.md).
//
// All native state is the static `state` below, outside the GC heap. It holds
// no Python objects. Python objects hold handles (slot + serial, desktop
// generation), never C pointers, and every method validates its handle
// before touching anything. kdm calls are atomic, so an exception leaves the
// native state as it was.
#include <string.h>

#include "py/mperrno.h"
#include "py/mphal.h"
#include "py/nlr.h"
#include "py/objarray.h"
#include "py/objint.h"
#include "py/runtime.h"

#include "kdm.h"

static kdm state;    // framebuffer, windows, pools: the single owner
static bool busy;    // inside a Python present() sink

typedef struct {
    mp_obj_base_t base;
    uint32_t generation;
    mp_obj_t windows[KD_MAX_WINDOWS];   // handle per slot, so poll() can return it
} desktop_obj_t;

typedef struct {
    mp_obj_base_t base;
    desktop_obj_t *desk;
    uint32_t serial;
    int8_t slot;
} handle_obj_t;   // Window and Sprite

static const mp_obj_type_t desktop_type, window_type, sprite_type;

static MP_NORETURN void raise_rc(int rc) {
    switch (rc) {
    case KDM_ESTALE: mp_raise_ValueError(MP_ERROR_TEXT("closed window, freed sprite or removed item"));
    case KDM_ENOITEM: mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("kagura_desktop: item pool full"));
    case KDM_ENOTEXT: mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("kagura_desktop: text arena full"));
    case KDM_ENOWIN: mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("kagura_desktop: no free window slot"));
    case KDM_ENOSPRITE: mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("kagura_desktop: sprite pool full"));
    case KDM_ENOMENU: mp_raise_ValueError(MP_ERROR_TEXT("menus too large"));
    case KDM_ESINK: mp_raise_OSError(MP_EIO);
    default: mp_raise_ValueError(MP_ERROR_TEXT("invalid argument"));
    }
}

static int check(int rc) {
    if (rc < 0) raise_rc(rc);
    return rc;
}

static desktop_obj_t *live_desktop(desktop_obj_t *d) {
    if (d->generation != state.generation) mp_raise_ValueError(MP_ERROR_TEXT("desktop closed"));
    if (busy) mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("desktop busy in present() sink"));
    return d;
}

static desktop_obj_t *desk_arg(mp_obj_t o) { return live_desktop(MP_OBJ_TO_PTR(o)); }

static int win_arg(mp_obj_t o) {
    handle_obj_t *h = MP_OBJ_TO_PTR(o);
    live_desktop(h->desk);
    check(kdm_window_check(&state, h->slot, h->serial));
    return h->slot;
}

static int sprite_arg(mp_obj_t o) {
    if (!mp_obj_is_type(o, &sprite_type)) mp_raise_TypeError(MP_ERROR_TEXT("expected Sprite"));
    handle_obj_t *h = MP_OBJ_TO_PTR(o);
    live_desktop(h->desk);
    check(kdm_sprite_check(&state, h->slot, h->serial));
    return h->slot;
}

// Coordinates, colours and small options: anything outside int16 is an error
// here, so no value is silently truncated on the way to the core.
static int i16(mp_obj_t o) {
    mp_int_t v = mp_obj_get_int(o);
    if (v < -32768 || v > 32767) raise_rc(KDM_EINVAL);
    return (int)v;
}

static uint8_t col(mp_obj_t o) {
    mp_int_t v = mp_obj_get_int(o);
    if (v < 0 || v > 15) raise_rc(KDM_EINVAL);
    return (uint8_t)v;
}

// Item ids are index | serial << 9 (at most 25 bits).
static int id_arg(mp_obj_t o) {
    mp_int_t v = mp_obj_get_int(o);
    return v < 0 || v > 0x1FFFFFF ? -1 : (int)v;
}

static int int_arg(size_t n_args, const mp_obj_t *args, size_t i, int dflt) {
    return i < n_args && args[i] != mp_const_none ? i16(args[i]) : dflt;
}

static handle_obj_t *new_handle(const mp_obj_type_t *type, desktop_obj_t *d, int slot, uint32_t serial) {
    handle_obj_t *h = mp_obj_malloc(handle_obj_t, type);
    h->desk = d;
    h->slot = (int8_t)slot;
    h->serial = serial;
    return h;
}

// Event time in ms: None or negative means now; otherwise any int, used modulo
// 2**32 like ticks_ms() (only differences matter).
static uint32_t now_ms(size_t n_args, const mp_obj_t *args, size_t i) {
    if (i >= n_args || args[i] == mp_const_none) return (uint32_t)mp_hal_ticks_ms();
    if (!mp_obj_is_int(args[i])) mp_raise_TypeError(MP_ERROR_TEXT("time must be an int"));
    if (mp_obj_int_sign(args[i]) < 0) return (uint32_t)mp_hal_ticks_ms();
    return (uint32_t)mp_obj_int_get_truncated(args[i]);
}

// ---- Desktop ----

static void parse_menus(mp_obj_t menus, kdm_menu_def *def) {
    size_t n, used = 0;
    mp_obj_t *menu;
    mp_obj_get_array(menus, &n, &menu);
    if (n > KDM_MENUS) mp_raise_ValueError(MP_ERROR_TEXT("menus too large"));
    def->count = (int)n;
    for (size_t i = 0; i < n; i++) {
        mp_obj_t *pair, *items;
        size_t ni;
        mp_obj_get_array_fixed_n(menu[i], 2, &pair);
        def->titles[i] = mp_obj_str_get_str(pair[0]);
        used += strlen(def->titles[i]) + 1;
        mp_obj_get_array(pair[1], &ni, &items);
        if (ni < 1 || ni > KDM_MENU_ITEMS) mp_raise_ValueError(MP_ERROR_TEXT("menus too large"));
        def->counts[i] = (int)ni;
        for (size_t k = 0; k < ni; k++) {
            def->items[i][k] = mp_obj_str_get_str(items[k]);
            used += strlen(def->items[i][k]) + 1;
        }
    }
    if (used > KDM_MENU_TEXT) mp_raise_ValueError(MP_ERROR_TEXT("menus too large"));
}

// Desktop(width=320, height=200, *, menus=None, cursor=True, outline_drag=False)
static mp_obj_t desktop_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    enum { ARG_width, ARG_height, ARG_menus, ARG_cursor, ARG_outline_drag };
    static const mp_arg_t allowed[] = {
        {MP_QSTR_width, MP_ARG_INT, {.u_int = KD_W}},
        {MP_QSTR_height, MP_ARG_INT, {.u_int = KD_H}},
        {MP_QSTR_menus, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_rom_obj = MP_ROM_NONE}},
        {MP_QSTR_cursor, MP_ARG_KW_ONLY | MP_ARG_BOOL, {.u_bool = true}},
        {MP_QSTR_outline_drag, MP_ARG_KW_ONLY | MP_ARG_BOOL, {.u_bool = false}},
    };
    mp_arg_val_t a[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args, MP_ARRAY_SIZE(allowed), allowed, a);
    if (a[ARG_width].u_int != KD_W || a[ARG_height].u_int != KD_H)
        mp_raise_ValueError(MP_ERROR_TEXT("the desktop is 320x200"));
    if (busy) mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("desktop busy in present() sink"));
    kdm_menu_def def;
    memset(&def, 0, sizeof def);
    if (a[ARG_menus].u_obj != mp_const_none) parse_menus(a[ARG_menus].u_obj, &def);
    desktop_obj_t *d = mp_obj_malloc(desktop_obj_t, type);   // before any native change
    for (int i = 0; i < KD_MAX_WINDOWS; i++) d->windows[i] = mp_const_none;
    check(kdm_init(&state, a[ARG_menus].u_obj != mp_const_none ? &def : NULL));
    d->generation = state.generation;
    kd_desktop_set_cursor(&state.desk, a[ARG_cursor].u_bool);
    state.desk.outline_drag = a[ARG_outline_drag].u_bool;
    return MP_OBJ_FROM_PTR(d);
}

// create_window(title, x, y, w, h, *, bg=2, closable=True, movable=True)
static mp_obj_t desktop_create_window(size_t n_args, const mp_obj_t *pos, mp_map_t *kw) {
    enum { ARG_title, ARG_x, ARG_y, ARG_w, ARG_h, ARG_bg, ARG_closable, ARG_movable };
    static const mp_arg_t allowed[] = {
        {MP_QSTR_title, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_rom_obj = MP_ROM_NONE}},
        {MP_QSTR_x, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0}},
        {MP_QSTR_y, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0}},
        {MP_QSTR_w, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0}},
        {MP_QSTR_h, MP_ARG_REQUIRED | MP_ARG_INT, {.u_int = 0}},
        {MP_QSTR_bg, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = KD_C_WHITE}},
        {MP_QSTR_closable, MP_ARG_KW_ONLY | MP_ARG_BOOL, {.u_bool = true}},
        {MP_QSTR_movable, MP_ARG_KW_ONLY | MP_ARG_BOOL, {.u_bool = true}},
    };
    desktop_obj_t *d = desk_arg(pos[0]);
    mp_arg_val_t a[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args - 1, pos + 1, kw, MP_ARRAY_SIZE(allowed), allowed, a);
    size_t len;
    const char *t = mp_obj_str_get_data(a[ARG_title].u_obj, &len);
    char title[KD_TITLE_MAX];
    if (len >= sizeof title) len = sizeof title - 1;
    memcpy(title, t, len);
    title[len] = 0;
    mp_int_t x = a[ARG_x].u_int, y = a[ARG_y].u_int, w = a[ARG_w].u_int, h = a[ARG_h].u_int, bg = a[ARG_bg].u_int;
    if (w < 0 || w > 32767 || h < 0 || h > 32767 || x < -32768 || x > 32767 || y < -32768 || y > 32767 ||
        bg < 0 || bg > 15)
        raise_rc(KDM_EINVAL);
    unsigned flags = (a[ARG_closable].u_bool ? KD_WF_CLOSE : 0) | (a[ARG_movable].u_bool ? KD_WF_MOVE : 0);
    handle_obj_t *o = new_handle(&window_type, d, -1, 0);   // allocate before the native window
    int slot = check(kdm_window_open(&state, title, kd_rect_make(x, y, w, h), flags, (uint8_t)bg));
    o->slot = (int8_t)slot;
    o->serial = state.win[slot].serial;
    d->windows[slot] = MP_OBJ_FROM_PTR(o);
    return MP_OBJ_FROM_PTR(o);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(desktop_create_window_obj, 6, desktop_create_window);

// sprite(data=None): 128 TILE4 bytes or 256 hex digits.
static void sprite_bytes(mp_obj_t data, uint8_t out[KD_SPRITE_BYTES]) {
    if (mp_obj_is_str(data)) {
        size_t len;
        const char *s = mp_obj_str_get_data(data, &len);
        kd_sprite sp;
        if (len != KD_SPRITE_HEX || !kd_sprite_import_hex(&sp, s, NULL))
            mp_raise_ValueError(MP_ERROR_TEXT("expected 256 hex digits"));
        memcpy(out, sp.data, KD_SPRITE_BYTES);
        return;
    }
    mp_buffer_info_t bi;
    mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
    if (bi.len != KD_SPRITE_BYTES) mp_raise_ValueError(MP_ERROR_TEXT("expected 128 bytes"));
    memcpy(out, bi.buf, KD_SPRITE_BYTES);
}

static mp_obj_t desktop_sprite(size_t n_args, const mp_obj_t *args) {
    desktop_obj_t *d = desk_arg(args[0]);
    uint8_t data[KD_SPRITE_BYTES];
    bool have = n_args > 1 && args[1] != mp_const_none;
    if (have) sprite_bytes(args[1], data);
    handle_obj_t *o = new_handle(&sprite_type, d, -1, 0);
    int s = check(kdm_sprite_alloc(&state, have ? data : NULL));
    o->slot = (int8_t)s;
    o->serial = state.sprites[s].serial;
    return MP_OBJ_FROM_PTR(o);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(desktop_sprite_obj, 1, 2, desktop_sprite);

// pointer(kind, x, y, t=None, button=1)
static mp_obj_t desktop_pointer(size_t n_args, const mp_obj_t *args) {
    desk_arg(args[0]);
    kd_event ev;
    memset(&ev, 0, sizeof ev);
    mp_int_t kind = mp_obj_get_int(args[1]);
    if (kind < KD_EV_POINTER_MOVE || kind > KD_EV_POINTER_UP) raise_rc(KDM_EINVAL);
    ev.type = (uint8_t)kind;
    ev.x = (int16_t)i16(args[2]);
    ev.y = (int16_t)i16(args[3]);
    ev.time_ms = now_ms(n_args, args, 4);
    ev.button = (uint8_t)int_arg(n_args, args, 5, KD_BUTTON_LEFT);
    kdm_feed(&state, &ev);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(desktop_pointer_obj, 4, 6, desktop_pointer);

// key(key, ch=0, mods=0, t=None); ch is an int or a one-character str.
static mp_obj_t desktop_key(size_t n_args, const mp_obj_t *args) {
    desk_arg(args[0]);
    kd_event ev;
    memset(&ev, 0, sizeof ev);
    ev.type = KD_EV_KEY;
    mp_int_t key = mp_obj_get_int(args[1]);
    if (key < 0 || key > 255) raise_rc(KDM_EINVAL);
    ev.key = (uint8_t)key;
    if (n_args > 2 && mp_obj_is_str(args[2])) {
        size_t len;
        const char *s = mp_obj_str_get_data(args[2], &len);
        if (len != 1) raise_rc(KDM_EINVAL);
        ev.ch = s[0];
    } else {
        ev.ch = (char)int_arg(n_args, args, 2, 0);
    }
    ev.mods = (uint8_t)int_arg(n_args, args, 3, 0);
    ev.time_ms = now_ms(n_args, args, 4);
    kdm_feed(&state, &ev);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(desktop_key_obj, 2, 5, desktop_key);

// The Window object for an event: the live handle, or a dead one when the
// slot has been reused since (it compares equal to the original handle).
static mp_obj_t event_window(desktop_obj_t *d, const kdm_event *e) {
    if (e->win < 0) return mp_const_none;
    mp_obj_t o = d->windows[e->win];
    if (o != mp_const_none && ((handle_obj_t *)MP_OBJ_TO_PTR(o))->serial == e->serial) return o;
    return MP_OBJ_FROM_PTR(new_handle(&window_type, d, e->win, e->serial));
}

static void event_fields(desktop_obj_t *d, const kdm_event *e, mp_obj_t out[8]) {
    out[0] = MP_OBJ_NEW_SMALL_INT(e->ev.type);
    out[1] = event_window(d, e);   // may allocate: before the event is dropped
    out[2] = MP_OBJ_NEW_SMALL_INT(e->ev.x);
    out[3] = MP_OBJ_NEW_SMALL_INT(e->ev.y);
    out[4] = MP_OBJ_NEW_SMALL_INT(e->ev.key);
    out[5] = MP_OBJ_NEW_SMALL_INT((uint8_t)e->ev.ch);
    out[6] = MP_OBJ_NEW_SMALL_INT(e->ev.mods);
    out[7] = MP_OBJ_NEW_SMALL_INT(e->ev.clicks);
}

static mp_obj_t desktop_poll(mp_obj_t self) {
    desktop_obj_t *d = desk_arg(self);
    kdm_event e;
    if (!kdm_peek(&state, &e)) return mp_const_none;
    mp_obj_t f[8];
    event_fields(d, &e, f);
    mp_obj_t t = mp_obj_new_tuple(8, f);
    kdm_drop(&state);
    return t;
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_poll_obj, desktop_poll);

// poll_into(lst): fills a list of at least 8 items; allocates nothing for
// live windows. Returns False when no event is pending.
static mp_obj_t desktop_poll_into(mp_obj_t self, mp_obj_t lst) {
    desktop_obj_t *d = desk_arg(self);
    if (!mp_obj_is_type(lst, &mp_type_list)) mp_raise_TypeError(MP_ERROR_TEXT("expected list"));
    size_t n;
    mp_obj_t *items;
    mp_obj_get_array(lst, &n, &items);
    if (n < 8) raise_rc(KDM_EINVAL);
    kdm_event e;
    if (!kdm_peek(&state, &e)) return mp_const_false;
    mp_obj_t f[8];
    event_fields(d, &e, f);
    memcpy(items, f, sizeof f);
    kdm_drop(&state);
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_2(desktop_poll_into_obj, desktop_poll_into);

static mp_obj_t desktop_render(mp_obj_t self) {
    desk_arg(self);
    return mp_obj_new_bool(kdm_render(&state));
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_render_obj, desktop_render);

typedef struct {
    mp_obj_t fn;
    uint8_t *mirror;
    mp_obj_t exc;
} sink_ctx;

static bool mirror_sink(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    memcpy(((sink_ctx *)ctx)->mirror + first * KD_TILE4_BYTES, data, count * KD_TILE4_BYTES);
    return true;
}

// Calls sink(first_tile, memoryview). An exception stops the flush (unsent
// runs stay dirty) and is re-raised by present() after the core returned.
static bool call_sink(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    sink_ctx *c = ctx;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t mv = mp_obj_new_memoryview('B', count * KD_TILE4_BYTES, (void *)data);   // read-only
        mp_obj_t r = mp_call_function_2(c->fn, MP_OBJ_NEW_SMALL_INT(first), mv);
        nlr_pop();
        return r != mp_const_false;
    }
    c->exc = MP_OBJ_FROM_PTR(nlr.ret_val);
    return false;
}

// present(sink=None, max_gap=0): render the damage and export dirty TILE4 runs,
// joining runs separated by at most max_gap clean tiles (0..999). sink is
// None, a writable buffer of >= 32,000 bytes (TILE4 mirror at pattern
// offsets) or a callable sink(first_tile, memoryview) valid during the call.
// Returns the number of tiles exported.
static mp_obj_t desktop_present(size_t n_args, const mp_obj_t *args) {
    desk_arg(args[0]);
    sink_ctx c = {mp_const_none, NULL, MP_OBJ_NULL};
    kd_tile4_sink sink = NULL;
    mp_obj_t s = n_args > 1 ? args[1] : mp_const_none;
    int max_gap = int_arg(n_args, args, 2, 0);
    if (max_gap < 0 || max_gap > KD_TILES - 1) raise_rc(KDM_EINVAL);
    mp_buffer_info_t bi;
    if (s == mp_const_none) {
    } else if (mp_get_buffer(s, &bi, MP_BUFFER_WRITE)) {
        if (bi.len < KD_TILE4_TOTAL) mp_raise_ValueError(MP_ERROR_TEXT("buffer smaller than 32000 bytes"));
        c.mirror = bi.buf;
        sink = mirror_sink;
    } else if (mp_obj_is_callable(s)) {
        c.fn = s;
        sink = call_sink;
    } else {
        mp_raise_TypeError(MP_ERROR_TEXT("sink must be None, a buffer or a callable"));
    }
    busy = sink == call_sink;
    int rc = kdm_present_gap(&state, (unsigned)max_gap, sink, &c, NULL);
    busy = false;
    if (c.exc != MP_OBJ_NULL) nlr_raise(c.exc);
    return MP_OBJ_NEW_SMALL_INT(check(rc));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(desktop_present_obj, 1, 3, desktop_present);

// invalidate(x, y, w, h): recompose a screen area at the next present().
static mp_obj_t desktop_invalidate(size_t n_args, const mp_obj_t *a) {
    desk_arg(a[0]);
    kd_desktop_invalidate(&state.desk, kd_rect_make(i16(a[1]), i16(a[2]), i16(a[3]), i16(a[4])));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(desktop_invalidate_obj, 5, 5, desktop_invalidate);

static mp_obj_t desktop_top(mp_obj_t self) {
    desktop_obj_t *d = desk_arg(self);
    kd_window *w = kd_desktop_top(&state.desk);
    return w ? d->windows[w - state.desk.win] : mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_top_obj, desktop_top);

static mp_obj_t desktop_windows(mp_obj_t self) {
    desktop_obj_t *d = desk_arg(self);
    mp_obj_t w[KD_MAX_WINDOWS];
    for (int i = 0; i < state.desk.zn; i++) w[i] = d->windows[state.desk.z[i]];
    return mp_obj_new_tuple(state.desk.zn, w);
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_windows_obj, desktop_windows);

static mp_obj_t desktop_crc(mp_obj_t self) {
    desk_arg(self);
    return mp_obj_new_int_from_uint(kdm_crc32(0, state.desk.fb.px, KD_FB_BYTES));
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_crc_obj, desktop_crc);

static void *out_buffer(mp_obj_t o, size_t need) {
    mp_buffer_info_t bi;
    mp_get_buffer_raise(o, &bi, MP_BUFFER_WRITE);
    if (bi.len < need) mp_raise_ValueError(MP_ERROR_TEXT("buffer smaller than 32000 bytes"));
    return bi.buf;
}

// snapshot(buf): the linear 4bpp plane (rows of 160 bytes); for tests.
static mp_obj_t desktop_snapshot(mp_obj_t self, mp_obj_t buf) {
    desk_arg(self);
    memcpy(out_buffer(buf, KD_FB_BYTES), state.desk.fb.px, KD_FB_BYTES);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(desktop_snapshot_obj, desktop_snapshot);

// tile4(buf): the whole plane packed as 1,000 TILE4 patterns; for tests.
static mp_obj_t desktop_tile4(mp_obj_t self, mp_obj_t buf) {
    desk_arg(self);
    kd_tile4_pack_all(&state.desk.fb, out_buffer(buf, KD_TILE4_TOTAL));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(desktop_tile4_obj, desktop_tile4);

static mp_obj_t desktop_set_cursor(mp_obj_t self, mp_obj_t on) {
    desk_arg(self);
    kd_desktop_set_cursor(&state.desk, mp_obj_is_true(on));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(desktop_set_cursor_obj, desktop_set_cursor);

static mp_obj_t desktop_set_outline_drag(mp_obj_t self, mp_obj_t on) {
    desk_arg(self);
    state.desk.outline_drag = mp_obj_is_true(on);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(desktop_set_outline_drag_obj, desktop_set_outline_drag);

static void put(mp_obj_t dict, qstr key, mp_uint_t value) {
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(key), mp_obj_new_int_from_uint(value));
}

static mp_obj_t desktop_stats(mp_obj_t self) {
    desk_arg(self);
    const kdm_stats *s = &state.stats;
    const kd_compose_stats *c = &state.desk.stats;
    mp_obj_t d = mp_obj_new_dict(16);
    put(d, MP_QSTR_items, s->items);
    put(d, MP_QSTR_items_peak, s->items_peak);
    put(d, MP_QSTR_text, s->text);
    put(d, MP_QSTR_text_peak, s->text_peak);
    put(d, MP_QSTR_compactions, s->compactions);
    put(d, MP_QSTR_dropped, s->dropped);
    put(d, MP_QSTR_pending, state.ring_count);
    put(d, MP_QSTR_presents, s->presents);
    put(d, MP_QSTR_tiles, s->tiles);
    put(d, MP_QSTR_runs, s->runs);
    put(d, MP_QSTR_renders, c->renders);
    put(d, MP_QSTR_layers, c->layers);
    put(d, MP_QSTR_last_area, (mp_uint_t)c->last_area);
    put(d, MP_QSTR_last_tiles, c->last_damage_tiles);
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_stats_obj, desktop_stats);

// close(): the native desktop is reset; this object and its handles die.
static mp_obj_t desktop_close(mp_obj_t self) {
    desktop_obj_t *d = MP_OBJ_TO_PTR(self);
    if (d->generation != state.generation) return mp_const_none;
    if (busy) mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("desktop busy in present() sink"));
    kdm_init(&state, NULL);
    for (int i = 0; i < KD_MAX_WINDOWS; i++) d->windows[i] = mp_const_none;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_close_obj, desktop_close);

static mp_obj_t desktop_is_open(mp_obj_t self) {
    return mp_obj_new_bool(((desktop_obj_t *)MP_OBJ_TO_PTR(self))->generation == state.generation);
}
static MP_DEFINE_CONST_FUN_OBJ_1(desktop_is_open_obj, desktop_is_open);

static const mp_rom_map_elem_t desktop_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_create_window), MP_ROM_PTR(&desktop_create_window_obj)},
    {MP_ROM_QSTR(MP_QSTR_sprite), MP_ROM_PTR(&desktop_sprite_obj)},
    {MP_ROM_QSTR(MP_QSTR_pointer), MP_ROM_PTR(&desktop_pointer_obj)},
    {MP_ROM_QSTR(MP_QSTR_key), MP_ROM_PTR(&desktop_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_poll), MP_ROM_PTR(&desktop_poll_obj)},
    {MP_ROM_QSTR(MP_QSTR_poll_into), MP_ROM_PTR(&desktop_poll_into_obj)},
    {MP_ROM_QSTR(MP_QSTR_render), MP_ROM_PTR(&desktop_render_obj)},
    {MP_ROM_QSTR(MP_QSTR_present), MP_ROM_PTR(&desktop_present_obj)},
    {MP_ROM_QSTR(MP_QSTR_invalidate), MP_ROM_PTR(&desktop_invalidate_obj)},
    {MP_ROM_QSTR(MP_QSTR_top), MP_ROM_PTR(&desktop_top_obj)},
    {MP_ROM_QSTR(MP_QSTR_windows), MP_ROM_PTR(&desktop_windows_obj)},
    {MP_ROM_QSTR(MP_QSTR_crc), MP_ROM_PTR(&desktop_crc_obj)},
    {MP_ROM_QSTR(MP_QSTR_snapshot), MP_ROM_PTR(&desktop_snapshot_obj)},
    {MP_ROM_QSTR(MP_QSTR_tile4), MP_ROM_PTR(&desktop_tile4_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_cursor), MP_ROM_PTR(&desktop_set_cursor_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_outline_drag), MP_ROM_PTR(&desktop_set_outline_drag_obj)},
    {MP_ROM_QSTR(MP_QSTR_stats), MP_ROM_PTR(&desktop_stats_obj)},
    {MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&desktop_close_obj)},
    {MP_ROM_QSTR(MP_QSTR_is_open), MP_ROM_PTR(&desktop_is_open_obj)},
};
static MP_DEFINE_CONST_DICT(desktop_locals, desktop_locals_table);

static MP_DEFINE_CONST_OBJ_TYPE(desktop_type, MP_QSTR_Desktop, MP_TYPE_FLAG_NONE,
                                make_new, desktop_make_new, locals_dict, &desktop_locals);

// ---- Window ----

static mp_obj_t ret_id(int rc) { return MP_OBJ_NEW_SMALL_INT(check(rc)); }

static size_t text_arg(mp_obj_t o, const char **s) {
    size_t len;
    *s = mp_obj_str_get_data(o, &len);
    return len;
}

// fill_rect(x, y, w, h, color) -> item id
static mp_obj_t window_fill_rect(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    return ret_id(kdm_add_fill(&state, slot, i16(a[1]), i16(a[2]), i16(a[3]),
                               i16(a[4]), col(a[5])));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_fill_rect_obj, 6, 6, window_fill_rect);

static mp_obj_t window_rect(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    return ret_id(kdm_add_rect(&state, slot, i16(a[1]), i16(a[2]), i16(a[3]),
                               i16(a[4]), col(a[5])));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_rect_obj, 6, 6, window_rect);

static mp_obj_t window_hline(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    return ret_id(kdm_add_hline(&state, slot, i16(a[1]), i16(a[2]), i16(a[3]),
                                col(a[4])));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_hline_obj, 5, 5, window_hline);

static mp_obj_t window_vline(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    return ret_id(kdm_add_vline(&state, slot, i16(a[1]), i16(a[2]), i16(a[3]),
                                col(a[4])));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_vline_obj, 5, 5, window_vline);

// fill_rects(buf, color): buf holds x, y, w, h quads of int16 (array('h')).
// All rectangles or none are added. Returns the first item id.
static mp_obj_t window_fill_rects(mp_obj_t self, mp_obj_t buf, mp_obj_t color) {
    int slot = win_arg(self);
    mp_buffer_info_t bi;
    mp_get_buffer_raise(buf, &bi, MP_BUFFER_READ);
    if (bi.typecode != 'h' || bi.len % 8) mp_raise_ValueError(MP_ERROR_TEXT("expected array('h') of x, y, w, h"));
    return ret_id(kdm_add_fills(&state, slot, bi.buf, (int)(bi.len / 8), col(color)));
}
static MP_DEFINE_CONST_FUN_OBJ_3(window_fill_rects_obj, window_fill_rects);

// text(x, y, s, fg=1, bg=-1, font=0); bg -1 is transparent, font 1 is 4x8.
static mp_obj_t window_text(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    const char *s;
    size_t len = text_arg(a[3], &s);
    return ret_id(kdm_add_text(&state, slot, i16(a[1]), i16(a[2]), s, len,
                               (uint8_t)int_arg(n_args, a, 4, KD_C_BLACK), int_arg(n_args, a, 5, -1),
                               int_arg(n_args, a, 6, 0)));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_text_obj, 4, 7, window_text);

// button(x, y, w, h, label, flags=0)
static mp_obj_t window_button(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    const char *s;
    size_t len = text_arg(a[5], &s);
    return ret_id(kdm_add_button(&state, slot, i16(a[1]), i16(a[2]), i16(a[3]),
                                 i16(a[4]), s, len, (unsigned)int_arg(n_args, a, 6, 0)));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_button_obj, 6, 7, window_button);

// sprite(x, y, spr, zoom=1, key=-1)
static mp_obj_t window_sprite(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    int s = sprite_arg(a[3]);
    return ret_id(kdm_add_sprite(&state, slot, i16(a[1]), i16(a[2]), s,
                                 int_arg(n_args, a, 4, 1), int_arg(n_args, a, 5, -1)));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_sprite_obj, 4, 6, window_sprite);

// icon(x, y, name, label, selected=False); name is one of kd.ICONS.
static mp_obj_t window_icon(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    const char *name, *label;
    size_t nlen = text_arg(a[3], &name), llen = text_arg(a[4], &label);
    int art = check(kdm_icon_lookup(name, nlen));
    return ret_id(kdm_add_icon(&state, slot, i16(a[1]), i16(a[2]), art, label, llen,
                               n_args > 5 && mp_obj_is_true(a[5])));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_icon_obj, 5, 6, window_icon);

static mp_obj_t window_set_text(mp_obj_t self, mp_obj_t id, mp_obj_t text) {
    int slot = win_arg(self);
    const char *s;
    size_t len = text_arg(text, &s);
    check(kdm_item_set_text(&state, slot, id_arg(id), s, len));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(window_set_text_obj, window_set_text);

static mp_obj_t window_set_color(mp_obj_t self, mp_obj_t id, mp_obj_t color) {
    int slot = win_arg(self);
    check(kdm_item_set_color(&state, slot, id_arg(id), col(color)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(window_set_color_obj, window_set_color);

static mp_obj_t window_set_flags(mp_obj_t self, mp_obj_t id, mp_obj_t flags) {
    int slot = win_arg(self);
    check(kdm_item_set_flags(&state, slot, id_arg(id), (unsigned)i16(flags)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(window_set_flags_obj, window_set_flags);

static mp_obj_t window_move_item(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    check(kdm_item_move(&state, slot, id_arg(a[1]), i16(a[2]), i16(a[3])));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_move_item_obj, 4, 4, window_move_item);

static mp_obj_t window_remove(mp_obj_t self, mp_obj_t id) {
    int slot = win_arg(self);
    check(kdm_item_remove(&state, slot, id_arg(id)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(window_remove_obj, window_remove);

// clear(bg=None): removes every record; bg changes the background colour.
static mp_obj_t window_clear(size_t n_args, const mp_obj_t *a) {
    int slot = win_arg(a[0]);
    check(kdm_window_clear(&state, slot, int_arg(n_args, a, 1, -1)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(window_clear_obj, 1, 2, window_clear);

static mp_obj_t window_activate(mp_obj_t self) {
    check(kdm_window_activate(&state, win_arg(self)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(window_activate_obj, window_activate);

// close(): no CLOSE event is queued (the script asked for it). Closing a
// closed window does nothing.
static mp_obj_t window_close(mp_obj_t self) {
    handle_obj_t *h = MP_OBJ_TO_PTR(self);
    live_desktop(h->desk);
    if (kdm_window_check(&state, h->slot, h->serial) == KDM_OK) kdm_window_close(&state, h->slot);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(window_close_obj, window_close);

static mp_obj_t window_move(mp_obj_t self, mp_obj_t x, mp_obj_t y) {
    int slot = win_arg(self);
    check(kdm_window_move(&state, slot, i16(x), i16(y)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(window_move_obj, window_move);

static mp_obj_t window_set_title(mp_obj_t self, mp_obj_t title) {
    int slot = win_arg(self);
    size_t len;
    const char *t = mp_obj_str_get_data(title, &len);
    char buf[KD_TITLE_MAX];
    if (len >= sizeof buf) len = sizeof buf - 1;
    memcpy(buf, t, len);
    buf[len] = 0;
    check(kdm_window_set_title(&state, slot, buf));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(window_set_title_obj, window_set_title);

static bool handle_alive(handle_obj_t *h, bool sprite) {
    if (h->desk->generation != state.generation) return false;
    return (sprite ? kdm_sprite_check(&state, h->slot, h->serial) : kdm_window_check(&state, h->slot, h->serial)) == KDM_OK;
}

static mp_obj_t window_is_open(mp_obj_t self) { return mp_obj_new_bool(handle_alive(MP_OBJ_TO_PTR(self), false)); }
static MP_DEFINE_CONST_FUN_OBJ_1(window_is_open_obj, window_is_open);

static mp_obj_t window_is_active(mp_obj_t self) {
    handle_obj_t *h = MP_OBJ_TO_PTR(self);
    return mp_obj_new_bool(handle_alive(h, false) && kd_window_is_active(&state.desk.win[h->slot]));
}
static MP_DEFINE_CONST_FUN_OBJ_1(window_is_active_obj, window_is_active);

static mp_obj_t rect_tuple(kd_rect r) {
    mp_obj_t t[4] = {MP_OBJ_NEW_SMALL_INT(r.x), MP_OBJ_NEW_SMALL_INT(r.y), MP_OBJ_NEW_SMALL_INT(r.w),
                     MP_OBJ_NEW_SMALL_INT(r.h)};
    return mp_obj_new_tuple(4, t);
}

// work() -> (x, y, w, h) of the work area in screen coordinates.
static mp_obj_t window_work(mp_obj_t self) { return rect_tuple(kd_window_work(&state.desk.win[win_arg(self)])); }
static MP_DEFINE_CONST_FUN_OBJ_1(window_work_obj, window_work);

static mp_obj_t window_frame(mp_obj_t self) { return rect_tuple(kd_window_frame(&state.desk.win[win_arg(self)])); }
static MP_DEFINE_CONST_FUN_OBJ_1(window_frame_obj, window_frame);

static void handle_print(const mp_print_t *print, mp_obj_t self, mp_print_kind_t kind) {
    (void)kind;
    handle_obj_t *h = MP_OBJ_TO_PTR(self);
    bool sprite = mp_obj_is_type(self, &sprite_type);
    mp_printf(print, "<%s %d:%u%s>", sprite ? "Sprite" : "Window", h->slot, (unsigned)h->serial,
              handle_alive(h, sprite) ? "" : " closed");
}

// Handles are equal when they name the same native object.
static mp_obj_t handle_binary_op(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs) {
    if (op != MP_BINARY_OP_EQUAL) return MP_OBJ_NULL;
    if (!mp_obj_is_type(rhs, mp_obj_get_type(lhs))) return mp_const_false;
    handle_obj_t *a = MP_OBJ_TO_PTR(lhs), *b = MP_OBJ_TO_PTR(rhs);
    return mp_obj_new_bool(a->desk == b->desk && a->slot == b->slot && a->serial == b->serial);
}

static mp_obj_t handle_unary_op(mp_unary_op_t op, mp_obj_t self) {
    if (op != MP_UNARY_OP_HASH) return MP_OBJ_NULL;
    return MP_OBJ_NEW_SMALL_INT(((handle_obj_t *)MP_OBJ_TO_PTR(self))->serial & 0x3FFFFFFF);
}

static const mp_rom_map_elem_t window_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_fill_rect), MP_ROM_PTR(&window_fill_rect_obj)},
    {MP_ROM_QSTR(MP_QSTR_fill_rects), MP_ROM_PTR(&window_fill_rects_obj)},
    {MP_ROM_QSTR(MP_QSTR_rect), MP_ROM_PTR(&window_rect_obj)},
    {MP_ROM_QSTR(MP_QSTR_hline), MP_ROM_PTR(&window_hline_obj)},
    {MP_ROM_QSTR(MP_QSTR_vline), MP_ROM_PTR(&window_vline_obj)},
    {MP_ROM_QSTR(MP_QSTR_text), MP_ROM_PTR(&window_text_obj)},
    {MP_ROM_QSTR(MP_QSTR_button), MP_ROM_PTR(&window_button_obj)},
    {MP_ROM_QSTR(MP_QSTR_sprite), MP_ROM_PTR(&window_sprite_obj)},
    {MP_ROM_QSTR(MP_QSTR_icon), MP_ROM_PTR(&window_icon_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_text), MP_ROM_PTR(&window_set_text_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_color), MP_ROM_PTR(&window_set_color_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_flags), MP_ROM_PTR(&window_set_flags_obj)},
    {MP_ROM_QSTR(MP_QSTR_move_item), MP_ROM_PTR(&window_move_item_obj)},
    {MP_ROM_QSTR(MP_QSTR_remove), MP_ROM_PTR(&window_remove_obj)},
    {MP_ROM_QSTR(MP_QSTR_clear), MP_ROM_PTR(&window_clear_obj)},
    {MP_ROM_QSTR(MP_QSTR_activate), MP_ROM_PTR(&window_activate_obj)},
    {MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&window_close_obj)},
    {MP_ROM_QSTR(MP_QSTR_move), MP_ROM_PTR(&window_move_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_title), MP_ROM_PTR(&window_set_title_obj)},
    {MP_ROM_QSTR(MP_QSTR_is_open), MP_ROM_PTR(&window_is_open_obj)},
    {MP_ROM_QSTR(MP_QSTR_is_active), MP_ROM_PTR(&window_is_active_obj)},
    {MP_ROM_QSTR(MP_QSTR_work), MP_ROM_PTR(&window_work_obj)},
    {MP_ROM_QSTR(MP_QSTR_frame), MP_ROM_PTR(&window_frame_obj)},
};
static MP_DEFINE_CONST_DICT(window_locals, window_locals_table);

static MP_DEFINE_CONST_OBJ_TYPE(window_type, MP_QSTR_Window, MP_TYPE_FLAG_NONE, print, handle_print,
                                binary_op, handle_binary_op, unary_op, handle_unary_op, locals_dict, &window_locals);

// ---- Sprite ----

static mp_obj_t sprite_set(size_t n_args, const mp_obj_t *a) {
    int s = sprite_arg(a[0]);
    return mp_obj_new_bool(check(kdm_sprite_set(&state, s, i16(a[1]), i16(a[2]), i16(a[3]))));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(sprite_set_obj, 4, 4, sprite_set);

// set_pixels(buf): bytes of x, y, colour triples. Returns pixels changed.
static mp_obj_t sprite_set_pixels(mp_obj_t self, mp_obj_t buf) {
    int s = sprite_arg(self);
    mp_buffer_info_t bi;
    mp_get_buffer_raise(buf, &bi, MP_BUFFER_READ);
    if (bi.len % 3) raise_rc(KDM_EINVAL);
    return MP_OBJ_NEW_SMALL_INT(check(kdm_sprite_set_many(&state, s, bi.buf, (int)(bi.len / 3))));
}
static MP_DEFINE_CONST_FUN_OBJ_2(sprite_set_pixels_obj, sprite_set_pixels);

static mp_obj_t sprite_get(mp_obj_t self, mp_obj_t x, mp_obj_t y) {
    int s = sprite_arg(self);
    int v = kd_sprite_get(&state.sprites[s].px, i16(x), i16(y));
    if (v < 0) raise_rc(KDM_EINVAL);
    return MP_OBJ_NEW_SMALL_INT(v);
}
static MP_DEFINE_CONST_FUN_OBJ_3(sprite_get_obj, sprite_get);

static mp_obj_t sprite_fill(mp_obj_t self, mp_obj_t color) {
    int s = sprite_arg(self);
    return MP_OBJ_NEW_SMALL_INT(check(kdm_sprite_fill(&state, s, i16(color))));
}
static MP_DEFINE_CONST_FUN_OBJ_2(sprite_fill_obj, sprite_fill);

static mp_obj_t sprite_load(mp_obj_t self, mp_obj_t data) {
    int s = sprite_arg(self);
    uint8_t buf[KD_SPRITE_BYTES];
    sprite_bytes(data, buf);
    return MP_OBJ_NEW_SMALL_INT(check(kdm_sprite_load(&state, s, buf)));
}
static MP_DEFINE_CONST_FUN_OBJ_2(sprite_load_obj, sprite_load);

static mp_obj_t sprite_hex(mp_obj_t self) {
    int s = sprite_arg(self);
    char out[KD_SPRITE_HEX + 1];
    kd_sprite_export_hex(&state.sprites[s].px, out);
    return mp_obj_new_str(out, KD_SPRITE_HEX);
}
static MP_DEFINE_CONST_FUN_OBJ_1(sprite_hex_obj, sprite_hex);

static mp_obj_t sprite_data(mp_obj_t self) {
    int s = sprite_arg(self);
    return mp_obj_new_bytes(state.sprites[s].px.data, KD_SPRITE_BYTES);
}
static MP_DEFINE_CONST_FUN_OBJ_1(sprite_data_obj, sprite_data);

static mp_obj_t sprite_free(mp_obj_t self) {
    handle_obj_t *h = MP_OBJ_TO_PTR(self);
    live_desktop(h->desk);
    if (kdm_sprite_check(&state, h->slot, h->serial) == KDM_OK) kdm_sprite_free(&state, h->slot);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(sprite_free_obj, sprite_free);

static mp_obj_t sprite_is_alive(mp_obj_t self) { return mp_obj_new_bool(handle_alive(MP_OBJ_TO_PTR(self), true)); }
static MP_DEFINE_CONST_FUN_OBJ_1(sprite_is_alive_obj, sprite_is_alive);

static const mp_rom_map_elem_t sprite_locals_table[] = {
    {MP_ROM_QSTR(MP_QSTR_set), MP_ROM_PTR(&sprite_set_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_pixels), MP_ROM_PTR(&sprite_set_pixels_obj)},
    {MP_ROM_QSTR(MP_QSTR_get), MP_ROM_PTR(&sprite_get_obj)},
    {MP_ROM_QSTR(MP_QSTR_fill), MP_ROM_PTR(&sprite_fill_obj)},
    {MP_ROM_QSTR(MP_QSTR_load), MP_ROM_PTR(&sprite_load_obj)},
    {MP_ROM_QSTR(MP_QSTR_hex), MP_ROM_PTR(&sprite_hex_obj)},
    {MP_ROM_QSTR(MP_QSTR_data), MP_ROM_PTR(&sprite_data_obj)},
    {MP_ROM_QSTR(MP_QSTR_free), MP_ROM_PTR(&sprite_free_obj)},
    {MP_ROM_QSTR(MP_QSTR_is_alive), MP_ROM_PTR(&sprite_is_alive_obj)},
};
static MP_DEFINE_CONST_DICT(sprite_locals, sprite_locals_table);

static MP_DEFINE_CONST_OBJ_TYPE(sprite_type, MP_QSTR_Sprite, MP_TYPE_FLAG_NONE, print, handle_print,
                                binary_op, handle_binary_op, unary_op, handle_unary_op, locals_dict, &sprite_locals);

// ---- module ----

// sizes() -> dict of the static native allocation, in bytes.
static mp_obj_t mod_sizes(void) {
    mp_obj_t d = mp_obj_new_dict(10);
    put(d, MP_QSTR_total, sizeof state);
    put(d, MP_QSTR_desktop, sizeof state.desk);
    put(d, MP_QSTR_framebuffer, sizeof state.desk.fb.px);
    put(d, MP_QSTR_items, sizeof state.items);
    put(d, MP_QSTR_text, sizeof state.text);
    put(d, MP_QSTR_sprites, sizeof state.sprites);
    put(d, MP_QSTR_events, sizeof state.ring);
    put(d, MP_QSTR_menus, sizeof state.menus + sizeof state.menu_items + sizeof state.menu_text);
    put(d, MP_QSTR_staging, sizeof state.staging);
    put(d, MP_QSTR_max_items, KDM_MAX_ITEMS);
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_sizes_obj, mod_sizes);

static const mp_rom_obj_tuple_t icons_tuple = {
    {&mp_type_tuple}, 7,
    {MP_ROM_QSTR(MP_QSTR_folder), MP_ROM_QSTR(MP_QSTR_file), MP_ROM_QSTR(MP_QSTR_drive), MP_ROM_QSTR(MP_QSTR_trash),
     MP_ROM_QSTR(MP_QSTR_studio), MP_ROM_QSTR(MP_QSTR_app), MP_ROM_QSTR(MP_QSTR_text)},
};

#define CONST(name, value) {MP_ROM_QSTR(MP_QSTR_##name), MP_ROM_INT(value)}

static const mp_rom_map_elem_t module_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_kagura_desktop)},
    {MP_ROM_QSTR(MP_QSTR_Desktop), MP_ROM_PTR(&desktop_type)},
    {MP_ROM_QSTR(MP_QSTR_Window), MP_ROM_PTR(&window_type)},
    {MP_ROM_QSTR(MP_QSTR_Sprite), MP_ROM_PTR(&sprite_type)},
    {MP_ROM_QSTR(MP_QSTR_sizes), MP_ROM_PTR(&mod_sizes_obj)},
    {MP_ROM_QSTR(MP_QSTR_ICONS), MP_ROM_PTR(&icons_tuple)},
    CONST(POINTER_MOVE, KD_EV_POINTER_MOVE), CONST(POINTER_DOWN, KD_EV_POINTER_DOWN),
    CONST(POINTER_UP, KD_EV_POINTER_UP), CONST(KEY, KD_EV_KEY), CONST(FOCUS, KD_EV_FOCUS),
    CONST(BLUR, KD_EV_BLUR), CONST(CLOSE, KDM_EV_CLOSE), CONST(MENU, KDM_EV_MENU),
    CONST(KEY_CHAR, KD_KEY_CHAR), CONST(KEY_UP, KD_KEY_UP), CONST(KEY_DOWN, KD_KEY_DOWN),
    CONST(KEY_LEFT, KD_KEY_LEFT), CONST(KEY_RIGHT, KD_KEY_RIGHT), CONST(KEY_ENTER, KD_KEY_ENTER),
    CONST(KEY_ESCAPE, KD_KEY_ESCAPE), CONST(KEY_TAB, KD_KEY_TAB), CONST(KEY_BACKSPACE, KD_KEY_BACKSPACE),
    CONST(KEY_DELETE, KD_KEY_DELETE), CONST(KEY_HOME, KD_KEY_HOME), CONST(KEY_END, KD_KEY_END),
    CONST(KEY_F6, KD_KEY_F6), CONST(KEY_F10, KD_KEY_F10),
    CONST(MOD_SHIFT, KD_MOD_SHIFT), CONST(MOD_CTRL, KD_MOD_CTRL), CONST(MOD_ALT, KD_MOD_ALT),
    CONST(BTN_DEFAULT, KD_BTN_DEFAULT), CONST(BTN_PRESSED, KD_BTN_PRESSED), CONST(BTN_FOCUS, KD_BTN_FOCUS),
    CONST(BTN_DISABLED, KD_BTN_DISABLED),
};
static MP_DEFINE_CONST_DICT(module_globals, module_table);

const mp_obj_module_t kagura_desktop_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_kagura_desktop, kagura_desktop_module);
