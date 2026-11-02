// SPDX-License-Identifier: Apache-2.0
// Interactive SDL2 host. All SDL use is in this file; the desktop core only
// sees kd_event values and exports TILE4 patterns.
//
// The window shows a RAM "VRAM" copy filled exclusively through the TILE4
// export (kd_tile4_flush), decoded per tile the way KAGURA-9 would read its
// patterns, so what you see has gone through the hardware data path.
//
//   kd_desktop [--scale N] [--kagura240] [--outline] [--smoke FILE]
//   F12 writes kd-screenshot-N.png; Options > Show dirty tiles flashes exports.
//
// --smoke pushes a fixed sequence of SDL mouse/keyboard events through the
// normal event loop, reads the presented frame back from the renderer, writes
// it to FILE and exits non-zero unless it equals the desktop framebuffer and
// the events had their expected effect. Works with SDL_VIDEODRIVER=offscreen.
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "image.h"
#include "kd_shell.h"
#include "kd_tile4.h"

static kd_shell S;
static uint8_t vram[KD_TILE4_TOTAL];
static uint8_t staging[KD_TILE_COLS * KD_TILE4_BYTES];
static uint8_t flash[KD_TILES];       // frames left to highlight each exported tile
static uint32_t argb[KD_W * KD_H];
static uint32_t pal[16];
static Uint32 window_id;   // injected mouse events need it for logical scaling

static bool to_vram(void *ctx, unsigned first, unsigned count, const uint8_t *data) {
    (void)ctx;
    memcpy(vram + first * KD_TILE4_BYTES, data, count * KD_TILE4_BYTES);
    for (unsigned t = first; t < first + count; t++) {
        flash[t] = 12;
        const uint8_t *p = vram + t * KD_TILE4_BYTES;
        int x0 = (int)(t % KD_TILE_COLS) * 8, y0 = (int)(t / KD_TILE_COLS) * 8;
        for (int y = 0; y < 8; y++)
            for (int x = 0; x < 8; x++) {
                uint8_t b = p[y * 4 + x / 2];
                argb[(y0 + y) * KD_W + x0 + x] = pal[(x & 1) ? (b & 15) : (b >> 4)];
            }
    }
    return true;
}

static void post(uint8_t type, int x, int y, uint8_t button, uint8_t key, char ch, uint8_t mods) {
    kd_event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.button = button;
    e.key = key;
    e.ch = ch;
    e.mods = mods;
    e.x = (int16_t)(x < 0 ? 0 : x >= KD_W ? KD_W - 1 : x);
    e.y = (int16_t)(y < 0 ? 0 : y >= KD_H ? KD_H - 1 : y);
    e.time_ms = SDL_GetTicks();
    kd_desktop_event(&S.desk, &e);
}

static uint8_t mods_now(void) {
    SDL_Keymod m = SDL_GetModState();
    return (uint8_t)(((m & KMOD_SHIFT) ? KD_MOD_SHIFT : 0) | ((m & KMOD_CTRL) ? KD_MOD_CTRL : 0) |
                     ((m & KMOD_ALT) ? KD_MOD_ALT : 0));
}

static void push_mouse(Uint32 type, int x, int y, int scale, int top) {
    SDL_Event e;
    memset(&e, 0, sizeof e);
    e.type = type;
    e.motion.windowID = window_id;   // same offset in the button struct
    if (type == SDL_MOUSEMOTION) {
        e.motion.x = x * scale;
        e.motion.y = (y + top) * scale;
    } else {
        e.button.windowID = window_id;
        e.button.button = SDL_BUTTON_LEFT;
        e.button.state = type == SDL_MOUSEBUTTONDOWN ? SDL_PRESSED : SDL_RELEASED;
        e.button.x = x * scale;
        e.button.y = (y + top) * scale;
    }
    SDL_PushEvent(&e);
}

static void push_key(SDL_Keycode k) {
    SDL_Event e;
    memset(&e, 0, sizeof e);
    e.type = SDL_KEYDOWN;
    e.key.keysym.sym = k;
    SDL_PushEvent(&e);
}

