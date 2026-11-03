// SPDX-License-Identifier: Apache-2.0
// Retained-mode layer between the C desktop (kd_app.h) and a script binding.
//
// A script cannot draw into a window on its own schedule: the compositor asks
// windows to draw any visible sub-rectangle at any time. kdm therefore keeps
// each window's content as a display list of records in fixed pools, and its
// window class replays that list when the compositor asks. Window events are
// copied into a fixed ring, together with window-manager outcomes (close box,
// menu choices), for the script to poll. Nothing here calls the script.
//
// Handles: windows and sprites are (slot, serial); a record is
// index | serial << KDM_ITEM_BITS. A handle whose serial no longer matches is
// stale and every call rejects it with KDM_ESTALE.
//
// Errors are atomic: a call that returns an error has changed nothing.
// No allocation, no globals; all state lives in the caller's kdm.
//
// Keyboard (Phase 4). Each window has at most one focused control: an
// editable field, or a button made focusable. Keys reach a window only after
// the desktop's own keys (open menu, F10, F6/Ctrl+Tab, Ctrl+W, Ctrl+arrows on
// movable windows; see kd_desktop.c). Then, in this order:
//   1. Tab / Shift+Tab move the focus through the window's focusable
//      controls in display-list order, wrapping. Without any, Tab is queued.
//   2. A focused field consumes printable ASCII, Backspace, Delete, Left,
//      Right, Home, End (Shift extends the selection), Ctrl+A (select all),
//      Ctrl+Insert (copy), Shift+Insert (paste), Shift+Delete (cut).
//      Ctrl+C stays MicroPython's interrupt and is never an editing key.
//      The editor (multiline) also takes Enter (a line break), Up, Down,
//      PgUp, PgDn (Shift selects) and Ctrl+Home / Ctrl+End.
//   3. A focused button consumes Enter and Space and queues KDM_EV_ACTIVATE.
//   4. Enter not consumed above activates the window's focusable default
//      button (KD_BTN_DEFAULT), if any.
//   5. Everything else is queued as before (Escape, Up, Down, F keys, ...).
// A window without focusable controls therefore behaves exactly as before.
// Non-ASCII text enters through kdm_text_input (UTF-8), never through the
// one-byte kd_event.ch. Edits by keys queue KDM_EV_CHANGE; API calls do not.
#ifndef KDM_H
#define KDM_H

#include <stddef.h>

#include "kd_desktop.h"
#include "kd_edit.h"
#include "kd_tile4.h"

#ifndef KDM_MAX_ITEMS
#define KDM_MAX_ITEMS 320          // display records, all windows together
#endif
#ifndef KDM_TEXT_BYTES
#define KDM_TEXT_BYTES 2048        // text arena (record strings, NUL included)
#endif
#ifndef KDM_MAX_SPRITES
#define KDM_MAX_SPRITES 8
#endif
#ifndef KDM_EVENTS
#define KDM_EVENTS 32
#endif
#define KDM_MENUS 4
#define KDM_MENU_ITEMS 8
#define KDM_MENU_TEXT 256
#define KDM_TEXT_MAX 63            // characters per record
#define KDM_ITEM_BITS 9
#define KDM_NONE 0xFFFFu
#ifndef KDM_FIELDS
#define KDM_FIELDS 8               // editable fields, all windows together
#endif
#define KDM_FIELD_BYTES 64         // field text with its NUL: 63 bytes
#define KDM_FIELD_H 12             // field height: border, padding, 8 px text
#ifndef KDM_DOC_BYTES
#define KDM_DOC_BYTES 8192         // the editor's document with its NUL: 8,191 bytes
#endif
#define KDM_LINE_H 10              // editor line pitch: 8 px text, 1 px above and below
#ifndef KDM_CLIP_BYTES
#define KDM_CLIP_BYTES 256         // clipboard, NUL included
#endif

#if KDM_MAX_ITEMS > (1 << KDM_ITEM_BITS) || KDM_TEXT_BYTES > 0xFFFF || KDM_DOC_BYTES > 0xFFFF
#error "kdm pool sizes out of range"
#endif

enum {
    KDM_OK = 0,
    KDM_ESTALE = -1,      // closed window, freed sprite, removed record, old desktop
    KDM_EINVAL = -2,      // bad argument
    KDM_ENOITEM = -3,     // record pool full
    KDM_ENOTEXT = -4,     // text arena full
    KDM_ENOWIN = -5,      // all window slots in use
    KDM_ENOSPRITE = -6,   // sprite pool full
    KDM_ENOMENU = -7,     // menu definition too large
    KDM_ESINK = -8,       // present: the sink refused a run
    KDM_ETOOLONG = -9,    // text longer than the field or clipboard holds
    KDM_ENOFIELD = -10,   // field pool full
    KDM_ENONE = -11,      // nothing focused
};

// Events added by kdm to the KD_EV_* set.
// CHANGE: a key edited a field; ACTIVATE: a button was pressed by key.
// Both carry the record id in ev.reserved.
enum { KDM_EV_CLOSE = 16, KDM_EV_MENU = 17, KDM_EV_CHANGE = 18, KDM_EV_ACTIVATE = 19 };

