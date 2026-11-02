// SPDX-License-Identifier: Apache-2.0
#include "kd_gfx.h"

#include <string.h>

// Flat 16-colour palette in the spirit of the Atari ST desktop: green desk,
// black on white chrome, saturated accents for icons and the sprite editor.
const uint16_t kd_palette_rgb444[16] = {
    0x0A5, 0x000, 0xFFF, 0xBBB, 0x666, 0x23C, 0xD22, 0xEC2,
    0x063, 0x2BC, 0xC4C, 0x842, 0x8AF, 0x8E8, 0xF82, 0xFFC,
};

#define ART(name, w, h, ...)                                  \
    static const char *const name##_rows[h] = {__VA_ARGS__}; \
    const kd_art name = {w, h, name##_rows}

ART(kd_art_cursor, 11, 16,
    "-          ",
    "--         ",
    "-#-        ",
    "-##-       ",
    "-###-      ",
    "-####-     ",
    "-#####-    ",
    "-######-   ",
    "-#######-  ",
    "-########- ",
    "-#####-----",
    "-##-##-    ",
    "-#- -##-   ",
    "--  -##-   ",
    "     -##-  ",
    "      --   ");

ART(kd_art_folder, 16, 16,
    "                ",
    "                ",
    "  #####         ",
    " #-----#        ",
    "#-------####### ",
    "#-------------# ",
    "###############-",
    "#-------------#-",
    "#-------------#-",
    "#-------------#-",
    "#-------------#-",
    "#-------------#-",
    "#-------------#-",
    "###############-",
    " ---------------",
    "                ");

ART(kd_art_file, 16, 16,
    "  ########      ",
    "  #------##     ",
    "  #------#-#    ",
    "  #------#--#   ",
    "  #------####   ",
    "  #---------#   ",
    "  #-#####---#   ",
    "  #---------#   ",
    "  #-######--#   ",
    "  #---------#   ",
    "  #-####----#   ",
    "  #---------#   ",
    "  #-######--#   ",
    "  #---------#   ",
    "  ###########   ",
    "                ");

ART(kd_art_text, 16, 16,
    "  ########      ",
    "  #------##     ",
    "  #-##---#-#    ",
    "  #------#--#   ",
    "  #-###--####   ",
    "  #---------#   ",
    "  #-#######-#   ",
    "  #-#######-#   ",
    "  #---------#   ",
    "  #-#######-#   ",
    "  #-#####---#   ",
    "  #---------#   ",
    "  #-######--#   ",
    "  #---------#   ",
    "  ###########   ",
    "                ");

ART(kd_art_app, 16, 16,
    "                ",
    " ############## ",
    " #-#-########-# ",
    " #-#-########-# ",
    " ############## ",
    " #------------# ",
    " #-######-----# ",
    " #------------# ",
    " #-########---# ",
    " #------------# ",
    " #-#####------# ",
    " #------------# ",
    " ############## ",
    "                ",
    "                ",
    "                ");

ART(kd_art_drive, 16, 16,
    "                ",
    " ############## ",
    " #--#######---# ",
    " #--#--####-#-# ",
    " #--#--####-#-# ",
    " #--#######---# ",
    " #------------# ",
    " #-##########-# ",
    " #-#--------#-# ",
    " #-#-######-#-# ",
    " #-#--------#-# ",
    " #-#-####---#-# ",
    " #-#--------#-# ",
    " ############## ",
    "                ",
    "                ");

ART(kd_art_trash, 16, 16,
    "      ####      ",
    "  ####----####  ",
    "  #----------#  ",
    "  ############  ",
    "   #--------#   ",
    "   #-#-##-#-#   ",
    "   #-#-##-#-#   ",
    "   #-#-##-#-#   ",
    "   #-#-##-#-#   ",
    "   #-#-##-#-#   ",
    "   #-#-##-#-#   ",
    "   #-#-##-#-#   ",
    "   #--------#   ",
    "   ##########   ",
    "                ",
    "                ");

ART(kd_art_studio, 16, 16,
    "     ######     ",
    "   ##------##   ",
    "  #-GG--HH---#  ",
    " #--GG--HH----# ",
    " #----------JJ# ",
    "#-FF-----#--JJ-#",
    "#-FF----###----#",
    "#-------###----#",
    " #-NN----#----# ",
    " #-NN--KK-----# ",
    "  #----KK---##  ",
    "   ##------#    ",
    "     ######     ",
    "                ",
    "                ",
    "                ");

static const char *const check_rows[6] = {
    "      #", "     ##", "#   ## ", "## ##  ", " ###   ", "  #    ",
};
static const kd_art check_art = {7, 6, check_rows};

void kd_gfx_art(kd_fb *fb, int x, int y, const kd_art *a, uint8_t ink, uint8_t paper) {
    kd_rect box = kd_rect_intersect(kd_rect_make(x, y, a->w, a->h), fb->clip);
    if (kd_rect_empty(box)) return;
    for (int yy = box.y; yy < box.y + box.h; yy++) {
        const char *row = a->rows[yy - y];
        for (int xx = box.x; xx < box.x + box.w; xx++) {
            char c = row[xx - x];
            if (c == '#') kd_fb_pixel(fb, xx, yy, ink);
            else if (c == '-') kd_fb_pixel(fb, xx, yy, paper);
            else if (c >= 'A' && c <= 'P') kd_fb_pixel(fb, xx, yy, (uint8_t)(c - 'A'));
        }
    }
}

void kd_gfx_desktop(kd_fb *fb, kd_rect area) {
    kd_fb_fill_rect(fb, area.x, area.y, area.w, area.h, KD_C_DESK);
}

static int title_w(const kd_menu *menus, int index) {
    return kd_text_width(&kd_font_system, menus[index].title);
}

int kd_menu_title_x(const kd_menu *menus, int index) {
    int x = 8;
    for (int i = 0; i < index; i++) x += title_w(menus, i) + 16;
    return x;
}

int kd_menu_title_w(const kd_menu *menus, int index) { return title_w(menus, index); }

int kd_menu_item_count(const kd_menu *m) {
    int n = 0;
    while (m->items[n].label) n++;
    return n;
}

kd_rect kd_menu_dropdown_rect(const kd_menu *menus, int index) {
    const kd_menu *m = &menus[index];
    int longest = 0, n = kd_menu_item_count(m);
    for (int i = 0; i < n; i++) {
        int len = kd_text_width(&kd_font_system, m->items[i].label);
        if (len > longest) longest = len;
    }
    int w = longest + 16 + 2 + 1;           // text, margins, border, shadow
    int h = n * KD_MENU_ITEM_H + 2 + 1;
    int x = kd_menu_title_x(menus, index) - 4;
    if (x + w > KD_W) x = KD_W - w;
    return kd_rect_make(x, KD_MENU_H - 1, w, h);
}

void kd_gfx_menubar(kd_fb *fb, const kd_menu *menus, int open) {
    kd_fb_fill_rect(fb, 0, 0, KD_W, KD_MENU_H - 1, KD_C_WHITE);
    kd_fb_hline(fb, 0, KD_MENU_H - 1, KD_W, KD_C_BLACK);
    for (int i = 0; menus[i].title; i++) {
        int x = kd_menu_title_x(menus, i), w = kd_menu_title_w(menus, i);
        bool hot = i == open;
        if (hot) kd_fb_fill_rect(fb, x - 4, 0, w + 8, KD_MENU_H - 1, KD_C_BLACK);
        kd_text(fb, &kd_font_system, x, 1, menus[i].title, hot ? KD_C_WHITE : KD_C_BLACK, KD_NO_KEY);
    }
}

void kd_gfx_dropdown(kd_fb *fb, const kd_menu *menus, int open, int hot) {
    if (open < 0) return;
    const kd_menu *m = &menus[open];
    kd_rect r = kd_menu_dropdown_rect(menus, open);
    int bw = r.w - 1, bh = r.h - 1;
    kd_fb_fill_rect(fb, r.x + 1, r.y + 1, bw - 2, bh - 2, KD_C_WHITE);
    kd_fb_rect(fb, r.x, r.y, bw, bh, KD_C_BLACK);
    // Layers must be opaque over their whole rect, so the shadow covers the
    // full right column and bottom row (no see-through corners).
    kd_fb_vline(fb, r.x + bw, r.y, bh + 1, KD_C_BLACK);
    kd_fb_hline(fb, r.x, r.y + bh, bw, KD_C_BLACK);
    for (int i = 0; m->items[i].label; i++) {
        const kd_menu_item *it = &m->items[i];
        int y = r.y + 1 + i * KD_MENU_ITEM_H;
        if (strcmp(it->label, "-") == 0) {
            static const uint8_t dots[8] = {0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55};
            kd_fb_pattern_rect(fb, r.x + 1, y + KD_MENU_ITEM_H / 2, bw - 2, 1, dots, KD_C_WHITE, KD_C_DGREY);
            continue;
        }
        bool lit = i == hot && !it->disabled;
        if (lit) kd_fb_fill_rect(fb, r.x + 1, y, bw - 2, KD_MENU_ITEM_H, KD_C_BLACK);
        uint8_t fg = it->disabled ? KD_C_DGREY : lit ? KD_C_WHITE : KD_C_BLACK;
        if (it->checked) kd_gfx_art(fb, r.x + 1, y + 2, &check_art, fg, fg);
        kd_text(fb, &kd_font_system, r.x + 9, y + 1, it->label, fg, KD_NO_KEY);
    }
}

kd_rect kd_frame_title(kd_rect f) { return kd_rect_make(f.x + 1, f.y + 1, f.w - 2, KD_TITLE_H - 1); }
kd_rect kd_frame_close(kd_rect f) { return kd_rect_make(f.x + 1, f.y + 1, KD_CLOSE_W - 1, KD_TITLE_H - 1); }
kd_rect kd_frame_work(kd_rect f) {
    return kd_rect_make(f.x + 1, f.y + KD_TITLE_H + 1, f.w - 2, f.h - KD_TITLE_H - 2);
}

void kd_gfx_frame(kd_fb *fb, kd_rect f, const char *title, bool active, bool closable) {
    static const uint8_t stripes[8] = {0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00};
    kd_fb_rect(fb, f.x, f.y, f.w, f.h, KD_C_BLACK);
    kd_fb_hline(fb, f.x + 1, f.y + KD_TITLE_H, f.w - 2, KD_C_BLACK);
    kd_rect t = kd_frame_title(f);
    int left = t.x;
    if (closable) {
        kd_rect c = kd_frame_close(f);
        kd_fb_fill_rect(fb, c.x, c.y, c.w, c.h, KD_C_WHITE);
        kd_fb_rect(fb, c.x + 2, c.y + 2, c.w - 4, c.h - 4, KD_C_BLACK);
        kd_fb_vline(fb, c.x + c.w, c.y, c.h, KD_C_BLACK);
        left = c.x + c.w + 1;
    }
    int avail = t.x + t.w - left;
    if (avail <= 0) return;
    kd_fb_fill_rect(fb, left, t.y, avail, t.h, KD_C_WHITE);
    // Rows y+2, y+4 .. y+8 are black: the GEM "lines" of an active window.
    if (active) kd_fb_pattern_rect(fb, left + 1, t.y + 1, avail - 2, t.h - 2, stripes, KD_C_WHITE, KD_C_BLACK);
    int tw, n = kd_text_fit(&kd_font_system, title, avail - 8, &tw);
    if (n == 0) return;
    int tx = left + (avail - tw) / 2;
    kd_fb_fill_rect(fb, tx - 4, t.y, tw + 8, t.h, KD_C_WHITE);
    kd_text_n(fb, &kd_font_system, tx, t.y + 1, title, n, active ? KD_C_BLACK : KD_C_DGREY, KD_NO_KEY);
}

void kd_gfx_outline(kd_fb *fb, kd_rect r) {
    static const uint8_t checker[8] = {0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55};
    if (kd_rect_empty(r)) return;
    kd_fb_pattern_rect(fb, r.x, r.y, r.w, 1, checker, KD_C_WHITE, KD_C_BLACK);
    kd_fb_pattern_rect(fb, r.x, r.y + r.h - 1, r.w, 1, checker, KD_C_WHITE, KD_C_BLACK);
    kd_fb_pattern_rect(fb, r.x, r.y + 1, 1, r.h - 2, checker, KD_C_WHITE, KD_C_BLACK);
    kd_fb_pattern_rect(fb, r.x + r.w - 1, r.y + 1, 1, r.h - 2, checker, KD_C_WHITE, KD_C_BLACK);
}

void kd_gfx_button(kd_fb *fb, kd_rect r, const char *label, unsigned flags) {
    static const uint8_t dots[8] = {0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55};
    bool pressed = flags & KD_BTN_PRESSED;
    kd_fb_fill_rect(fb, r.x, r.y, r.w, r.h, pressed ? KD_C_BLACK : KD_C_WHITE);
    kd_fb_rect(fb, r.x, r.y, r.w, r.h, KD_C_BLACK);
    int inset = 2;
    if (flags & KD_BTN_DEFAULT) {
        kd_fb_rect(fb, r.x + 1, r.y + 1, r.w - 2, r.h - 2, KD_C_BLACK);
        inset = 3;
    }
    if (flags & KD_BTN_FOCUS) {
        kd_rect f = kd_rect_make(r.x + inset, r.y + inset, r.w - 2 * inset, r.h - 2 * inset);
        uint8_t c0 = pressed ? KD_C_BLACK : KD_C_WHITE, c1 = pressed ? KD_C_WHITE : KD_C_DGREY;
        kd_fb_pattern_rect(fb, f.x, f.y, f.w, 1, dots, c0, c1);
        kd_fb_pattern_rect(fb, f.x, f.y + f.h - 1, f.w, 1, dots, c0, c1);
        kd_fb_pattern_rect(fb, f.x, f.y, 1, f.h, dots, c0, c1);
        kd_fb_pattern_rect(fb, f.x + f.w - 1, f.y, 1, f.h, dots, c0, c1);
    }
    uint8_t fg = (flags & KD_BTN_DISABLED) ? KD_C_DGREY : pressed ? KD_C_WHITE : KD_C_BLACK;
    int tw = kd_text_width(&kd_font_system, label);
    kd_text(fb, &kd_font_system, r.x + (r.w - tw) / 2, r.y + (r.h - 8) / 2, label, fg, KD_NO_KEY);
}

kd_rect kd_icon_box(int x, int y, const char *label) {
    int lw = kd_text_width(&kd_font_small, label) + 2;
    int lx = x + KD_ICON_W / 2 - lw / 2;
    kd_rect icon = kd_rect_make(x, y, KD_ICON_W, KD_ICON_H);
    return kd_rect_union(icon, kd_rect_make(lx, y + KD_ICON_H + 1, lw, 9));
}

void kd_gfx_icon(kd_fb *fb, int x, int y, const kd_art *a, const char *label, bool selected) {
    kd_gfx_art(fb, x, y, a, selected ? KD_C_WHITE : KD_C_BLACK, selected ? KD_C_BLACK : KD_C_WHITE);
    int lw = kd_text_width(&kd_font_small, label) + 2;
    int lx = x + KD_ICON_W / 2 - lw / 2, ly = y + KD_ICON_H + 1;
    kd_fb_fill_rect(fb, lx, ly, lw, 9, selected ? KD_C_BLACK : KD_C_WHITE);
    kd_text(fb, &kd_font_small, lx + 1, ly + 1, label, selected ? KD_C_WHITE : KD_C_BLACK, KD_NO_KEY);
}