static void push_text(const char *s) {
    SDL_Event e;
    memset(&e, 0, sizeof e);
    e.type = SDL_TEXTINPUT;
    snprintf(e.text.text, sizeof e.text.text, "%s", s);
    SDL_PushEvent(&e);
}

// Studio is on top in the demo scene: paint cell (2,3) with colour 7 by
// keyboard, cell (6,1) with the mouse, open and close the File menu.
static void push_smoke(int scale, int top) {
    kd_rect work = kd_window_work(S.studio.win);
    push_mouse(SDL_MOUSEMOTION, 200, 150, scale, top);
    push_text("7");
    push_key(SDLK_RIGHT);
    push_key(SDLK_RIGHT);
    push_key(SDLK_DOWN);
    push_key(SDLK_DOWN);
    push_key(SDLK_DOWN);
    push_key(SDLK_RETURN);
    int gx = work.x + KD_STUDIO_GX + 6 * KD_STUDIO_ZOOM + 2, gy = work.y + KD_STUDIO_GY + 1 * KD_STUDIO_ZOOM + 2;
    push_mouse(SDL_MOUSEMOTION, gx, gy, scale, top);
    push_mouse(SDL_MOUSEBUTTONDOWN, gx, gy, scale, top);
    push_mouse(SDL_MOUSEBUTTONUP, gx, gy, scale, top);
    int fx = kd_menu_title_x(S.desk.menus, KD_MENU_FILE) + 4;
    push_mouse(SDL_MOUSEMOTION, fx, 4, scale, top);
    push_mouse(SDL_MOUSEBUTTONDOWN, fx, 4, scale, top);
    push_mouse(SDL_MOUSEBUTTONUP, fx, 4, scale, top);
    push_key(SDLK_ESCAPE);
    push_mouse(SDL_MOUSEMOTION, 300, 190, scale, top);
}

static bool smoke_check(SDL_Renderer *ren, const char *path, int scale, int lines, int top) {
    int w = KD_W * scale, h = lines * scale;
    uint32_t *px = malloc((size_t)w * (size_t)h * 4);
    uint8_t *idx = malloc((size_t)KD_W * (size_t)lines);
    if (!px || !idx || SDL_RenderReadPixels(ren, NULL, SDL_PIXELFORMAT_ARGB8888, px, w * 4) != 0) {
        fprintf(stderr, "read back failed: %s\n", SDL_GetError());
        return false;
    }
    int bad = 0;
    for (int y = 0; y < lines; y++)
        for (int x = 0; x < KD_W; x++) {
            uint32_t c = px[(size_t)(y * scale + scale / 2) * w + (size_t)(x * scale + scale / 2)] | 0xFF000000u;
            int i = 0;
            while (i < 16 && pal[i] != c) i++;
            idx[y * KD_W + x] = (uint8_t)(i & 15);
            int dy = y - top;
            int want = (dy < 0 || dy >= KD_H) ? 0 : kd_fb_get(&S.desk.fb, x, dy);
            bad += i != want;
        }
    bool ok = kd_write_png_indexed(path, idx, KD_W, lines);
    bool effects = kd_sprite_get(&S.studio.sprite, 2, 3) == 7 && kd_sprite_get(&S.studio.sprite, 6, 1) == 7 &&
                   S.desk.menu_open == -1;   // a real mouse over the window may move the pointer
    printf("smoke: %d pixel(s) differ from the framebuffer, events %s, %s written\n", bad,
           effects ? "applied" : "NOT applied", path);
    if (!effects)
        printf("smoke: key paint %d, mouse paint %d, menu %d, pointer %d,%d\n", kd_sprite_get(&S.studio.sprite, 2, 3),
               kd_sprite_get(&S.studio.sprite, 6, 1), S.desk.menu_open, S.desk.px, S.desk.py);
    free(px);
    free(idx);
    return ok && bad == 0 && effects;
}

