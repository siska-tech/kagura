# SPDX-License-Identifier: Apache-2.0
"""Cherry-blossom stress showcase, the MicroPython twin of the Pico C `stress`.

A kagura night scene with 256 falling cherry petals, seven raster-scroll
bands, an aurora animated by a PSRAM->VRAM COPY, a recorded piano played
from PSRAM on both PCM channels and six PSG voices for the accompaniment and
sound effects. The top two lines are a HUD in the Misaki 8x8 font (update
rate, sprite overflows, PCM underruns, PSRAM traffic, ERROR_CODE); a Japanese
marquee runs along the bottom. Both strips are raster-scroll bands pinned to
their own map rows, so they stay put while the scenery scrolls.

The scene, palettes, layers, bands, music and counters are those of the C
version. The loop is slower than 60 Hz on the RP2040, so motion and music
follow FRAME_COUNT_L (VBlanks) and skip frames rather than slow down; the HUD
FPS counts updates. The petal OAM, HUD text and piano resampling are Viper
kernels (sakura_viper.py); raster bands and COPY_SRC go in one ext_writes().

Needs ABI 0.6, kagura_ja and /fonts/misaki8.kfnt; the piano needs CAPS PSRAM
and sakura_assets/piano_c4.pcm (without them the melody plays on a PSG sine).
Usage: import sakura; sakura.run(60)   (0 runs until a key or Ctrl-C)
"""
import gc
import math
import os
import sys
from array import array
from time import ticks_ms, ticks_us, ticks_diff
import kagura
from kagura import regs as R
from kagura.device import DeviceError
import sakura_viper as K

ALL_ON = R.DISPLAY_CTRL_DISPLAY_ENABLE | R.DISPLAY_CTRL_BG_ENABLE | R.DISPLAY_CTRL_SPR_ENABLE

# Pattern allocation (tile 0 stays blank).
TILE_HUD = 16          # 2 x 40 tiles shown on map rows 30-31
TILE_MARQUEE = 96      # 64 tiles on map row 0
TILE_AURORA = 160      # 8 x 4 block, rewritten by COPY every frame
TILE_PETAL = 192       # three 8x8 frames
TILE_BIG_PETAL = 196   # two 16x16 frames (196, 200)
TILE_SCENERY = 256     # deduplicated scenery up to tile 1023
SCENERY_MAX = 1024 - TILE_SCENERY

# 16-colour palettes.
PAL_SKY, PAL_AURORA, PAL_MOUNTAIN, PAL_SHRINE, PAL_FOREST, PAL_WATER = range(6)
PAL_PETAL, PAL_PETAL_FAR, PAL_PETAL_BIG, PAL_MARQUEE, PAL_HUD = 10, 11, 12, 14, 15
# Text colours in the HUD and marquee palettes.
C_SHADOW, C_BAR, C_RULE, C_BAD, C_GOOD, C_NOTE, C_LABEL, C_TEXT = 1, 2, 3, 9, 10, 11, 12, 15

# PSRAM layout.
PSRAM_NOTES = 0x400000        # long piano notes, 64 KiB apart
PSRAM_SHORT_NOTES = 0x480000  # short versions, 32 KiB apart
SHORT_SLOT = 0x8000
NOTE_SLOT = 0x10000
# A PREPARE cuts a note still sounding on its channel, which clicks. Notes
# whose channel is reused within 1 s use the short version, silent by the
# time the channel is reused (500 ms at the earliest).
NOTE_MAX = (48000, 23040)     # 1 s, 0.48 s
NOTE_FADE = (2400, 9600)
PSRAM_AURORA = 0x500000       # 16 frames x 1 KiB
# The C4 recording is streamed from its file through a small window.
PIANO_SAMPLES = 72000
PIANO_BLOCK = 4096
PIANO_WINDOW = 8192

# Scenery bands of the 240-line layout: first line, which is also the map y
# of their art; X speed in 1/16 px per frame. The 180-line layout squeezes
# the band starts and shows the top of each band's art (RS_Y).
BAND_Y = (16, 72, 104, 136, 176, 200)
BAND_SPEED = (1, 3, 6, 12, 24, 40)
BANDS = 6

# Three petal layers with evenly spaced Y so a line never holds more than
# 3 + 5 + 5 sprites (240 lines) or 3 + 6 + 6 (180 lines), under the 16 limit.
# first, count, size, speed, sway, wind, palette (sakura_viper.LAYER bytes).
LAYERS = bytes((0, 32, 16, 20, 20, 24, PAL_PETAL_BIG,     # near: lowest numbers, drawn on top
                32, 112, 8, 12, 12, 16, PAL_PETAL,
                144, 112, 8, 6, 8, 8, PAL_PETAL_FAR))     # far: behind the scenery
WRAP = 352 * 16    # wind_x period in 1/16 px; the petals wrap every 352 px

# Main-loop optimizations, each switchable for A/B runs (Sakura(opt=...)):
#   order   wait for the previous COMMIT before the transfers instead of inside the OAM write
#   hud     redraw only the HUD tiles whose glyphs changed, one row per update
#   bands   fill only the changing values of a precomputed EXT table
#   palette per-frame colours from tables, the flame's mix() every third VBlank
#   regs    per-frame register reads and the COPY command as bare link transactions
#   hudascii draw ASCII HUD fields directly, without caching numeric layouts
#   hudbuf  fixed fields and native diff/draw; load its kernels after the scene
#   hudround match RP2 float32 MB formatting with integer arithmetic
#   hudglyph dirty only the changed glyphs within a stationary fixed field
#   steady  optionally reserve every sound view before timing (STEADY_OPTS)
#   oam     hoist frame/layer constants out of the 256-petal native loop
#   short   fixed register transactions through Link's ownership/error wrapper
OPTS = ('order', 'hud', 'bands', 'palette', 'regs', 'hudascii', 'hudbuf', 'hudround', 'hudglyph', 'oam', 'short')
STEADY_OPTS = OPTS + ('steady',)

MARQUEE = ("◆ 神楽九 KAGURA-9 ◆ 桜256枚・ラスター8段・PSRAMピアノ2声・PSG6声 同時処理中 "
           "◆ Tang Nano 9K + Raspberry Pi Pico + MicroPython")   # 512 px; the 512 px loop wraps into the first ◆
TITLE = "神楽 全機能ストレステスト"
LABELS = ("スプライト", "オーバーフロー", "PCMアンダーラン")
HUD_WIDE = (TITLE,) + LABELS
LOADING = ("背景を生成中", "オーロラをPSRAMへ転送中", "オーロラを生成中",
           "ピアノ音源をPSRAMへ転送中", "音源を初期化中")

_Q = (0, 12, 24, 35, 45, 53, 59, 63, 64, 63, 59, 53, 45, 35, 24, 12, 0)
SINE64 = tuple(_Q[p] if p < 16 else _Q[32 - p] if p < 32 else -_Q[p - 32] if p < 48 else -_Q[64 - p]
               for p in range(64))
SINE_BYTES = bytes(v + 64 for v in SINE64)


def sine64(phase):
    return SINE64[phase & 63]


def div(a, b):
    """C integer division (toward zero) for b > 0."""
    return a // b if a >= 0 else -(-a // b)


SHIMMER = tuple(div(v, 16) + 4 for v in SINE64)   # water band X offset by phase t * 3


def mix(x):
    x &= 0xffffffff
    x ^= x >> 16
    x = x * 0x7feb352d & 0xffffffff
    x ^= x >> 15
    x = x * 0x846ca68b & 0xffffffff
    return x ^ x >> 16


def rgb(r, g, b):
    return (r & 15) << 8 | (g & 15) << 4 | (b & 15)


def pal_set(pal, p, c, colour):
    pal[2 * (p * 16 + c)] = colour & 255
    pal[2 * (p * 16 + c) + 1] = colour >> 8


def tile_px(tiles, tile, x, y, c):
    i = tile * 32 + y * 4 + x // 2
    tiles[i] = (tiles[i] & 0xf0) | c if x & 1 else (tiles[i] & 0x0f) | c << 4


# 16x16 sprites use base, base+1 (top) and base+2, base+3 (bottom).
def sprite_px(tiles, base, x, y, c):
    tile_px(tiles, base + (2 if y >= 8 else 0) + (1 if x >= 8 else 0), x & 7, y & 7, c)


# ---- Text ---------------------------------------------------------------

