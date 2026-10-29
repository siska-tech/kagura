# SPDX-License-Identifier: Apache-2.0
"""Deterministic paint() regions shared by PC tests, Pico benchmark and diagnostics.

prepare(fb, name) draws walls (colour 1) around open pixels (colour 0) and
returns the seed. Only TileFramebuffer drawing APIs or mark_dirty() are used.
"""

NAMES = ('box8', 'box32', 'box160', 'full', 'corridor', 'maze', 'comb',
         'checker', 'checker8', 'noise')


def _lcg(state):
    return (state * 1664525 + 1013904223) & 0xFFFFFFFF


def _pattern(fb, rows):
    # rows: 8 tile-row bytes patterns (4 B each) repeated in every tile.
    tile = b''.join(rows)
    for n in range(1200):
        fb.buffer[n * 32:n * 32 + 32] = tile
    fb.mark_dirty()


def prepare(fb, name):
    if name == 'box8':
        fb.fill(1); fb.fill_rect(101, 99, 8, 8, 0)
        return 104, 102
    if name == 'box32':
        fb.fill(1); fb.fill_rect(61, 45, 32, 32, 0)
        return 70, 60
    if name == 'box160':
        fb.fill(1); fb.fill_rect(80, 60, 160, 120, 0)
        return 160, 120
    if name == 'full':
        fb.fill(0)
        return 160, 120
    if name == 'corridor':
        # One 1-pixel corridor zig-zagging through every even row (38 400 px).
        fb.fill(0)
        for y in range(1, 240, 2):
            fb.hline(0, y, 320, 1)
            fb.pixel(0 if y & 2 else 319, y, 0)
        return 0, 0
    if name == 'maze':
        # Binary-tree perfect maze: 80x60 cells, 3-pixel corridors, 1-pixel walls.
        fb.fill(1)
        state = 38
        for cy in range(60):
            for cx in range(80):
                x, y = cx * 4 + 1, cy * 4 + 1
                fb.fill_rect(x, y, 3, 3, 0)
                state = _lcg(state)
                if cy and (cx == 79 or state & 0x10000):
                    fb.fill_rect(x, y - 1, 3, 1, 0)
                elif cx < 79:
                    fb.fill_rect(x + 3, y, 1, 3, 0)
        return 1, 1
    if name == 'comb':
        # 160 one-pixel teeth hanging from the top row.
        fb.fill(0)
        for x in range(1, 320, 2):
            fb.vline(x, 1, 239, 1)
        return 0, 0
    if name == 'checker':
        # 1-pixel checkerboard: 4-connected region is one pixel.
        _pattern(fb, (b'\x01' * 4, b'\x10' * 4) * 4)
        return 0, 0
    if name == 'checker8':
        # 8x8 checker: open tiles touch only diagonally.
        for n in range(1200):
            fb.buffer[n * 32:n * 32 + 32] = bytes(32) if (n % 40 + n // 40) & 1 == 0 else b'\x11' * 32
        fb.mark_dirty()
        return 0, 0
    if name == 'noise':
        # About 40% walls: a large cluster full of holes and dead ends.
        state = 1200
        buffer = fb.buffer
        for n in range(38400):
            state = _lcg(state)
            buffer[n] = (16 if state >> 24 < 102 else 0) | (1 if state >> 16 & 255 < 102 else 0)
        fb.mark_dirty()
        x, y = 160, 120
        while fb.pixel(x, y):
            x += 1
        return x, y
    raise ValueError('unknown shape')
