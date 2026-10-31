# SPDX-License-Identifier: Apache-2.0
"""Frame and HUD kernels loaded after the scene releases its work buffers."""
import micropython


@micropython.viper
def cents(value: int) -> int:
    """RP2 float32 APPROX '%.2f' of bytes/2**20; input 0..2**30-1.

    Reproduce the float32 input/scaling and parsed-decimal candidate choice.
    Candidate distances use 1/1024-byte units to stay inside native words.
    """
    # Match input int -> float32, then division by 2**20 (exact scaling).
    shift = 0
    top = value
    while top >= 0x1000000:
        top >>= 1
        shift += 1
    if shift:
        rest = value & ((1 << shift) - 1)
        half = 1 << (shift - 1)
        if rest > half or (rest == half and (top & 1)):
            top += 1
        value = top << shift
    fraction = (value & 0x3ffff) * 25
    low = (value >> 18) * 25 + (fraction >> 18)
    # The formatter first rounds the float32 multiplication by 100,
    # then the float32 addition of 0.5, before truncating to an integer.
    top = low
    exponent = 0
    while top >= 2:
        top >>= 1
        exponent += 1
    drop = exponent - 5
    remainder = fraction & 0x3ffff
    roundedlow = low
    if drop > 0:
        mantissa = remainder >> drop
        rest = remainder & ((1 << drop) - 1)
        half = 1 << (drop - 1)
        if rest > half or (rest == half and (mantissa & 1)):
            mantissa += 1
        remainder = mantissa << drop
    if remainder >= 0x40000:
        roundedlow += 1
        remainder -= 0x40000
    rounded = roundedlow + (1 if remainder >= 0x20000 else 0)
    best = 100000000
    result = rounded
    # The formatter compares float32-parsed decimal candidates. This can
    # move a threshold relative to rounding the exact input rational.
    for candidate in range(low, low + 2):
        if candidate == 0:
            distance = value << 10
        else:
            base = (candidate // 100) << 20
            numer = (candidate % 100) * 262144
            top = base + numer // 25
            shift = 0
            while top < 0x800000:
                top <<= 1
                shift -= 1
            while top >= 0x1000000:
                top >>= 1
                shift += 1
            if shift < 0:
                scaled = numer << (0 - shift)
                mantissa = (base << (0 - shift)) + scaled // 25
                rest = scaled % 25
                if rest * 2 > 25:
                    mantissa += 1
                distance = mantissa - (value << (0 - shift))
                if distance < 0:
                    distance = 0 - distance
                distance <<= shift + 10
            else:
                denominator = 25 << shift
                mantissa = (base >> shift) + numer // denominator
                rest = numer % denominator
                if rest * 2 > denominator or (rest * 2 == denominator and (mantissa & 1)):
                    mantissa += 1
                distance = (mantissa << shift) - value
                if distance < 0:
                    distance = 0 - distance
                distance <<= 10
        if distance < best or (distance == best and
                (candidate % 10 == 0 or (result % 10 != 0 and candidate == rounded))):
            best = distance
            result = candidate
    return result


@micropython.viper
def bandwidth(bytecount: int, elapsed: int) -> int:
    """Exact bytes*1000000//elapsed//1024 without heap big integers.

    Caller bounds: 0 <= bytecount <= 2**30-1, 1e6 <= elapsed < 2**27.
    Multiply by 15625 into two uint32 words, divide by elapsed*16.
    """
    value = uint(bytecount)
    denominator = uint(elapsed) << 4
    part = (value & 65535) * 15625
    highs = (value >> 16) * 15625 + (part >> 16)
    word = ((highs & 65535) << 16) | (part & 65535)
    highs >>= 16
    quotient = uint(0)
    for bit in range(31, -1, -1):
        highs = (highs << 1) | ((word >> bit) & 1)
        quotient <<= 1
        if highs >= denominator:
            highs -= denominator
            quotient |= 1
    return int(quotient)


@micropython.viper
def ascii_field(out, atlas, offset: int, text) -> int:
    o = ptr8(out)
    a = ptr8(atlas)
    s = ptr8(text)
    n = int(len(text))
    for i in range(n):
        p = offset + i * 4
        o[p] = (i * 4) & 255
        o[p + 1] = (i * 4) >> 8
        o[p + 2] = a[s[i]]
        o[p + 3] = 4
    return n


@micropython.viper
def number_field(out, atlas, offset: int, value: int, mode: int, extra: int) -> int:
    """Small ints: decimal, FPS tenths, ERR hex, or MB hundredths + KB/s."""
    o = ptr8(out)
    a = ptr8(atlas)
    prefix = ptr8(b'FPS ERR .MB KB/s')
    start = 0
    base = 10
    minimum = 1
    tail = value % 10
    if mode == 3:
        tail = value % 100
        value //= 100
    if mode == 1 or mode == 2:
        start = 4
        for i in range(4):
            o[offset + i * 4 + 2] = a[prefix[i + (4 if mode == 2 else 0)]]
        if mode == 1:
            value //= 10
        else:
            base = 16
            minimum = 2
    n = 0
    while value or n < minimum:
        digit = value % base
        code = 48 + digit if digit < 10 else 55 + digit
        o[offset + (start + n) * 4 + 2] = a[code]
        value //= base
        n += 1
    for i in range(n >> 1):
        left = offset + (start + i) * 4 + 2
        right = offset + (start + n - 1 - i) * 4 + 2
        temp = o[left]
        o[left] = o[right]
        o[right] = temp
    n += start
    if mode == 1:
        o[offset + n * 4 + 2] = a[46]
        o[offset + (n + 1) * 4 + 2] = a[48 + tail]
        n += 2
    if mode == 3:
        o[offset + n * 4 + 2] = a[46]
        o[offset + (n + 1) * 4 + 2] = a[48 + tail // 10]
        o[offset + (n + 2) * 4 + 2] = a[48 + tail % 10]
        for i in range(3):
            o[offset + (n + 3 + i) * 4 + 2] = a[prefix[9 + i]]
        n += 6
        start = n
        count = 0
        while extra or count == 0:
            o[offset + (start + count) * 4 + 2] = a[48 + extra % 10]
            extra //= 10
            count += 1
        for i in range(count >> 1):
            left = offset + (start + i) * 4 + 2
            right = offset + (start + count - 1 - i) * 4 + 2
            temp = o[left]
            o[left] = o[right]
            o[right] = temp
        n += count
        for i in range(4):
            o[offset + (n + i) * 4 + 2] = a[prefix[12 + i]]
        n += 4
    for i in range(n):
        p = offset + i * 4
        o[p] = (i * 4) & 255
        o[p + 1] = (i * 4) >> 8
        o[p + 3] = 4
    return n


@micropython.viper
def render(strip, atlas, glyphs, meta, oldglyphs, oldmeta, packed, rule: int, fine: int) -> int:
    """Diff fixed fields, redraw their tile span, pack from packed[0].

    meta has five words per field: x, glyph count, colour, glyph byte offset,
    width. Keeping the preceding metadata and glyphs preserves both sides
    of a shrinking or moving field without allocating runs or layouts.
    Returns first_tile * 256 + end_tile, or zero for an unchanged row.
    """
    st = ptr8(strip)
    at = ptr8(atlas)
    gl = ptr8(glyphs)
    m = ptr32(meta)
    og = ptr8(oldglyphs)
    om = ptr32(oldmeta)
    out = ptr8(packed)
    fields = int(len(meta)) // 5
    lo = 512
    hi = 0
    if om[1] > 65535:                               # -1 in a uint32 slot, also on 64-bit Viper
        lo = 0
        hi = 320
    for f in range(fields):
        k = f * 5
        offset = int(m[k + 3])
        n = int(m[k + 1]) * 4
        changed = 0
        if m[k] != om[k] or m[k + 1] != om[k + 1] or m[k + 2] != om[k + 2]:
            changed = 1
        else:
            for j in range(n):
                if gl[offset + j] != og[offset + j]:
                    if fine == 0:
                        changed = 1
                        break
                    p = offset + (j & -4)
                    x = int(m[k]) + int(gl[p]) + (int(gl[p + 1]) << 8)
                    end = x + int(gl[p + 3]) + 1
                    if x < lo:
                        lo = x
                    if end > hi:
                        hi = end
                    x = int(om[k]) + int(og[p]) + (int(og[p + 1]) << 8)
                    end = x + int(og[p + 3]) + 1
                    if x < lo:
                        lo = x
                    if end > hi:
                        hi = end
        if changed:
            x = int(m[k])
            end = x + int(m[k + 4]) + 1
            if x < lo:
                lo = x
            if end > hi:
                hi = end
            if om[k + 1] <= 65535:
                x = int(om[k])
                end = x + int(om[k + 4]) + 1
                if x < lo:
                    lo = x
                if end > hi:
                    hi = end
        for j in range(n):
            og[offset + j] = gl[offset + j]
        for j in range(5):
            om[k + j] = m[k + j]
    first = lo // 8
    endtile = (hi + 7) // 8
    if first < 0:
        first = 0
    if endtile > 40:
        endtile = 40
    if first >= endtile:
        return 0
    lo = first * 8
    hi = endtile * 8
    for y in range(8):
        c = rule if y == 7 else 2
        for x in range(lo, hi):
            st[y * 512 + x] = c
    for f in range(fields):
        k = f * 5
        x0 = int(m[k])
        if x0 >= hi or x0 + int(m[k + 4]) < lo:
            continue
        offset = int(m[k + 3])
        colour = int(m[k + 2])
        for g in range(int(m[k + 1])):
            p = offset + g * 4
            x = x0 + int(gl[p]) + (int(gl[p + 1]) << 8)
            width = int(gl[p + 3])
            if x >= hi or x + width < lo:
                continue
            r = int(gl[p + 2]) * 8 + 128
            for shadow in range(2):
                dx = 1 - shadow
                c = 1 if shadow == 0 else colour
                for y in range(8 - dx):
                    bits = int(at[r + y])
                    for b in range(width):
                        px = x + b + dx
                        if (bits & (0x80 >> b)) and px >= lo and px < hi:
                            st[(y + dx) * 512 + px] = c
    for tile in range(first, endtile):
        for y in range(8):
            row = y * 512 + tile * 8
            dest = (tile - first) * 32 + y * 4
            for x in range(4):
                out[dest + x] = (st[row + 2 * x] << 4) | st[row + 2 * x + 1]
    return first * 256 + endtile