class Text:
    """Misaki glyphs drawn into one text row (8 x 512 pixels, one byte each),
    packed into 4bpp tiles. Glyphs are read from the KJ8F font once."""

    def __init__(self, font_path):
        from kagura_ja import Font
        codes = set(range(0x20, 0x7f))
        for s in (MARQUEE, TITLE) + LABELS + LOADING:
            codes.update(ord(ch) for ch in s)
        self.glyphs = {}
        with Font(font_path) as font:
            for code in codes:
                rows = font.glyph(code)
                if rows is None:
                    continue
                # KJ8F centres the 4 px half-width glyphs in their cell.
                width = 4 if code < 0x80 or 0xff61 <= code <= 0xff9f else 8
                if width == 4:
                    rows = bytes((r << 2) & 255 for r in rows)
                self.glyphs[code] = (rows, width)
        self.unknown = self.glyphs[0x3f]
        # One atlas of every glyph's rows for draw_run(); slot = position.
        codes = sorted(self.glyphs)
        if len(codes) > 256:
            raise ValueError('more than 256 glyphs')
        self.slots = {code: i for i, code in enumerate(codes)}
        # ASCII slot lookup precedes the glyph rows, shared by both draw_run modes.
        self.atlas = bytes(self.slots.get(code, self.slots[0x3f]) for code in range(128)) + b''.join(
            self.glyphs[code][0] for code in codes)
        self.layouts = {}
        self.strip = bytearray(8 * 512)
        self.packed = bytearray(64 * 32)

    def text(self, x, s, colour):
        """Draw UTF-8 text with a drop shadow; with colour 0 only measure.
        Returns the x after the text."""
        get, unknown, strip = self.glyphs.get, self.unknown, self.strip
        for ch in s:
            rows, width = get(ord(ch), unknown)
            if colour:
                K.glyph(strip, x, rows, width | colour << 8)
            x += width
        return x

    def clear(self, rule):
        K.clear_span(self.strip, 0, 512, rule)

    def pack(self, tiles):
        K.pack(self.strip, self.packed, tiles)
        return memoryview(self.packed)[:tiles * 32]

    def measure(self, s):
        return self.layout(s)[1]

    def layout(self, s):
        """(layout, width) of a string for sakura_viper.draw_run(), cached:
        walking a str costs tens of microseconds per character on the RP2040."""
        cache = self.layouts
        hit = cache.get(s)
        if hit is None:
            if len(cache) >= 96:                    # the changing numbers would grow it without end
                cache.clear()
            slots, glyphs, x = self.slots, self.glyphs, 0
            out = bytearray(4 * len(s))
            for i, ch in enumerate(s):
                code = ord(ch)
                if code not in glyphs:
                    code = 0x3f
                width = glyphs[code][1]
                out[4 * i], out[4 * i + 1], out[4 * i + 2], out[4 * i + 3] = x & 255, x >> 8, slots[code], width
                x += width
            hit = cache[s] = (bytes(out), x)
        return hit


# ---- Scenery ------------------------------------------------------------