enum { KDM_EDIT_COPY, KDM_EDIT_CUT, KDM_EDIT_PASTE, KDM_EDIT_SELECT_ALL };

enum {
    KDM_OP_FREE, KDM_OP_FILL, KDM_OP_RECT, KDM_OP_HLINE, KDM_OP_VLINE,
    KDM_OP_TEXT, KDM_OP_TEXT_SMALL, KDM_OP_BUTTON, KDM_OP_SPRITE, KDM_OP_ICON,
    KDM_OP_FIELD, KDM_OP_EDITOR,
};

#define KDM_NO_BG 0xFF   // text: transparent background; sprite: no key

typedef struct {
    uint8_t op;          // KDM_OP_*
    uint8_t win;         // window slot
    uint8_t c0, c1;      // see kdm_add_*: colours, font, flags, zoom, key
    int16_t x, y, w, h;  // bounding box in work-area coordinates
    uint16_t next;       // next record of the window, KDM_NONE at the end
    uint16_t aux;        // text arena offset, sprite slot or art index
    uint16_t serial;
} kdm_item;

typedef struct {
    uint32_t serial;     // 0: slot unused
    uint16_t head, tail; // display list, drawing order
    uint16_t focus;      // focused record, KDM_NONE if none
    uint8_t bg;
    bool open;
} kdm_window;

typedef struct {
    kd_sprite px;
    uint32_t serial;
    bool used;
} kdm_sprite;

typedef struct {
    kd_event ev;         // work-area coordinates for window events
    uint32_t serial;     // window serial at the time of the event (0: none)
    int8_t win;          // window slot, -1 for desktop events (menus)
} kdm_event;

// An editable field, or the multiline editor (pool slot KDM_FIELDS, whose
// text is kdm.doc); the record's aux is the pool index.
typedef struct {
    kd_edit ed;          // text points into text[] below (static state)
    uint16_t item;       // owning record, KDM_NONE: free
    int16_t scroll;      // pixels of text hidden on the left
    uint16_t top;        // editor: first visible line
    uint16_t top_off;    // editor: its byte offset
    uint16_t lines;      // editor: logical lines (LF count + 1)
    uint8_t text[KDM_FIELD_BYTES];
} kdm_field;

typedef struct {
    uint32_t dropped;           // events lost because the ring was full
    uint32_t compactions;       // text arena compactions
    uint16_t items, items_peak; // records in use
    uint16_t text, text_peak;   // live text bytes
    uint32_t presents, tiles, runs;
} kdm_stats;

typedef struct kdm {
    kd_desktop desk;
    uint32_t generation;        // incremented by every kdm_init
    uint32_t next_serial;       // windows and sprites
    uint16_t item_serial;
    kdm_window win[KD_MAX_WINDOWS];
    kdm_item items[KDM_MAX_ITEMS];
    uint16_t free_item;         // free list through next
    uint16_t text_top;          // arena allocation pointer
    char text[KDM_TEXT_BYTES];
    kdm_sprite sprites[KDM_MAX_SPRITES];
    kdm_field fields[KDM_FIELDS + 1];  // the last one is the editor's
    uint8_t doc[KDM_DOC_BYTES];       // the editor's document
    char clip[KDM_CLIP_BYTES];  // clipboard, NUL-terminated UTF-8
    uint16_t clip_len;
    kdm_event ring[KDM_EVENTS];
    uint8_t ring_head, ring_count;
    int8_t api_closing;         // slot being closed by kdm_window_close
    kd_menu menus[KDM_MENUS + 1];
    kd_menu_item menu_items[KDM_MENUS][KDM_MENU_ITEMS + 1];
    char menu_text[KDM_MENU_TEXT];
    kdm_stats stats;
    uint8_t staging[KD_TILE_COLS * KD_TILE4_BYTES];
} kdm;

// Menu definition: titles[i] with items[i][0..counts[i]-1] ("-" separator).
typedef struct {
    int count;
    const char *titles[KDM_MENUS];
    const char *items[KDM_MENUS][KDM_MENU_ITEMS];
    int counts[KDM_MENUS];
} kdm_menu_def;

// Resets everything (all earlier handles become stale). menus may be NULL.
int kdm_init(kdm *m, const kdm_menu_def *menus);

// Windows. Frame rect as kd_window_open. Returns the slot or an error.
int kdm_window_open(kdm *m, const char *title, kd_rect frame, unsigned flags, uint8_t bg);
int kdm_window_check(const kdm *m, int slot, uint32_t serial);
int kdm_window_close(kdm *m, int slot);
int kdm_window_activate(kdm *m, int slot);
int kdm_window_move(kdm *m, int slot, int x, int y);
int kdm_window_set_title(kdm *m, int slot, const char *title);
int kdm_window_clear(kdm *m, int slot, int bg);   // bg < 0 keeps the colour
kd_window *kdm_window_core(kdm *m, int slot);