static uint8_t map_key(SDL_Keycode k) {
    switch (k) {
    case SDLK_UP: return KD_KEY_UP;
    case SDLK_DOWN: return KD_KEY_DOWN;
    case SDLK_LEFT: return KD_KEY_LEFT;
    case SDLK_RIGHT: return KD_KEY_RIGHT;
    case SDLK_RETURN: case SDLK_KP_ENTER: return KD_KEY_ENTER;
    case SDLK_ESCAPE: return KD_KEY_ESCAPE;
    case SDLK_TAB: return KD_KEY_TAB;
    case SDLK_BACKSPACE: return KD_KEY_BACKSPACE;
    case SDLK_DELETE: return KD_KEY_DELETE;
    case SDLK_HOME: return KD_KEY_HOME;
    case SDLK_END: return KD_KEY_END;
    case SDLK_F6: return KD_KEY_F6;
    case SDLK_F10: return KD_KEY_F10;
    default: return KD_KEY_NONE;
    }
}

int main(int argc, char **argv) {
    int scale = 3;
    bool k240 = false, outline = false;
    const char *smoke = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--scale") == 0 && i + 1 < argc) scale = atoi(argv[++i]);
        else if (strcmp(argv[i], "--kagura240") == 0) k240 = true;
        else if (strcmp(argv[i], "--outline") == 0) outline = true;
        else if (strcmp(argv[i], "--smoke") == 0 && i + 1 < argc) smoke = argv[++i];
        else {
            fprintf(stderr, "usage: %s [--scale N] [--kagura240] [--outline] [--smoke FILE]\n", argv[0]);
            return 2;
        }
    }
    if (scale < 1 || scale > 8) scale = 3;
    int lines = k240 ? 240 : KD_H, top = k240 ? 20 : 0;   // centre placement
    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    SDL_Window *win = SDL_CreateWindow("KAGURA Desktop (C GEM-style prototype)", SDL_WINDOWPOS_CENTERED,
                                       SDL_WINDOWPOS_CENTERED, KD_W * scale, lines * scale, 0);
    SDL_Renderer *ren = win ? SDL_CreateRenderer(win, -1, SDL_RENDERER_PRESENTVSYNC) : NULL;
    SDL_Texture *tex = ren ? SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, KD_W, KD_H) : NULL;
    if (!tex) {
        fprintf(stderr, "SDL setup: %s\n", SDL_GetError());
        return 1;
    }
    SDL_RenderSetLogicalSize(ren, KD_W, lines);
    SDL_RenderSetIntegerScale(ren, SDL_TRUE);
    SDL_SetRenderDrawBlendMode(ren, SDL_BLENDMODE_BLEND);
    SDL_ShowCursor(SDL_DISABLE);
    SDL_StartTextInput();
    for (int i = 0; i < 16; i++) {
        uint16_t c = kd_palette_rgb444[i];
        pal[i] = 0xFF000000u | (uint32_t)(((c >> 8) & 15) * 17) << 16 | (uint32_t)(((c >> 4) & 15) * 17) << 8 |
                 (uint32_t)((c & 15) * 17);
    }

    kd_shell_demo_scene(&S);
    kd_desktop_set_cursor(&S.desk, true);
    S.desk.outline_drag = outline;
    S.opt_items[KD_OPT_OUTLINE].checked = outline;
    int shots = 0, smoke_frames = 0;
    uint64_t freq = SDL_GetPerformanceFrequency(), render_ticks = 0;
    unsigned frames = 0, tiles = 0, last_title = 0;
    bool running = true, smoke_ok = true;
    window_id = SDL_GetWindowID(win);
    if (smoke) push_smoke(scale, top);
    while (running && !S.quit) {
        SDL_Event e;
        if (smoke ? SDL_PollEvent(&e) : SDL_WaitEventTimeout(&e, 16)) {
            do {
                switch (e.type) {
                case SDL_QUIT: running = false; break;
                case SDL_MOUSEMOTION: post(KD_EV_POINTER_MOVE, e.motion.x, e.motion.y - top, 0, 0, 0, mods_now()); break;
                case SDL_MOUSEBUTTONDOWN: case SDL_MOUSEBUTTONUP:
                    if (e.button.button == SDL_BUTTON_LEFT)
                        post(e.type == SDL_MOUSEBUTTONDOWN ? KD_EV_POINTER_DOWN : KD_EV_POINTER_UP, e.button.x,
                             e.button.y - top, KD_BUTTON_LEFT, 0, 0, mods_now());
                    break;
                case SDL_KEYDOWN: {
                    SDL_Keycode k = e.key.keysym.sym;
                    uint8_t m = mods_now();
                    if (k == SDLK_F12) {
                        char name[64];
                        snprintf(name, sizeof name, "kd-screenshot-%d.png", shots++);
                        printf("%s %s\n", name, kd_write_fb_png(name, &S.desk.fb, scale, k240) ? "written" : "failed");
                    } else if (map_key(k) != KD_KEY_NONE) {
                        post(KD_EV_KEY, 0, 0, 0, map_key(k), 0, m);
                    } else if ((m & (KD_MOD_CTRL | KD_MOD_ALT)) && k >= 32 && k < 127) {
                        post(KD_EV_KEY, 0, 0, 0, KD_KEY_CHAR, (char)k, m);   // no TEXTINPUT with Ctrl
                    }
                    break;
                }
                case SDL_TEXTINPUT:
                    if (mods_now() & (KD_MOD_CTRL | KD_MOD_ALT)) break;
                    for (const char *p = e.text.text; *p; p++)
                        if (*p >= 32 && *p < 127) post(KD_EV_KEY, 0, 0, 0, KD_KEY_CHAR, *p, 0);
                    break;
                default: break;
                }
            } while (SDL_PollEvent(&e));
        }
        uint64_t t0 = SDL_GetPerformanceCounter();
        bool drawn = kd_desktop_render(&S.desk);
        render_ticks += SDL_GetPerformanceCounter() - t0;
        kd_tile4_stats st;
        kd_tile4_flush(&S.desk.fb, 0, staging, KD_TILE_COLS, to_vram, NULL, &st);
        tiles += st.tiles;
        frames += drawn;
        SDL_UpdateTexture(tex, NULL, argb, KD_W * 4);
        SDL_SetRenderDrawColor(ren, (pal[0] >> 16) & 255, (pal[0] >> 8) & 255, pal[0] & 255, 255);
        SDL_RenderClear(ren);   // border lines show BACKDROP = palette 0
        SDL_Rect dst = {0, top, KD_W, KD_H};
        SDL_RenderCopy(ren, tex, NULL, &dst);
        if (S.tiles_overlay) {
            for (unsigned t = 0; t < KD_TILES; t++) {
                if (!flash[t]) continue;
                SDL_SetRenderDrawColor(ren, 255, 0, 0, (Uint8)(flash[t] * 12));
                SDL_Rect r = {(int)(t % KD_TILE_COLS) * 8, top + (int)(t / KD_TILE_COLS) * 8, 8, 8};
                SDL_RenderFillRect(ren, &r);
            }
        }
        for (unsigned t = 0; t < KD_TILES; t++)
            if (flash[t]) flash[t]--;
        if (smoke && ++smoke_frames >= 5) {   // read back before present
            smoke_ok = smoke_check(ren, smoke, scale, lines, top);
            running = false;
        }
        SDL_RenderPresent(ren);
        unsigned now = SDL_GetTicks();
        if (now - last_title > 1000) {
            char title[160];
            snprintf(title, sizeof title, "KAGURA Desktop - %u frames, render avg %.1f us, %u tiles exported",
                     frames, frames ? render_ticks * 1e6 / (double)freq / frames : 0.0, tiles);
            SDL_SetWindowTitle(win, title);
            frames = tiles = 0;
            render_ticks = 0;
            last_title = now;
        }
    }
    SDL_DestroyTexture(tex);
    SDL_DestroyRenderer(ren);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return smoke_ok ? 0 : 1;
}