def mountain_top(x):
    return 118 + div(sine64(x // 4) * 10, 64) + div(sine64(x // 2 + 13) * 5, 64) + div(sine64(x + 7) * 2, 64)


def hill_top(x):
    return 158 + div(sine64(x // 2 + 5) * 6, 64) + div(sine64(x + 20) * 3, 64)


# A vermilion torii, 48 px wide, u = 0..47; -1 where it has no pixel.
def torii(u, y):
    if u < 0 or u > 47:
        return -1
    if y == 139:
        return 7 if u <= 2 or u >= 45 else -1                 # upturned kasagi ends
    if y == 140:
        return 7                                              # black cap
    if y == 141 or y == 142:
        return 5 if 2 <= u <= 45 else -1
    if y == 144 and 4 <= u <= 43:
        return 5                                              # shimaki
    if 145 <= y <= 148 and 22 <= u <= 25:
        return 6                                              # gakuzuka
    if (y == 150 or y == 151) and 5 <= u <= 42:
        return 5                                              # nuki
    if y >= 143 and (9 <= u <= 12 or 35 <= u <= 38):
        return 7 if y >= 172 else 6 if u == 12 or u == 38 else 5   # pillars
    return -1


# A stone lantern (toro), u = x mod 64.
def lantern(u, y):
    if y == 182:
        return 3 if 30 <= u <= 33 else -1
    if y == 183:
        return 3 if 28 <= u <= 35 else -1
    if y == 184:
        return 3 if 26 <= u <= 37 else -1
    if 185 <= y <= 189 and 28 <= u <= 35:
        return 8 if 186 <= y <= 188 and 30 <= u <= 33 else 3
    if y == 190:
        return 3 if 27 <= u <= 36 else -1
    if 191 <= y <= 196:
        return 4 if 30 <= u <= 33 else -1
    if y >= 197:
        return 3 if 27 <= u <= 36 else -1
    return -1


class Scene:
    """Colour of the scenery pixel at map (x, y), y in the 240-line layout.
    Every feature repeats with a period that divides the 512 px map width."""

    def __init__(self):
        self.mt = array('h', [mountain_top(x) for x in range(514)])
        self.ht = array('h', [hill_top(x) for x in range(512)])
        self.trees = tuple((mix(k) % 5 - 2, 10 + mix(k + 100) % 12) for k in range(8))
        self.stars = bytearray(128)

    def line(self, y, out):
        """Pixels 0..511 of line y into out (bytes from 0, 512 apart is the caller's)."""
        if y < 72:                                  # stars every 128 px, for this line
            for u in range(128):
                h = mix(u * 977 + y * 131)
                self.stars[u] = 3 if h % 331 == 0 else ((2 if (h >> 8) & 1 else 1) if h % 61 == 0 else 0)
        for x in range(512):
            out[x] = self.px(x, y)

    def px(self, x, y):
        if y < 72:                                  # sky: one moon
            dx, dy = x - 380, y - 44
            d = dx * dx + dy * dy
            if d <= 121:
                if (dx + 3) * (dx + 3) + (dy - 2) * (dy - 2) <= 6 or (dx - 4) * (dx - 4) + (dy + 4) * (dy + 4) <= 3:
                    return 5
                return 6 if dx > 6 else 4
            if d <= 196:
                return 7 if (x + y) & 1 else 0
            return self.stars[x & 127]
        if y < 136:                                 # far mountains
            top = self.mt[x]
            if y < top:
                return 0
            if y < top + 3 and top < 114:
                return 4
            if self.mt[x + 2] < top and y < top + 8:
                return 2
            return 3 if y > 130 else 1
        if y < 176:                                 # hills and a torii every 256 px
            c = torii((x - 100) & 255, y)
            if c >= 0:
                return c
            top = self.ht[x]
            return (2 if y < top + 2 else 1) if y >= top else 3   # 3: haze continuing the mountains' base
        if y < 200:                                 # forest and stone lanterns
            c = lantern(x & 63, y)
            if c >= 0:
                return c
            if y >= 194:
                return 1
            for j in range(x // 16 - 1, x // 16 + 2):
                shift, height = self.trees[j & 7]
                dx = x - (j * 16 + 8 + shift)
                if y >= 199 - height + 2 * abs(dx):
                    return 2 if dx < 0 and y < 199 - height + 2 * -dx + 2 else 1
            return 5                                # the hills behind the trees
        dx = x - 380                                # water with the moon's reflection
        if -10 <= dx <= 10 and (x + y * 5) & 3 == 0 and mix(x + y * 512) & 1:
            return 3
        return 2 if (x + y * 11) & 31 < 2 + ((y & 3) == 0) else 1


def map_set(work, col, row, tile, palette):
    entry = tile | palette << 10
    work[2 * (row * 64 + col)] = entry & 255
    work[2 * (row * 64 + col) + 1] = entry >> 8


def build_scenery(d, strip, packed, work):
    """Map and deduplicated scenery tiles; returns the unique tile count."""
    scene = Scene()
    seen = {}
    blank = bytes(32)
    work[:4096] = bytes(4096)
    for col in range(64):
        map_set(work, col, 0, TILE_MARQUEE + col, PAL_MARQUEE)
        map_set(work, col, 30, TILE_HUD + col if col < 40 else 0, PAL_HUD)
        map_set(work, col, 31, TILE_HUD + 40 + col if col < 40 else 0, PAL_HUD)
        for row in range(9, 13):
            map_set(work, col, row, TILE_AURORA + (row - 9) * 8 + (col & 7), PAL_AURORA)
    line = memoryview(strip)
    for row in range(2, 29):
        if 9 <= row < 13:
            continue
        palette = (PAL_SKY if row < 9 else PAL_MOUNTAIN if row < 17 else PAL_SHRINE if row < 22
                   else PAL_FOREST if row < 25 else PAL_WATER)
        for y in range(8):
            scene.line(row * 8 + y, line[y * 512:])
        K.pack(strip, packed, 64)
        first, new = len(seen), []
        for col in range(64):
            t = bytes(packed[col * 32:col * 32 + 32])
            if t == blank:
                tile = 0
            else:
                tile = seen.get(t)
                if tile is None:
                    if len(seen) == SCENERY_MAX:
                        raise ValueError('scenery needs more than %d tiles' % SCENERY_MAX)
                    tile = seen[t] = TILE_SCENERY + len(seen)
                    new.append(t)
            map_set(work, col, row, tile, palette)
        if new:                                     # this row's new tiles are consecutive
            d.write_memory((TILE_SCENERY + first) * 32, b''.join(new))
    d.write_memory(R.VRAM_MAP_BASE, memoryview(work)[:4096])
    print('SAKURA scenery: %d unique tiles' % len(seen))
    return len(seen)


# One 64x32 px aurora frame (8 x 4 tiles) in out[0..1023]; 16 frames loop.
# Each band of 8 lines is drawn into the strip and packed through `packed`.
def make_aurora(f, strip, packed, out):
    blank = bytes(64)
    for ty in range(4):
        for y in range(8):
            strip[y * 512:y * 512 + 64] = blank
        for x in range(64):
            foot = 22 + div(sine64(x * 2 + f * 4), 10) + div(sine64(x + 80 - f * 4), 16)
            bright = (sine64(x * 3 + f * 8) + 64) // 43 - 1
            for y in range(ty * 8, min(ty * 8 + 8, foot + 1)):
                glow = 7 - (foot - y) // 3 + bright
                if glow >= 1:
                    strip[(y - ty * 8) * 512 + x] = 7 if glow > 7 else glow
        K.pack(strip, packed, 8)
        out[ty * 256:ty * 256 + 256] = memoryview(packed)[:256]


def make_petals(work):
    small = (
        ("..1..1..", ".11.111.", ".122221.", ".122221.", "..1221..", "..1331..", "...33...", "........"),
        ("........", "...111..", "..12221.", ".122221.", ".12221..", ".1331...", "..3.....", "........"),
        ("........", "........", ".111111.", "12222331", ".111111.", "........", "........", "........"),
    )
    work[:12 * 32] = bytes(12 * 32)
    for f in range(3):
        for y in range(8):
            for x in range(8):
                if small[f][y][x] != '.':
                    tile_px(work, f, x, y, ord(small[f][y][x]) - 48)
    for f in range(2):                              # big petal, face-on and turned
        for y in range(16):
            for x in range(16):
                # Round shoulders tapering to the base, with a V notch on top;
                # frame 1 is the same petal turned edge-on (narrower).
                ty = (y + 0.5) / 16
                u, v = (ty - 0.35) / 0.65, (0.35 - ty) / 0.38
                half = (7.2 * math.sqrt(max(0.0, 1 - u * u)) * (1 - 0.5 * u) if ty >= 0.35
                        else 7.2 * math.sqrt(max(0.0, 1 - v * v)))
                dx = abs(x - 7.5) * (1.8 if f else 1.0)
                if dx >= half or 3.2 - dx > y:
                    continue
                fx, fy = (x - 7.5) / 7.5, (y - 7.5) / 7.5
                c = 4 if fx < -0.3 and fy < -0.2 else 3 if fy > 0.55 else 2 if fx * fx + fy * fy < 0.3 else 1
                sprite_px(work, 4 + f * 4, x, y, c)


# ---- Palette ------------------------------------------------------------

AURORA = (0x032, 0x053, 0x175, 0x2a7, 0x4d9, 0x8fc)   # colour 7, the crest, changes per frame


def build_palette(pal, t):
    pal[:] = bytes(len(pal))
    pal_set(pal, PAL_SKY, 0, 0x013)                 # backdrop
    pal_set(pal, PAL_SKY, 1, 0x667)
    pal_set(pal, PAL_SKY, 2, 0xaac)
    for c, v in ((4, 0xffd), (5, 0xddb), (6, 0xbb9), (7, 0x236)):
        pal_set(pal, PAL_SKY, c, v)
    for c in range(6):
        pal_set(pal, PAL_AURORA, c + 1, AURORA[c])
    for c, v in ((1, 0x235), (2, 0x347), (3, 0x346), (4, 0xcdf)):
        pal_set(pal, PAL_MOUNTAIN, c, v)
    for c, v in ((1, 0x122), (2, 0x243), (3, 0x346), (5, 0xe32), (6, 0x911), (7, 0x111)):
        pal_set(pal, PAL_SHRINE, c, v)
    for c, v in ((1, 0x021), (2, 0x132), (3, 0x778), (4, 0x556), (5, 0x122)):
        pal_set(pal, PAL_FOREST, c, v)
    pal_set(pal, PAL_WATER, 1, 0x024)
    pal_set(pal, PAL_WATER, 2, 0x147)
    for c, v in ((1, 0xf9b), (2, 0xfde), (3, 0xd58)):
        pal_set(pal, PAL_PETAL, c, v)
    for c, v in ((1, 0xb8b), (2, 0xdad), (3, 0x969)):
        pal_set(pal, PAL_PETAL_FAR, c, v)
    for c, v in ((1, 0xf8a), (2, 0xfcd), (3, 0xc47), (4, 0xfef)):
        pal_set(pal, PAL_PETAL_BIG, c, v)
    for p in (PAL_MARQUEE, PAL_HUD):
        hud = p == PAL_HUD
        for c, v in ((C_SHADOW, 0x000), (C_BAR, 0x123 if hud else 0x302), (C_RULE, 0x48c if hud else 0xc53),
                     (C_BAD, 0xf55), (C_GOOD, 0x6e8), (C_NOTE, 0xfd5), (C_LABEL, 0x9bd),
                     (C_TEXT, 0xfff if hud else 0xfec)):
            pal_set(pal, p, c, v)
    palette_frame(pal, t)


def palette_frame(pal, t):
    """The entries that change per frame, all in palettes 0..5 (bytes 0..191)."""
    tw = 10 + div(sine64(t * 3), 13)                # twinkling stars
    pal_set(pal, PAL_SKY, 3, rgb(tw, tw, 15))
    shift = (sine64(t // 2) + 64) // 43             # slow violet tint on the crest
    pal_set(pal, PAL_AURORA, 7, rgb(12 + shift, 15 - shift, 14))
    flick = mix(t // 3)                             # lantern flame
    pal_set(pal, PAL_FOREST, 8, rgb(15, 10 + flick % 4, 3 + (flick >> 8) % 3))
    gl = 11 + div(sine64(t * 5), 16)                # moonlight on the water
    pal_set(pal, PAL_WATER, 3, rgb(gl, gl, 12))


def _le16(colour):
    return colour & 255, colour >> 8


# palette_frame()'s colours by sine phase, and their byte offsets in the palette.
SKY_TWINKLE = tuple(_le16(rgb(10 + div(v, 13), 10 + div(v, 13), 15)) for v in SINE64)            # phase t * 3
AURORA_CREST = tuple(_le16(rgb(12 + (v + 64) // 43, 15 - (v + 64) // 43, 14)) for v in SINE64)   # phase t // 2
WATER_GLOW = tuple(_le16(rgb(11 + div(v, 16), 11 + div(v, 16), 12)) for v in SINE64)              # phase t * 5
AT_SKY, AT_CREST, AT_FLAME, AT_WATER = (2 * (PAL_SKY * 16 + 3), 2 * (PAL_AURORA * 16 + 7),
                                        2 * (PAL_FOREST * 16 + 8), 2 * (PAL_WATER * 16 + 3))


class PaletteFrame:
    """palette_frame() from the tables above. The lantern flame changes every
    third VBlank; sakura_viper.flame() computes its mix() in native words, as
    mix() itself would need big integers on the RP2040. Allocates nothing."""

    def __init__(self):
        self.key = -1

    def __call__(self, pal, t):
        pal[AT_SKY], pal[AT_SKY + 1] = SKY_TWINKLE[(t * 3) & 63]
        pal[AT_CREST], pal[AT_CREST + 1] = AURORA_CREST[(t // 2) & 63]
        key = t // 3
        if key != self.key:
            self.key = key
            colour = K.flame(key)
            pal[AT_FLAME], pal[AT_FLAME + 1] = colour & 255, colour >> 8
        pal[AT_WATER], pal[AT_WATER + 1] = WATER_GLOW[(t * 5) & 63]


# ---- Sound --------------------------------------------------------------

# Piano notes resampled from the C4 recording: semitones from C4.
NOTE_SEMI = (-3, -1, 0, 4, 5, 9, 11, 12, 16, 17, 21)
NOTES = len(NOTE_SEMI)
# Original melody in the miyako-bushi scale, one entry per eighth note:
# 1 + index into NOTE_SEMI, 0 for a rest. Eight bars loop.
MELODY = bytes((
    6, 0, 7, 0, 8, 0, 7, 6,  5, 0, 0, 0, 4, 0, 0, 0,  6, 0, 7, 0, 8, 0, 9, 0,  10, 0, 9, 8, 7, 0, 0, 0,
    9, 0, 10, 0, 9, 0, 8, 7, 6, 0, 0, 0, 8, 0, 7, 0,  6, 0, 5, 0, 4, 0, 5, 0,  6, 0, 0, 0, 1, 0, 0, 0,
))
# Per bar: bass and two pad notes, semitones from C4.
CHORDS = ((-15, 0, 4), (-19, -3, 0), (-15, 0, 4), (-20, -3, -1),
          (-19, -3, 0), (-15, 0, 4), (-22, -7, -3), (-15, -3, 0))


def read_fully(f, buf):
    """readinto() until buf is full or the file ends; returns the bytes read."""
    got = 0
    while got < len(buf):
        n = f.readinto(buf[got:])
        if not n:
            break
        got += n
    return got


def step_hz(hz):
    return int(hz * 16777216 / 48000 + 0.5)


def step_whole_hz(hz):
    """step_hz() of a whole number of hertz below 4096 in small integers (no
    float objects per call): hz * 2**24 / 48000 = hz * 131072 / 375, rounded
    half up. The fraction is never exactly one half, so this is step_hz()
    computed exactly."""
    return (hz * 262144 + 375) // 750


def semi_step(semi):
    return step_hz(261.63 * 2 ** (semi / 12))


BELL = (step_hz(1318.5), step_hz(1760.0))   # alternating E6/A6 shimmer
# Every semitone the music uses, computed once instead of per note.
SEMI_STEPS = {s: semi_step(s) for s in set(NOTE_SEMI) | {c for chord in CHORDS for c in chord}}


# Eighth notes until the melody's second next note, which reuses this
# note's PCM channel.
def channel_reuse_steps(step):
    seen = 0
    for d in range(1, 64):
        if MELODY[(step + d) & 63]:
            seen += 1
            if seen == 2:
                return d
    return 64


class Sound:
    """Register writes are queued as (index, value) pairs and sent once per
    update with device.audio_writes(); envelopes advance once per VBlank."""

    def __init__(self, d, pcm, psg):
        self.d, self.pcm, self.psg = d, pcm, psg
        self.ops, self.n = bytearray(128), 0
        self.ops_view = memoryview(self.ops)
        self.views = {}
        self.noise = self.bass = self.bell = self.gust = self.lead = 0
        self.next_pcm = 0
        self.start = [0, 0]
        self.length = [0, 0]
        self.done_bytes = 0          # samples fetched by finished or cut notes
        self.note_len = [[0, 0] for _ in range(NOTES)]
        self.audio_read = d.audio_read   # Sakura swaps in a raw read for opt 'regs'
        self.started = False             # a piano note started since the flag was cleared
        self.steady = False

    def reserve_views(self):
        view = self.ops_view
        # All queued lengths of the melody/envelopes with 1..8 VBlanks per
        # update. Reserve the used lengths rather than enlarging the dict
        # to every even size; arbitrary future writes still use send's fallback.
        for n in (12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 38, 44, 50):
            if n not in self.views:
                self.views[n] = view[:n]

    def write(self, index, value):
        ops, n = self.ops, self.n
        ops[n], ops[n + 1] = index, value
        self.n = n + 2

    def send(self):
        n = self.n
        if n:
            view = self.views.get(n)
            if view is None:                        # one view per length, kept: no new view per update
                view = self.views[n] = self.ops_view[:n] if self.steady else memoryview(self.ops)[:n]
            self.d.audio_writes(view)
            self.n = 0

    def step(self, ch, step):
        base = ch * R.AUDIO_CH_STRIDE + R.AUDIO_STEP_L
        self.write(base, step & 255)
        self.write(base + 1, step >> 8 & 255)
        self.write(base + 2, step >> 16 & 255)

    def gain(self, ch, left, right):
        self.write(ch * R.AUDIO_CH_STRIDE + R.AUDIO_GAIN_L, left)
        self.write(ch * R.AUDIO_CH_STRIDE + R.AUDIO_GAIN_R, right)

    def pcm_write(self, p, offset, value):
        self.write(R.AUDIO_PCM_BASE + p * R.AUDIO_PCM_STRIDE + offset, value)

    def init(self, work):
        """Silence every channel, set the wave tables (ch4 triangle bass, ch5
        sine for leads and effects) and enable both PCM channels."""
        for i in range(256):
            work[i] = (i * 2 - 128 if i < 128 else 383 - i * 2) & 255
            s = sine64(i // 4)
            work[256 + i] = (s * 2 - (s > 0)) & 255
        self.write(R.AUDIO_MASTER_GAIN, 40)
        for ch in range(R.AUDIO_CHANNELS):
            self.step(ch, 0)
            if ch < 3:
                self.write(ch * 16 + R.AUDIO_DUTY, (64, 64, 32)[ch])
            if ch >= 4:
                self.write(ch * 16 + R.AUDIO_LEN_LOG2, 8)
            self.gain(ch, 0, 0)
            self.write(ch * 16 + R.AUDIO_CONTROL,
                       R.AUDIO_CONTROL_ENABLE | R.AUDIO_CONTROL_PHASE_RESET if self.psg else 0)
            self.send()
        self.gain(0, 12, 6)                         # pads, spread left and right
        self.gain(1, 6, 12)
        for p in range(2 if self.pcm else 0):
            self.pcm_write(p, R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_STOP | R.AUDIO_PCM_CMD_CLEAR)
            self.pcm_write(p, R.AUDIO_PCM_GAIN_L, 120 if p else 160)
            self.pcm_write(p, R.AUDIO_PCM_GAIN_R, 160 if p else 120)
            self.pcm_write(p, R.AUDIO_PCM_CONTROL, R.AUDIO_PCM_CONTROL_ENABLE)
        self.send()
        # Both wave banks get the same tables (every AUDIO_COMMIT swaps them).
        for _ in range(2):
            self.d.write_memory(R.VRAM_WAVE_BASE, memoryview(work)[:512])
            self.d.audio_commit()

    def played(self, p, now):
        if self.steady:
            length = self.length[p]
            elapsed = ticks_diff(now, self.start[p])
            if length <= 0 or elapsed <= 0:
                return 0
            if elapsed >= 1000000 and length <= 48000:
                return length
            return min(elapsed * 48 // 1000, length)
        n = ticks_diff(now, self.start[p]) * 48 // 1000
        return max(0, min(n, self.length[p]))

    def pcm_bytes(self):
        now = ticks_us()
        return self.done_bytes + self.played(0, now) + self.played(1, now)

    def piano(self, n, short):
        """Start a piano note on the PCM channel not used by the previous note,
        so two notes ring together. ENABLE is already 1; the update's
        AUDIO_COMMIT starts it."""
        p = self.next_pcm
        self.next_pcm ^= 1
        self.done_bytes += self.played(p, ticks_us())
        start = PSRAM_SHORT_NOTES + n * SHORT_SLOT if short else PSRAM_NOTES + n * NOTE_SLOT
        length = self.note_len[n][short]
        end = start + length
        for b in range(3):
            self.pcm_write(p, R.AUDIO_PCM_START_L + b, start >> 8 * b & 255)
        for b in range(3):
            self.pcm_write(p, R.AUDIO_PCM_END_L + b, end >> 8 * b & 255)
        self.pcm_write(p, R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_PREPARE)
        self.send()
        status = R.AUDIO_PCM_BASE + p * R.AUDIO_PCM_STRIDE + R.AUDIO_PCM_STATUS
        t0 = ticks_us()
        read = self.audio_read
        while not read(status) & R.AUDIO_PCM_STATUS_READY and ticks_diff(ticks_us(), t0) < 2000:
            pass
        self.started = True
        self.start[p] = ticks_us()
        self.length[p] = length

    def tick(self, t, last):
        """One VBlank of the C sound_frame(); an eighth note is 15 of them
        (120 BPM). Gains and sweeps are written for the update's last tick
        only. Returns True when a wind gust starts."""
        gust = False
        if t % 15 == 0:
            step = t // 15
            bar, pos, m = (step // 8) & 7, step & 7, MELODY[step & 63]
            if m and self.pcm:
                self.piano(m - 1, int(channel_reuse_steps(step) < 4))   # reused within 1 s
            if m and not self.pcm:
                self.step(5, SEMI_STEPS[NOTE_SEMI[m - 1]])
                self.lead = 60
            if pos == 0:
                chord = CHORDS[bar]
                self.step(0, SEMI_STEPS[chord[1]])
                self.step(1, SEMI_STEPS[chord[2]])
                self.step(4, SEMI_STEPS[chord[0]])
            if pos == 0 or pos == 4:
                self.bass = 80
            if pos in (0, 3, 4):                    # taiko "don"
                self.noise = 90
                self.write(3 * 16 + R.AUDIO_NOISE_PERIOD_L, 40)
                if self.psg:
                    self.write(3 * 16 + R.AUDIO_CONTROL, R.AUDIO_CONTROL_ENABLE | R.AUDIO_CONTROL_PHASE_RESET)
            elif pos in (2, 6, 7):                  # rim "ka"
                self.noise = 36
                self.write(3 * 16 + R.AUDIO_NOISE_PERIOD_L, 1)
            if pos == 0 and bar & 1 == 0:
                self.bell = 40                      # suzu bells
            if pos == 0 and bar == 4 and self.pcm:
                self.gust = 120
                gust = True
        if last:
            self.gain(3, self.noise, self.noise)
            self.gain(4, self.bass, self.bass)
        self.noise = self.noise * 13 // 16
        self.bass = self.bass * 31 // 32
        if self.bell:
            if last:
                self.step(2, BELL[(t // 3) & 1])
                self.gain(2, self.bell, self.bell * 3 // 4)
            self.bell -= 1
        elif last:
            self.gain(2, 0, 0)
        if self.gust:                               # wind sparkle: rising sine
            if last:
                g = (120 - self.gust) // 2 if self.gust > 60 else self.gust // 2
                self.step(5, step_whole_hz(700 + (120 - self.gust) * 22 + sine64(t * 8) * 6))
                self.gain(5, g, 30 - g)
            self.gust -= 1
        else:
            if last:
                self.gain(5, self.lead, self.lead)
            self.lead = self.lead * 15 // 16
        return gust

    def stop(self):
        self.n = 0
        for ch in range(R.AUDIO_CHANNELS):
            self.write(ch * 16 + R.AUDIO_CONTROL, 0)
        for p in range(2 if self.pcm else 0):
            self.pcm_write(p, R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_STOP)
            self.pcm_write(p, R.AUDIO_PCM_CONTROL, 0)
        self.send()
        self.d.audio_commit()


# ---- Demo ---------------------------------------------------------------

def _keyboard():
    """A function returning True once any key except CR/LF arrives on stdin."""
    try:
        import select
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
    except (ImportError, AttributeError, OSError, ValueError):
        return lambda: False

    # ipoll() reuses one result instead of returning a new list (no garbage per update).
    ready = getattr(poll, 'ipoll', poll.poll)
    ready(0)                                       # allocate ipoll's cached tuple before timing; do not read stdin

    def pressed():
        for _ in ready(0):
            c = sys.stdin.read(1)
            if not c:                               # end of input: nobody can press a key
                return False
            if c not in '\r\n':                     # ignore the CRLF left after the command
                return True
        return False
    return pressed


class Stats:
    """Per-update measurements for benchmarks.

    proc: microseconds of work per update, i.e. the loop time minus the wait
    for the previous COMMIT to apply (with opt 'order'; without it that wait
    hides inside the OAM write) and minus the FRAME_COUNT read made only for
    these statistics. flags: 1 housekeeping or HUD work, 2 a piano note
    started, 4 a device error. cadence: VBlanks between successive applied
    COMMITs, read right after each wait, so every counted update was shown.

    The heap is sampled every SAMPLE updates (gc.mem_alloc() walks the whole
    allocation table, milliseconds): net heap growth per update from windows
    without a collection. Temporaries freed before a sample (notably VM call
    frames) are not counted. A drop detects a collection, whose update is taken to be the
    slowest one of that window and is counted under 'gc' instead.
    """

    BIN = 100      # us per histogram bin
    BINS = 1000    # 0..99.9 ms; longer updates land in the last bin
    SAMPLE = 30    # updates per heap sample

    def __init__(self):
        # Recording buffers allocated once; reset() reuses them.
        self.hist = [array('H', (0 for _ in range(self.BINS))) for _ in range(4)]   # all, normal, hud, gc
        self.total = [0, 0, 0, 0]
        self.count = [0, 0, 0, 0]
        self.cadence = array('H', (0 for _ in range(16)))
        self.reset()

    def reset(self):
        for h in self.hist:
            for b in range(self.BINS):
                h[b] = 0
        for k in range(4):
            self.total[k] = self.count[k] = 0
        for c in range(16):
            self.cadence[c] = 0
        self.over = 0      # updates over one 59.94 Hz frame (16.68 ms)
        self.n = 0
        self.frame = None
        self.confirmed = None
        self.sync_us = self.sync_max_us = self.sample_us = 0
        self.vblanks = 0
        self.track_heap = hasattr(gc, 'mem_alloc')   # MicroPython only
        self.heap = None
        self.allocated = self.allocating = self.collections = 0
        self.window = self.slowest = self.slowest_k = 0

    def _put(self, k, proc, sign):
        b = min(proc // self.BIN, self.BINS - 1)
        self.hist[k][b] += sign
        self.total[k] += sign * proc
        self.count[k] += sign

    def add(self, proc, flags, frame):
        if self.frame is not None:                  # the first update includes setup: not counted
            cadence = (frame - self.frame) & 255
            self.vblanks += cadence
            self.cadence[min(cadence, 15)] += 1
            k = 2 if flags & 1 else 1
            self._put(0, proc, 1)
            self._put(k, proc, 1)
            if proc > 16683:
                self.over += 1
            if proc > self.slowest:
                self.slowest, self.slowest_k = proc, k
            self.window += 1
        self.frame = frame
        self.n += 1
        if self.track_heap and self.window >= self.SAMPLE:
            heap = gc.mem_alloc()
            if self.heap is not None:
                if heap < self.heap:                # a collection ran in this window
                    self.collections += 1
                    self._put(self.slowest_k, self.slowest, -1)
                    self._put(3, self.slowest, 1)
                else:
                    self.allocated += heap - self.heap
                    self.allocating += self.window
            self.heap = heap
            self.window = self.slowest = 0

    def summary(self, k):
        """count, mean, p50, p95, p99, max in ms (percentiles and max to the bin's upper edge)."""
        n, hist = self.count[k], self.hist[k]
        if not n:
            return (0, 0, 0, 0, 0, 0)
        out = []
        for q in (50, 95, 99, 100):
            want, seen = (n * q + 99) // 100, 0
            for b in range(self.BINS):
                seen += hist[b]
                if seen >= want:
                    out.append((b + 1) * self.BIN / 1000)
                    break
        return (n, self.total[k] / n / 1000) + tuple(out)

    def report(self, label, seconds):
        displayed = self.n - 1 if self.confirmed is None else self.confirmed
        print('BENCH %s updates=%d displayed/s=%.2f vblanks=%d (%.2f Hz)' % (
            label, self.n, displayed / seconds, self.vblanks, self.vblanks / seconds))
        for k, name in ((0, 'all   '), (1, 'normal'), (2, 'hud   '), (3, 'gc    ')):
            print('BENCH %s proc %s n=%d mean=%.2f p50=%.1f p95=%.1f p99=%.1f max=%.1f ms' % (
                (label, name) + self.summary(k)))
        if self.heap is not None:
            print('BENCH %s heap: %.0f net bytes per update, %d detected collections in %.1f s' % (
                label, self.allocated / max(1, self.allocating), self.collections, seconds))
        print('BENCH %s sync: mean=%.3f max=%.3f ms (COMMIT wait incl STATUS polling), '
              'stats FRAME_COUNT read mean=%.3f ms' % (
                  label, self.sync_us / max(1, self.n) / 1000, self.sync_max_us / 1000,
                  self.sample_us / max(1, self.n) / 1000))
        print('BENCH %s over 16.7 ms: %d, cadence (VBlanks per shown update) %s' % (
            label, self.over, ' '.join('%d:%d' % (c, self.cadence[c]) for c in range(16) if self.cadence[c])))


class Sakura:
    def __init__(self, d, pcm=True, copy=True, psg=True, font='/fonts/misaki8.kfnt', assets='sakura_assets',
                 opt=None):
        self.d = d
        self.opt = set(OPTS if opt is None else opt)
        # A kagura frozen into an older UF2 has no ext_writes(): one ext_write() per pair.
        self.ext_writes = getattr(d, 'ext_writes', None) or (
            lambda pairs: [d.ext_write(pairs[i], pairs[i + 1]) for i in range(0, len(pairs), 2)])
        self.lines = 180 if d.height == 180 else 240
        self.psram = bool(d.caps & R.CAPS_PSRAM)
        self.rscroll = bool(d.caps & R.CAPS_RSCROLL)
        self.copy = self.psram and copy
        self.piano = None                           # path of the C4 recording
        reason = ''
        if self.psram and pcm:
            path = assets + '/piano_c4.pcm'
            try:
                size = os.stat(path)[6]
                if size != PIANO_SAMPLES:
                    raise OSError('%s is %d bytes, not %d' % (path, size, PIANO_SAMPLES))
                self.piano = path
            except OSError as error:
                reason = ' (%r)' % error
        self.pcm = self.piano is not None
        # Taken now, before loading fragments the heap; released after the upload.
        self.window = bytearray(PIANO_WINDOW) if self.pcm else None
        self.text = Text(font)
        self.sound = Sound(d, self.pcm, psg)
        self.oam = bytearray(R.VRAM_OAM_SIZE)
        self.pal = bytearray(R.VRAM_PALETTE_SIZE)
        self.work = bytearray(4096)                  # map row/table and streaming piano output
        self.ext = bytearray(2 * (3 + 1 + 4 * (BANDS + 1) + 1 + 3))
        self.p = array('i', [0] * 5)
        self.wind_x = [0, 0, 0]                     # 1/16 px
        self.petal_x = array('H', [0] * 256)
        self.petal_phase = bytearray(256)
        self.hud_rows = [b'', b'']
        print('SAKURA CAPS 0x%02x, %d lines%s%s%s%s%s' % (
            d.caps, self.lines,
            '' if self.psram else ', no PSRAM: piano, aurora COPY and PSRAM counter off',
            '' if self.rscroll else ', no RSCROLL: one scroll for the whole screen, HUD off-screen',
            ', nopcm: melody on the PSG sine' + reason if self.psram and not self.pcm else '',
            '' if self.copy or not self.psram else ', nocopy: aurora still',
            '' if psg else ', nopsg: PSG voices off'))

    # ---- HUD and marquee

    def upload(self, first_tile, tiles, row=None):
        data = self.text.pack(tiles)
        if row is not None:                         # unchanged HUD rows are not sent again
            data = bytes(data)
            if data == self.hud_rows[row]:
                return
            self.hud_rows[row] = data
        self.d.write_memory(first_tile * 32, data)

    def draw_marquee(self):
        tx = self.text
        tx.clear(C_RULE)
        end = tx.text(4, MARQUEE, C_TEXT)
        if end > 512:
            print('SAKURA note: marquee is %d px, the last %d px are cut' % (end, end - 512))
        self.upload(TILE_MARQUEE, 64)

    def draw_hud(self, h):
        tx = self.text
        tx.clear(C_BAR)
        x = tx.text(3, 'KAGURA-9', C_TEXT)
        tx.text(x + 6, TITLE, C_NOTE)
        v = 'FPS %d.%d' % (h['fps10'] // 10, h['fps10'] % 10)
        tx.text(317 - tx.text(0, v, 0), v, C_GOOD if h['fps10'] >= 595 or h['status'] else C_BAD)
        self.upload(TILE_HUD, 40, 0)
        tx.clear(C_RULE)
        if h['status']:
            tx.text(3, h['status'], C_LABEL)
        else:
            x = tx.text(3, LABELS[0], C_LABEL)
            x = tx.text(x + 2, '256', C_TEXT)
            x = tx.text(x + 6, LABELS[1], C_LABEL)
            x = tx.text(x + 2, '%d' % h['overflow'], C_BAD if h['overflow'] else C_GOOD)
            x = tx.text(x + 6, LABELS[2], C_LABEL)
            x = tx.text(x + 2, '%d' % h['underrun'], C_BAD if h['underrun'] else C_GOOD)
            x = tx.text(x + 6, 'PSRAM', C_LABEL)
            x = tx.text(x + 3, '%.2fMB %dKB/s' % (h['psram_bytes'] / 1048576, h['psram_kbs']), C_TEXT)
            v = 'ERR %02X' % h['errors']
            tx.text(317 - tx.text(0, v, 0), v, C_BAD if h['errors'] or h['line_underrun'] else C_GOOD)
        self.upload(TILE_HUD + 40, 40, 1)

    def loading(self, what):
        self.draw_hud({'fps10': 0, 'status': what})
        self.d.commit()

    # HUD by difference (opt 'hud'): the same layout as draw_hud() as runs of
    # (x, text, colour); only the runs that differ from the last update mark
    # tiles dirty, and only glyphs over those tiles are drawn again.

    def hud_runs(self, h, row):
        m = self.hud_width
        if row == 0:
            v = 'FPS %d.%d' % (h['fps10'] // 10, h['fps10'] % 10)
            return ((3, 'KAGURA-9', C_TEXT), (3 + m('KAGURA-9') + 6, TITLE, C_NOTE),
                    (317 - m(v), v, C_GOOD if h['fps10'] >= 595 else C_BAD))
        runs = []
        x = 3
        for gap, s, colour in ((0, LABELS[0], C_LABEL), (2, '256', C_TEXT), (6, LABELS[1], C_LABEL),
                               (2, '%d' % h['overflow'], C_BAD if h['overflow'] else C_GOOD),
                               (6, LABELS[2], C_LABEL),
                               (2, '%d' % h['underrun'], C_BAD if h['underrun'] else C_GOOD),
                               (6, 'PSRAM', C_LABEL),
                               (3, '%.2fMB %dKB/s' % (h['psram_bytes'] / 1048576, h['psram_kbs']), C_TEXT)):
            runs.append((x + gap, s, colour))
            x += gap + m(s)
        v = 'ERR %02X' % h['errors']
        runs.append((317 - m(v), v, C_BAD if h['errors'] or h['line_underrun'] else C_GOOD))
        return runs

    def hud_row(self, row, runs):
        """Redraw and upload only the tiles of HUD row 0 or 1 whose glyphs
        changed since the last call (all 40 on the first). Returns tiles sent.
        The main loop runs the three steps on separate updates instead."""
        if not self.hud_prepare(row, runs):
            return 0
        self.hud_paint(row)
        self.hud_upload(row)
        return self.hud_end - self.hud_first

    def hud_prepare(self, row, runs):
        """Diff runs against what the row shows; keep the dirty tile span in
        hud_first/hud_end and the runs to paint. False when nothing changed."""
        width = self.hud_width
        old = self.hud_placed[row]
        if old is None:
            lo, hi = 0, 320
        else:
            lo, hi = 512, 0
            for run in runs:
                if run not in old:
                    lo, hi = min(lo, run[0]), max(hi, run[0] + width(run[1]) + 1)   # + 1: the shadow
            for run in old:
                if run not in runs:
                    lo, hi = min(lo, run[0]), max(hi, run[0] + width(run[1]) + 1)
            if hi <= lo:
                return False
        self.hud_placed[row] = runs
        self.hud_first, self.hud_end = max(0, lo // 8), min(40, (hi + 7) // 8)
        return self.hud_first < self.hud_end

    def hud_width(self, s):
        # HUD runs are either all ASCII (4 px each), or fixed Japanese labels.
        if 'hudascii' in self.opt and s not in HUD_WIDE:
            return len(s) * 4
        return self.text.layout(s)[1]

    def hud_paint(self, row):
        """Clear the dirty span of the row's strip, draw the runs over it, pack it."""
        tx = self.text
        layout, first, end = tx.layout, self.hud_first, self.hud_end
        a, b = first * 8, end * 8
        strip = self.hud_strips[row]
        K.clear_span(strip, a, b, C_BAR if row == 0 else C_RULE)
        clip, atlas = a | b << 12, tx.atlas
        for x, s, colour in self.hud_placed[row]:
            if 'hudascii' in self.opt and s not in HUD_WIDE:
                if x < b and x + len(s) * 4 >= a:
                    K.draw_run(strip, atlas, s, x | colour << 12 | 0x10000, clip)
                continue
            lay, width = layout(s)
            if x < b and x + width >= a:
                K.draw_run(strip, atlas, lay, x | colour << 12, clip)
        K.pack_span(strip, tx.packed, first, end)

    def hud_upload(self, row):
        first, end = self.hud_first, self.hud_end
        self.d.write_memory((TILE_HUD + 40 * row + first) * 32, memoryview(self.text.packed)[first * 32:end * 32])

    # ---- Raster bands

    def bands(self, t):
        """EXT pairs for the scroll, the raster table and COPY_SRC; returns their byte count."""
        e, n, lines = self.ext, 0, self.lines
        rs = self.rscroll
        sx = 0 if rs else t // 4
        # Line 0 starts on map row 30 (HUD); without RSCROLL the scenery is shown instead.
        for index, value in ((R.EXT_SCROLL_X_L, sx & 255), (R.EXT_SCROLL_X_H, sx >> 8 & 1),
                             (R.EXT_SCROLL_Y, 240 if rs else 0)):
            e[n], e[n + 1] = index, value
            n += 2
        if rs:
            e[n], e[n + 1] = R.EXT_RS_INDEX, 0
            n += 2
            for k in range(BANDS + 1):
                if k < BANDS:
                    by = BAND_Y[k]
                    line = by if lines == 240 else 16 + (by - 16) * (lines - 24) // 216
                    x = t * BAND_SPEED[k] // 16
                    if k == BANDS - 1:
                        x += div(sine64(t * 3), 16) + 4   # water shimmer
                    y = by - line
                else:                               # marquee on map row 0
                    line = lines - 8
                    x = t
                    y = 256 - line
                for index, value in ((R.EXT_RS_LINE, line), (R.EXT_RS_X_L, x & 255),
                                     (R.EXT_RS_X_H, x >> 8 & 1), (R.EXT_RS_Y, y & 255)):
                    e[n], e[n + 1] = index, value
                    n += 2
            e[n], e[n + 1] = R.EXT_RS_COUNT, BANDS + 1
            n += 2
        if self.copy:
            src = PSRAM_AURORA + ((t // 2) & 15) * 1024
            for i in range(3):
                e[n], e[n + 1] = R.EXT_COPY_SRC_L + i, src >> 8 * i & 255
                n += 2
        return n

    def bands_template(self):
        """Lay out the EXT table once (opt 'bands'); bands_fast() then fills
        only the values that change: the X of each band (or the global scroll
        X) and COPY_SRC. Indices, lines, Y and RS_COUNT stay as laid out."""
        self.ext_n = self.bands(0)
        # Pair j holds its value at byte 2j + 1; band k's RS_X_L is pair 5 + 4k, RS_X_H the next.
        self.ext_x = tuple(2 * (5 + 4 * k) + 1 for k in range(BANDS + 1)) if self.rscroll else None
        self.ext_src = self.ext_n - 5 if self.copy else None

    def bands_fast(self, t):
        e = self.ext
        xs = self.ext_x
        if xs:
            for k in range(BANDS):
                x = t * BAND_SPEED[k] // 16
                if k == BANDS - 1:
                    x += SHIMMER[(t * 3) & 63]      # water shimmer
                i = xs[k]
                e[i], e[i + 2] = x & 255, x >> 8 & 1
            i = xs[BANDS]                           # marquee
            e[i], e[i + 2] = t & 255, t >> 8 & 1
        else:
            sx = t // 4
            e[1], e[3] = sx & 255, sx >> 8 & 1
        i = self.ext_src
        if i is not None:
            src = PSRAM_AURORA + ((t // 2) & 15) * 1024
            e[i], e[i + 2], e[i + 4] = src & 255, src >> 8 & 255, src >> 16 & 255
        return self.ext_n

    # ---- Loading

    def upload_piano(self):
        """Resample the C4 recording to each note and upload a long and a short
        version to its PSRAM slot, each fading out over its last NOTE_FADE
        samples. Returns the bytes uploaded.

        Every version reads the recording from start to end, so one pass over
        the file feeds all 22 through a PIANO_WINDOW-byte window that moves
        PIANO_BLOCK bytes at a time, and each version's output goes straight
        to PSRAM. RAM never holds the whole recording or a whole note."""
        d, work, count = self.d, self.work, PIANO_SAMPLES
        versions = []                               # [base, length, step, fade, off, k, frac]
        for n in range(NOTES):
            step = int(2 ** (NOTE_SEMI[n] / 12) * 65536 + 0.5)
            for short in range(2):
                length = min(((count - 1) << 16) // step, NOTE_MAX[short])
                self.sound.note_len[n][short] = length
                base = PSRAM_SHORT_NOTES + n * SHORT_SLOT if short else PSRAM_NOTES + n * NOTE_SLOT
                versions.append([base, length, step, NOTE_FADE[short], 0, 0, 0])
        window = self.window
        q = array('i', [0] * 7)
        blocks = (count + PIANO_BLOCK - 1) // PIANO_BLOCK
        keep = PIANO_WINDOW - PIANO_BLOCK
        with open(self.piano, 'rb') as f:
            w0, filled = 0, read_fully(f, memoryview(window))
            while True:
                last = w0 + filled >= count
                # The highest source index a version may start a sample at: its k + 1 must be loaded too.
                kmax = count - 1 if last else w0 + filled - 2
                for v in versions:
                    base, length, step, fade, off, k, frac = v
                    while off < length and k <= kmax:
                        n = min(length - off, len(work), ((kmax - k + 1) * 65536 - 1 - frac) // step + 1)
                        q[0], q[1], q[2], q[3] = n, k - w0, frac, step
                        q[4], q[5], q[6] = length - off, fade, count - w0
                        k = w0 + K.resample(work, window, q)
                        frac = q[2]
                        d.write_memory(base + off, memoryview(work)[:n])
                        off += n
                    v[4], v[5], v[6] = off, k, frac
                if last:
                    break
                self.loading('%s %d/%d' % (LOADING[3], w0 // PIANO_BLOCK + 1, blocks))
                window[:keep] = memoryview(window)[PIANO_BLOCK:]   # keep == PIANO_BLOCK: no overlap
                w0 += PIANO_BLOCK
                filled = keep + read_fully(f, memoryview(window)[keep:])
        if any(v[4] != v[1] for v in versions):
            raise OSError('piano_c4.pcm ended early')
        d.fence()
        return sum(v[1] for v in versions)

    def load(self):
        d, work, tx = self.d, self.work, self.text
        t_load = ticks_ms()
        load_bytes = 0
        # Blank everything, then show the HUD while the rest loads.
        d.write_reg(R.REG_IRQ_ENABLE, 0)
        d.fill(R.VRAM_PATTERN_BASE, R.VRAM_PATTERN_SIZE, 0)
        d.fill(R.VRAM_MAP_BASE, R.VRAM_MAP_SIZE, 0)
        d.fill(R.VRAM_MAP_EXT_BASE, R.VRAM_MAP_EXT_SIZE, 0)
        d.fill(R.VRAM_OAM_BASE, R.VRAM_OAM_SIZE, 0)
        d.fence()
        build_palette(self.pal, 0)
        d.write_memory(R.VRAM_PALETTE_BASE, self.pal)
        d.ext_write(R.EXT_BACKDROP, 0)
        d.ext_write(R.EXT_RASTER_LINE, 255)
        d.write_reg(R.REG_DISPLAY_CTRL, ALL_ON)
        self.ext_writes(memoryview(self.ext)[:self.bands(0)])
        self.loading(LOADING[0])
        self.draw_marquee()
        build_scenery(d, tx.strip, tx.packed, work)
        make_petals(work)
        d.write_memory(TILE_PETAL * 32, memoryview(work)[:12 * 32])
        self.loading(LOADING[1] if self.psram else LOADING[2])
        for f in range(16 if self.psram else 1):
            make_aurora(f, tx.strip, tx.packed, work)
            d.write_memory(PSRAM_AURORA + f * 1024 if self.psram else TILE_AURORA * 32, memoryview(work)[:1024])
            load_bytes += 1024 if self.psram else 0
        if self.pcm:
            load_bytes += self.upload_piano()
            self.window = None
            gc.collect()
        self.loading(LOADING[4])
        self.sound.init(work)
        self.work = None                            # release the loading workspace
        print('SAKURA loaded in %d ms (%d bytes to PSRAM)' % (ticks_diff(ticks_ms(), t_load), load_bytes))
        for i in range(256):
            h = mix(i * 2654435761 + 7)
            self.petal_x[i] = h % 352
            self.petal_phase[i] = h >> 16 & 255
        d.write_reg(R.REG_IRQ_STATUS, 0xff)

    # ---- Main loop

    def run(self, seconds=0, stats=None):
        self.d.clear_errors()
        self.load()
        return self.loop(seconds, stats)

    def loop(self, seconds=0, stats=None):
        """The showcase until `seconds` pass (0: a key or Ctrl-C) after load();
        True on PASS. stats: a Stats to fill (adds one FRAME_COUNT read per
        update, excluded from its processing time)."""
        d, sound, p, opt = self.d, self.sound, self.p, self.opt
        track_sync = stats and hasattr(stats, 'sync_us')
        build_oam = K.build_oam
        if 'oam' in opt:
            from sakura_hud_viper import build_oam_fast
            build_oam = build_oam_fast
        o_order, o_hud, o_bands, o_regs = 'order' in opt, 'hud' in opt, 'bands' in opt, 'regs' in opt
        tr = d.transport
        b1 = bytearray(1)
        ab = bytearray(1)
        link = getattr(tr, 'link', None) if 'short' in opt and o_regs else None
        short = link is not None and hasattr(link, '_fast')
        if short:
            # Known byte-sized register operations; keep Link's ownership,
            # abort and exception translation. Call the method directly:
            # caching a bound _fast would allocate an argument array per call.
            short_kernel = link.k._short

            def reg(offset):
                return link._fast('read', short_kernel, 2, 0x80 | offset, 0)

            def audio_reg(index):
                link._fast('write', short_kernel, 2, 0x100 | R.REG_AUDIO_REG_INDEX, index)
                return link._fast('read', short_kernel, 2, 0x80 | R.REG_AUDIO_REG_DATA, 0)
        else:
            def reg(offset):                        # one bare link transaction (opt 'regs')
                tr.readinto(offset, b1)
                return b1[0]

            def audio_reg(index):
                ab[0] = index
                tr.write(R.REG_AUDIO_REG_INDEX, ab)
                tr.readinto(R.REG_AUDIO_REG_DATA, b1)
                return b1[0]
        read_reg = reg if o_regs else d.read_reg
        sound.audio_read = audio_reg if o_regs else d.audio_read
        sound.steady = 'hudround' in opt or 'steady' in opt
        rate = None
        if sound.steady:
            from sakura_hud_viper import bandwidth
            rate = bandwidth
        if 'steady' in opt:
            sound.reserve_views()
        palette = PaletteFrame() if 'palette' in opt else palette_frame
        if o_bands:
            self.bands_template()
            ext_view = memoryview(self.ext)[:self.ext_n]   # the length never changes: no view per update
        print('SAKURA GO - %s (opt %s)' % ('timed run' if seconds else 'press any key to stop',
                                           ' '.join(o for o in STEADY_OPTS if o in opt) or 'none'))
        pressed = _keyboard()
        hud = {'fps10': 600, 'status': None, 'overflow': 0, 'underrun': 0, 'line_underrun': 0,
               'psram_bytes': 0, 'psram_kbs': 0, 'errors': 0}
        fixed_hud = None
        if o_hud and 'hudbuf' in opt:
            from sakura_hud import Hud
            fixed_hud = Hud(self)
            for row in range(2):
                fixed_hud.update(hud, row)
        elif o_hud:                                 # the first full draw happens before the timed run
            self.hud_strips = [self.text.strip, bytearray(8 * 512)]
            self.hud_placed = [None, None]
            for row in range(2):
                self.hud_row(row, self.hud_runs(hud, row))
        copy_bytes = overflow_frames = device_errors = updates = skipped = 0
        confirmed, pending = 0, False
        ovf_index = ovf_line = stage = shown = 0
        t, gust = -1, 0
        aurora = bytes((TILE_AURORA * 32 & 255, TILE_AURORA * 32 >> 8, 0))
        oam, pal = self.oam, memoryview(self.pal)[:192]
        layer_wind = tuple(LAYERS[l * 7 + 5] for l in range(3))
        p[1] = self.lines
        interrupted = False
        start = ticks_ms()
        d.busy += 1   # COPY and the 'regs' accesses are bare transport transactions
        try:
            frame = read_reg(R.REG_FRAME_COUNT_L)
            start = ticks_ms()
            window, window_updates, window_bytes = ticks_us(), 0, 0
            while not (seconds and ticks_diff(ticks_ms(), start) >= seconds * 1000) and not pressed():
                t0 = ticks_us()
                flags = 0
                # Motion and music advance by the VBlanks since the last update.
                now = read_reg(R.REG_FRAME_COUNT_L)
                dt = min(8, max(1, (now - frame) & 255)) if t >= 0 else 1
                skipped += dt - 1
                frame = now
                for tick in range(t + 1, t + dt + 1):
                    wind = 6 + (120 - gust if gust > 60 else gust)
                    if gust:
                        gust -= 1
                    for l in range(3):
                        self.wind_x[l] = (self.wind_x[l] + wind * layer_wind[l] // 8) % WRAP
                    if sound.tick(tick, tick == t + dt):
                        gust = 120
                t += dt
                p[0] = t
                for l in range(3):
                    p[2 + l] = self.wind_x[l] // 16
                build_oam(oam, self.petal_x, self.petal_phase, SINE_BYTES, LAYERS, p)
                palette(self.pal, t)
                n = self.bands_fast(t) if o_bands else self.bands(t)
                updates += 1
                window_updates += 1
                waited = 0
                synced = sampled = 0
                try:
                    if not o_order:
                        # Queued behind the previous COMMIT, which applies them at the next VBlank.
                        d.write_memory(R.VRAM_OAM_BASE, oam)
                        d.write_memory(R.VRAM_PALETTE_BASE, pal)
                    # The raster table is refused while that COMMIT is pending. With opt 'order'
                    # the wait comes first, and this update's writes all go to the next frame.
                    w0 = ticks_us()
                    d.wait_status(R.STATUS_COMMIT_BUSY, 0)
                    if track_sync:
                        synced = ticks_diff(ticks_us(), w0)
                    if pending:
                        confirmed += 1
                        pending = False
                    if stats:
                        shown = reg(R.REG_FRAME_COUNT_L)
                    waited = ticks_diff(ticks_us(), w0)
                    if track_sync:
                        sampled = waited - synced
                    if o_order:
                        d.write_memory(R.VRAM_OAM_BASE, oam)
                        d.write_memory(R.VRAM_PALETTE_BASE, pal)
                    self.ext_writes(ext_view if o_bands else memoryview(self.ext)[:n])
                    if self.copy:
                        if short:
                            link._fast('write', short_kernel, 2, 0x340 | R.REG_VRAM_ADDR_L, TILE_AURORA * 32)
                            link._fast('write', short_kernel, 2, 0x240 | R.REG_LENGTH_L, 1024)
                            link._fast('write', short_kernel, 2, 0x100 | R.REG_COMMAND, R.CMD_COPY)
                        else:
                            tr.write(R.REG_VRAM_ADDR_L, aurora, True)
                            tr.write(R.REG_LENGTH_L, b'\x00\x04', True)
                        if o_regs and not short:
                            tr.write(R.REG_COMMAND, b'\x05')   # CMD_COPY
                        elif not o_regs:
                            d.write_reg(R.REG_COMMAND, R.CMD_COPY)
                        copy_bytes += 1024
                    sound.send()
                    d.audio_commit()
                    d.commit(wait=False)
                    pending = True
                    # Counters: sprite overflow (IRQ b5 with index/line).
                    irq = read_reg(R.REG_IRQ_STATUS)
                    if irq & R.IRQ_STATUS_SPR_OVERFLOW:
                        overflow_frames += 1
                        ovf_index = d.read_reg(R.REG_SPR_OVERFLOW_INDEX)
                        ovf_line = d.read_reg(R.REG_SPR_OVERFLOW_LINE)
                        d.write_reg(R.REG_IRQ_STATUS, R.IRQ_STATUS_SPR_OVERFLOW)
                    due = t // 15 != (t - dt) // 15
                    if o_hud:
                        # One chore per update: poll and count, then HUD row 1, then row 0.
                        # (Splitting each row over four more updates was measured: more
                        # updates ran over the frame, and fewer were shown.)
                        if due:
                            stage = 1
                        due = stage == 1
                    if due:
                        flags |= 1
                        # PCM status flags stay set until CLEAR, so polling here sees every channel fault.
                        for ch in range(2 if self.pcm else 0):
                            base = R.AUDIO_PCM_BASE + ch * R.AUDIO_PCM_STRIDE
                            if sound.audio_read(base + R.AUDIO_PCM_STATUS) & (R.AUDIO_PCM_STATUS_UNDERRUN |
                                                                              R.AUDIO_PCM_STATUS_MEMORY_ERROR):
                                hud['underrun'] += 1
                                d.audio_write(base + R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_CLEAR)
                        e = read_reg(R.REG_ERROR_CODE)
                        if e:
                            hud['errors'] |= e
                            if e & R.ERROR_CODE_LINE_UNDERRUN:
                                hud['line_underrun'] += 1
                            d.clear_errors()
                        us = ticks_us()
                        total = copy_bytes + sound.pcm_bytes() if self.psram else 0
                        elapsed = ticks_diff(us, window)
                        if elapsed >= 1000000:
                            hud['fps10'] = window_updates * 10000000 // elapsed
                            delta_bytes = total - window_bytes
                            if rate and 0 <= delta_bytes <= 0x3fffffff and elapsed < 0x8000000:
                                hud['psram_kbs'] = rate(delta_bytes, elapsed)
                            else:
                                hud['psram_kbs'] = delta_bytes * 1000000 // elapsed // 1024
                            window, window_updates, window_bytes = us, 0, total
                        hud['overflow'] = overflow_frames
                        hud['psram_bytes'] = total
                        if not o_hud:
                            self.draw_hud(hud)
                    if o_hud and stage:
                        flags |= 1
                        if stage == 1:                      # polled above
                            stage = 2
                        else:
                            row = 1 if stage == 2 else 0
                            if fixed_hud:
                                fixed_hud.update(hud, row)
                            else:
                                self.hud_row(row, self.hud_runs(hud, row))
                            stage = 3 if stage == 2 else 0
                except DeviceError as error:        # keep running, but show and count it
                    flags |= 4
                    hud['errors'] |= error.code
                    if error.code & R.ERROR_CODE_LINE_UNDERRUN:
                        hud['line_underrun'] += 1
                    device_errors += 1
                    d.clear_errors()
                if stats:
                    if sound.started:
                        flags |= 2
                    # Processing ends here; the statistics' own heap sampling is not part of it.
                    stats.add(ticks_diff(ticks_us(), t0) - waited, flags, shown)
                    if track_sync:
                        stats.sync_us += synced
                        stats.sample_us += sampled
                        stats.sync_max_us = max(stats.sync_max_us, synced)
                sound.started = False
        except KeyboardInterrupt:
            interrupted = True
        finally:
            d.busy -= 1
            sound.audio_read = d.audio_read
        secs = ticks_diff(ticks_ms(), start) / 1000
        ok = not overflow_frames and not hud['underrun'] and not hud['errors']
        psram = (copy_bytes + sound.pcm_bytes()) / 1048576 if self.psram else 0.0
        print('SAKURA %s: %d updates in %.1f s (%.2f updates/s, %d VBlanks skipped), sprite overflow frames %d%s, '
              'PCM underruns %d, line underruns %d, ERROR_CODE seen 0x%02x (%d driver reports), '
              'PSRAM %.2f MB (COPY %.2f MB)%s' % (
                  'PASS' if ok else 'FAIL', updates, secs, updates / secs if secs > 0 else 0.0, skipped,
                  overflow_frames, ' (last index %d line %d)' % (ovf_index, ovf_line) if overflow_frames else '',
                  hud['underrun'], hud['line_underrun'], hud['errors'], device_errors,
                  psram, copy_bytes / 1048576, ' (Ctrl-C)' if interrupted else ''))
        if stats:
            stats.seconds = secs
            if hasattr(stats, 'confirmed'):
                stats.confirmed = confirmed
        self.displayed = confirmed
        print('SAKURA display: %d COMMITs confirmed in %.1f s (%.2f displayed/s)' % (
              confirmed, secs, confirmed / secs if secs > 0 else 0.0))
        return ok

def run(seconds=0, device=None, mode='qspi', pcm=True, copy=True, psg=True,
        font='/fonts/misaki8.kfnt', assets='sakura_assets', opt=None):
    """Run the showcase for `seconds` (0: until a key or Ctrl-C); True on PASS
    (no sprite overflow, PCM underrun or device error).

    device=None connects with kagura.connect(mode=mode) and closes it after.
    pcm/copy/psg=False turn single loads off to isolate a fault: the melody
    then plays on a PSG sine, the aurora stops, or the PSG voices stay off.
    opt: the main-loop optimizations to use (OPTS, all by default); () runs
    the original loop for comparison. STEADY_OPTS additionally reserves sound
    transfer views before timing; the default caches used lengths lazily.
    """
    own = device is None
    d = kagura.connect(mode=mode) if own else device
    demo = None
    try:
        demo = Sakura(d, pcm, copy, psg, font, assets, opt)
        return demo.run(seconds)
    finally:
        try:
            if demo:
                demo.sound.stop()
        finally:
            if own:
                d.deinit()