// Records. Return the record id (>= 0) or an error.
int kdm_add_fill(kdm *m, int slot, int x, int y, int w, int h, uint8_t color);
int kdm_add_rect(kdm *m, int slot, int x, int y, int w, int h, uint8_t color);
int kdm_add_hline(kdm *m, int slot, int x, int y, int w, uint8_t color);
int kdm_add_vline(kdm *m, int slot, int x, int y, int h, uint8_t color);
// font 0: system 8x8, 1: small 4x8. bg < 0: transparent.
int kdm_add_text(kdm *m, int slot, int x, int y, const char *s, size_t len, uint8_t fg, int bg, int font);
int kdm_add_button(kdm *m, int slot, int x, int y, int w, int h, const char *label, size_t len, unsigned flags);
// zoom 1..16; key < 0 draws colour 0 opaquely, else pixels equal to key are skipped.
int kdm_add_sprite(kdm *m, int slot, int x, int y, int sprite, int zoom, int key);
// art: index into kdm_icon_names.
int kdm_add_icon(kdm *m, int slot, int x, int y, int art, const char *label, size_t len, bool selected);
// n rectangles (x, y, w, h quads); all or none are added. Returns n or an error.
int kdm_add_fills(kdm *m, int slot, const int16_t *xywh, int n, uint8_t color);
int kdm_item_set_text(kdm *m, int slot, int id, const char *s, size_t len);
int kdm_item_set_color(kdm *m, int slot, int id, uint8_t color);
int kdm_item_set_flags(kdm *m, int slot, int id, unsigned flags);
int kdm_item_move(kdm *m, int slot, int id, int x, int y);
int kdm_item_remove(kdm *m, int slot, int id);

// Fields and focus. font 0: system 8x8, 1: small 4x8 ASCII. Height KDM_FIELD_H.
// The first focusable control added to a window takes the focus.
int kdm_add_field(kdm *m, int slot, int x, int y, int w, const char *s, size_t len, int font);
// The multiline editor: one per desktop (KDM_ENOFIELD if it exists), its text in
// kdm.doc (KDM_DOC_BYTES - 1 bytes). Lines are not wrapped: the view scrolls
// both ways to keep the caret visible. Line pitch KDM_LINE_H; h >= 16.
int kdm_add_editor(kdm *m, int slot, int x, int y, int w, int h, const char *s, size_t len, int font);
// Text of a field or text record; valid until the next change of the record.
int kdm_item_get_text(kdm *m, int slot, int id, const char **s, size_t *len);
const kd_edit *kdm_field_editor(kdm *m, int slot, int id);   // NULL: not a live field
int kdm_field_select(kdm *m, int slot, int id, size_t anchor, size_t caret);   // byte offsets
int kdm_item_set_focusable(kdm *m, int slot, int id, bool on);   // buttons
int kdm_focus(kdm *m, int slot, int id);      // id < 0: no focus
int kdm_focused(const kdm *m, int slot);      // record id or KDM_ENONE
// KDM_EDIT_*: returns 1 when the text, selection or clipboard changed.
int kdm_edit(kdm *m, int slot, int id, int cmd);
// UTF-8 text for the focused field of the top window (menus closed). Returns
// 1 when inserted, 0 when no field has the focus, KDM_ETOOLONG when it does
// not fit, KDM_EINVAL for invalid UTF-8 or a line break. Queues KDM_EV_CHANGE.
int kdm_text_input(kdm *m, const char *s, size_t len);
int kdm_set_clipboard(kdm *m, const char *s, size_t len);

extern const char *const kdm_icon_names[];
int kdm_icon_lookup(const char *name, size_t len);

// Sprites. Returns the slot; m->sprites[slot].serial is the handle serial.
int kdm_sprite_alloc(kdm *m, const uint8_t *data);   // data: 128 B TILE4 or NULL (zero)
int kdm_sprite_check(const kdm *m, int s, uint32_t serial);
int kdm_sprite_free(kdm *m, int s);                  // also removes its records
int kdm_sprite_set(kdm *m, int s, int x, int y, int color);   // 1 changed, 0 not
int kdm_sprite_set_many(kdm *m, int s, const uint8_t *xyc, int n);   // pixels changed
int kdm_sprite_load(kdm *m, int s, const uint8_t data[KD_SPRITE_BYTES]);   // pixels changed
int kdm_sprite_fill(kdm *m, int s, int color);

// Input and events.
void kdm_feed(kdm *m, const kd_event *ev);
bool kdm_peek(const kdm *m, kdm_event *out);
void kdm_drop(kdm *m);    // removes the event kdm_peek returned

// Composition and export. sink may be NULL (tiles are marked exported).
bool kdm_render(kdm *m);
int kdm_present(kdm *m, kd_tile4_sink sink, void *ctx, kd_tile4_stats *st);
// As kdm_present; clean gaps of at most max_gap tiles between dirty runs are sent
// too, so a transport with a high cost per run makes fewer, longer transfers.
int kdm_present_gap(kdm *m, unsigned max_gap, kd_tile4_sink sink, void *ctx, kd_tile4_stats *st);

uint32_t kdm_crc32(uint32_t crc, const uint8_t *p, size_t n);

#endif
