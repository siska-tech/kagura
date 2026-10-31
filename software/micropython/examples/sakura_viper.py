# SPDX-License-Identifier: Apache-2.0
"""Viper kernels of sakura.py: the per-frame OAM, HUD text and piano resampling.

Every index stays inside the buffers sakura.py allocates for them; the host
tests run this source on bounds-checked pointers (tests/test_sakura.py).
"""
import micropython

# Layer table rows (bytes): first sprite, count, size, fall speed, sway, wind, palette.
LAYER = 7


@micropython.viper
def build_oam(oam, xs, phases, sine, layers, p):
    """Write all 256 petal records into oam.

    xs: array('H') base X 0..351; phases: bytearray; sine: bytes of
    sine64(i) + 64 for i in 0..63; p: array('i') [t, lines, wind0, wind1,
    wind2] with wind_x // 16 >= 0 per layer.
    """
    o = ptr8(oam)
    px = ptr16(xs)
    pp = ptr8(phases)
    s = ptr8(sine)
    ly = ptr8(layers)
    q = ptr32(p)
    t = int(q[0])
    lines = int(q[1])
    for l in range(3):
        b = l * 7
        first = int(ly[b])
        count = int(ly[b + 1])
        size = int(ly[b + 2])
        speed = int(ly[b + 3])
        sway = int(ly[b + 4])
        palette = int(ly[b + 6])
        top = 16 - size
        field = lines - 8 - top
        wind = int(q[2 + l])
        for k in range(count):
            i = first + k
            ph = int(pp[i])
            y = top + (k * field * 16 // count + t * speed) // 16 % field
            v = sway * (int(s[(t // 2 + ph) & 63]) - 64)  # C truncates sway * sine / 64 toward zero
            if v < 0:
                v = 0 - (0 - v) // 64
            else:
                v = v // 64
            x = (int(px[i]) + wind + v + 352) % 352 - 16  # wraps through negative X
            attr = 1                                      # SPR_ON
            if size == 16:
                tile = 196 + ((t // 10 + ph) & 1) * 4
                attr |= 2                                 # SPR_16
                if ph & 1:
                    attr |= 4
            else:
                f = (t // 6 + ph) & 3                     # 0 1 2 1-mirrored: a tumbling petal
                tile = 192 + f
                mirror = ph & 1
                if f == 3:
                    tile = 193
                    mirror ^= 1
                if mirror:
                    attr |= 4                             # SPR_HFLIP
            if ph & 2:
                attr |= 8                                 # SPR_VFLIP
            # The HUD and marquee bars are opaque, so behind hides petals there.
            if l == 2 or y < 16 or y + size > lines - 8:
                attr |= 16                                # SPR_BEHIND
            e = i * 8
            o[e] = x & 255
            o[e + 1] = (x >> 8) & 3
            o[e + 2] = y & 255
            o[e + 3] = ((y >> 8) & 3) | (attr << 2)
            o[e + 4] = tile & 255
            o[e + 5] = ((tile >> 8) & 3) | (palette << 2)
            o[e + 6] = 0
            o[e + 7] = 0


@micropython.viper
def flame(key: int) -> int:
    """sakura.palette_frame()'s lantern colour rgb(15, 10 + h % 4, 3 + (h >> 8) % 3)
    for h = mix(key), in native 32-bit words: no big integers on the RP2040.
    The masks keep 64-bit Viper ports and the host model, whose integers never
    wrap, exact."""
    mask = (uint(0xffff) << 16) | uint(0xffff)
    h = uint(key) & mask
    h ^= h >> 16
    h = (h * uint((0x7feb << 16) | 0x352d)) & mask
    h ^= h >> 15
    h = (h * uint((0x846c << 16) | 0xa68b)) & mask
    h ^= h >> 16
    g = int(h & uint(3))
    b = int((h >> 8) & uint(0xffffff)) % 3
    return (15 << 8) | ((10 + g) << 4) | (3 + b)


@micropython.viper
def glyph(strip, x: int, rows, wc: int):
    """Draw 8 glyph rows (bit 7 leftmost) at x into the 8 x 512 strip with a
    drop shadow of colour 1; wc = width | colour << 8."""
    st = ptr8(strip)
    r = ptr8(rows)
    width = wc & 255
    colour = wc >> 8
    for shadow in range(2):
        dx = 1 - shadow
        c = 1 if shadow == 0 else colour
        for y in range(8 - dx):
            bits = int(r[y])
            for b in range(width):
                px = x + b + dx
                if (bits & (0x80 >> b)) and px >= 0 and px < 512:
                    st[(y + dx) * 512 + px] = c


@micropython.viper
def clear_span(strip, lo: int, hi: int, rule: int):
    """Clear a text span without keeping full-row fill buffers on the heap."""
    st = ptr8(strip)
    for y in range(8):
        colour = rule if y == 7 else 2
        for x in range(lo, hi):
            st[y * 512 + x] = colour


@micropython.viper
def draw_run(strip, atlas, layout, xc: int, clip: int):
    """glyph() for a whole run of text, drawing only pixels lo <= px < hi.

    atlas: 128 ASCII slots, then 8 rows per glyph slot; layout: 4 bytes per glyph (dx low, dx
    high, slot, width); xc = x | colour << 12; clip = lo | hi << 12.
    With xc bit 16 set, layout is an ASCII string (4 px per character).
    Redrawing the glyphs over a cleared span in their original order
    reproduces exactly what a full redraw leaves there."""
    st = ptr8(strip)
    at = ptr8(atlas)
    lay = ptr8(layout)
    x0 = xc & 0xfff
    colour = (xc >> 12) & 15
    lo = clip & 0xfff
    hi = (clip >> 12) & 0xfff
    ascii = (xc >> 16) & 1
    n = int(len(layout))
    if ascii == 0:
        n >>= 2
    for g in range(n):
        if ascii:
            x = x0 + g * 4
            width = 4
            r = int(at[lay[g]]) * 8 + 128
        else:
            x = x0 + int(lay[4 * g]) + (int(lay[4 * g + 1]) << 8)
            width = int(lay[4 * g + 3])
            r = int(lay[4 * g + 2]) * 8 + 128
        if x >= hi or x + width < lo:
            continue
        for shadow in range(2):
            dx = 1 - shadow
            c = 1 if shadow == 0 else colour
            for y in range(8 - dx):
                bits = int(at[r + y])
                for b in range(width):
                    px = x + b + dx
                    if (bits & (0x80 >> b)) and px >= lo and px < hi:
                        st[(y + dx) * 512 + px] = c


@micropython.viper
def pack_span(strip, out, first: int, end: int):
    """pack() of the cells first..end-1 only, at their own places in out."""
    st = ptr8(strip)
    o = ptr8(out)
    for t in range(first, end):
        for y in range(8):
            row = y * 512 + t * 8
            d = t * 32 + y * 4
            for x in range(4):
                o[d + x] = (st[row + 2 * x] << 4) | st[row + 2 * x + 1]


@micropython.viper
def pack(strip, out, tiles: int):
    """The first `tiles` 8x8 cells of the strip as 4bpp tiles in out."""
    st = ptr8(strip)
    o = ptr8(out)
    for t in range(tiles):
        for y in range(8):
            row = y * 512 + t * 8
            d = t * 32 + y * 4
            for x in range(4):
                o[d + x] = (st[row + 2 * x] << 4) | st[row + 2 * x + 1]


@micropython.viper
def resample(out, src, p) -> int:
    """Linear interpolation of the signed 8-bit src into out.

    p: array('i') [n, k, frac, step, remaining, fade, count]: n samples from
    position k + frac / 65536 advancing step / 65536 each; the last `fade`
    of the `remaining` samples fade to silence. Returns the next k and
    leaves the next frac in p[2].
    """
    o = ptr8(out)
    s = ptr8(src)
    q = ptr32(p)
    n = int(q[0])
    k = int(q[1])
    frac = int(q[2])
    step = int(q[3])
    remaining = int(q[4])
    fade = int(q[5])
    count = int(q[6])
    for i in range(n):
        a = int(s[k])
        if a > 127:
            a -= 256
        b = a
        if k + 1 < count:
            b = int(s[k + 1])
            if b > 127:
                b -= 256
        v = a + (((b - a) * frac) >> 16)
        left = remaining - i
        if left < fade:                                   # C truncates v * left / fade toward zero
            if v < 0:
                v = 0 - (0 - v) * left // fade
            else:
                v = v * left // fade
        o[i] = v & 255
        frac += step & 0xffff
        k += (step >> 16) + (frac >> 16)
        frac &= 0xffff
    q[2] = frac
    return k
