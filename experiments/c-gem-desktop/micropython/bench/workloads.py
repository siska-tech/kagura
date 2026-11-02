# SPDX-License-Identifier: Apache-2.0
"""Stage 3A workloads driven through the kagura_desktop binding.

The scene and operations of bench_native.c, written once for MicroPython:
bench_binding.py times them on the unix port. Uses only array and
kagura_desktop, so the same file runs on an embedded build.
"""
from array import array

import kagura_desktop as kd

HEX = ('00000000000000000000001100001188000118dd00118ddd0018dd210018dd11'
       '000000000000000011000000dd110000dddd1000ddddd100dd21dd10dd11dd10'
       '018ddddd018ddd6d018dddd60188dddd00188888000111110000000000000000'
       'ddddddd1ddd6ddd1666dddd1dddddd8188888810111111000000000000000000',
       '0000000000111000016661001666661016626661162666661666666616666666'
       '0000000000111000016661001666661066666610666666106666661066666610'
       '0166666600166666000166660000166600000166000000160000000100000000'
       '6666610066661000666100006610000061000000100000000000000000000000')
MENUS = (('Desk', ('About demo', '-', 'Quit')), ('Window', ('Close', 'Cycle')))
DIGITS = tuple(str(i) for i in range(10))
LIST = tuple('ABCDEF')


class Scene:
    def __init__(self):
        self.vram = bytearray(32000)
        d = self.d = kd.Desktop(320, 200, menus=MENUS)
        self.g = d.create_window('Gallery', 8, 16, 200, 120)
        self.gallery(0)
        self.spr = d.sprite(HEX[1])
        s = self.s2 = d.create_window('Sprite', 120, 40, 190, 150, bg=3)
        s.sprite(4, 4, self.spr, 6)
        s.sprite(108, 4, self.spr, 1)
        s.sprite(108, 24, self.spr, 2, 0)
        for i in range(16):
            s.fill_rect(108 + i % 4 * 14, 60 + i // 4 * 10, 12, 8, i)
        s.text(100, 102, 'COLOUR 6', 1, 3)
        self.rw = None
        d.present(self.vram)
        while d.poll() is not None:
            pass

    def gallery(self, value):
        g = self.g
        self.label = g.text(8, 8, DIGITS[value], 1, 2)
        self.panel = g.fill_rect(100, 40, 32, 32, 4)
        self.button = g.button(8, 40, 40, 14, 'GO')
        for k in range(6):
            g.text(140, 8 + k * 10, LIST[k], 1)


tick = 0


def workloads(sc, n_rects, iters=200):
    """Operations by name; iters bounds the precomputed per-iteration data."""
    d, g, s2, spr = sc.d, sc.g, sc.s2, sc.spr
    label, panel, button = sc.label, sc.panel, sc.button

    def idle(i):
        pass

    def full(i):
        d.invalidate(0, 0, 320, 200)

    def label_one_char(i):
        g.set_text(label, DIGITS[(i + 10) % 10])

    def button_press(i):
        g.set_flags(button, kd.BTN_PRESSED if i & 1 else 0)

    def panel_move(i):
        g.move_item(panel, 100 + (i & 1) * 4, 40)

    def rebuild(i):
        g.clear()
        sc.gallery((i + 10) % 10)

    def pixel(i):
        spr.set(5, 6, 9 if i & 1 else 3)

    def px16_calls(i):
        y, c = (i + 16) % 16, (i + 15) % 15 + 1
        for x in range(16):
            spr.set(x, y, c)

    px16 = [bytes(v for x in range(16) for v in (x, (i + 16) % 16, (i + 15) % 15 + 1)) for i in range(-4, iters)]

    def px16_batched(i):
        spr.set_pixels(px16[i + 4])

    imports = [bytes(0), bytes(0)]
    for k in range(2):
        t = d.sprite(HEX[k])
        imports[k] = t.data()
        t.free()

    def sprite_import(i):
        spr.load(imports[i & 1])

    def activate(i):
        (g if i & 1 else s2).activate()

    def move(i):
        s2.move(120 + (i & 1) * 8, 40)

    def open_close(i):
        w = d.create_window('Tmp', 60, 50, 120, 80)
        w.text(4, 4, 'temporary', 1)
        w.fill_rect(4, 20, 60, 20, 5)
        d.present(sc.vram)
        w.close()

    work = g.work()
    lst = [None] * 8
    seen = {}

    def feed(i):
        global tick
        x, y = work[0] + 60 + (i & 1), work[1] + 80
        tick += 1000
        d.pointer(kd.POINTER_DOWN, x, y, tick)
        tick += 100
        d.pointer(kd.POINTER_UP, x, y, tick)
        tick += 100
        d.key(kd.KEY_CHAR, 97, 0, tick)

    def events(i):   # poll(): a tuple per event
        feed(i)
        while True:
            e = d.poll()
            if e is None:
                break
            seen[e[0]] = seen.get(e[0], 0) + 1

    def events_into(i):   # poll_into(): no allocation
        feed(i)
        while d.poll_into(lst):
            k = lst[0]
            seen[k] = seen.get(k, 0) + 1

    quads = {}

    def rect_arrays(n, iters):
        return [array('h', [v for k in range(n) for v in ((k * 37 + i * 8 + 800) % 260, (k * 23) % 140,
                                                          12 + (k % 5) * 4, 8 + (k % 3) * 4)])
                for i in range(-4, iters)]

    def rects_calls(i):
        rw = sc.rw
        rw.clear()
        q, c = quads[n_rects][i + 4], (i + 16) % 16
        for k in range(0, 4 * n_rects, 4):
            rw.fill_rect(q[k], q[k + 1], q[k + 2], q[k + 3], c)

    def rects_batched(i):
        rw = sc.rw
        rw.clear()
        rw.fill_rects(quads[n_rects][i + 4], (i + 16) % 16)

    if n_rects:
        quads[n_rects] = rect_arrays(n_rects, iters)
    return {
        'idle': idle, 'full': full, 'label_one_char': label_one_char, 'button_press': button_press,
        'panel_move': panel_move, 'rebuild': rebuild, 'pixel': pixel, 'px16_calls': px16_calls,
        'px16_batched': px16_batched, 'sprite_import': sprite_import, 'activate': activate, 'move': move,
        'open_close': open_close, 'events': events, 'events_into': events_into,
        'rects_calls': rects_calls, 'rects_batched': rects_batched,
    }


TABLE = (
    ('idle', 'idle', 200, 0),
    ('full_redraw', 'full', 100, 0),
    ('label_one_char', 'label_one_char', 200, 0),
    ('button_press', 'button_press', 200, 0),
    ('panel_move_4px', 'panel_move', 200, 0),
    ('window_rebuild', 'rebuild', 200, 0),
    ('sprite_pixel', 'pixel', 200, 0),
    ('sprite_16px_calls', 'px16_calls', 200, 0),
    ('sprite_16px_batched', 'px16_batched', 200, 0),
    ('sprite_import', 'sprite_import', 100, 0),
    ('window_activate', 'activate', 100, 0),
    ('window_move_8px', 'move', 100, 0),
    ('window_open_close', 'open_close', 100, 0),
    ('events_3', 'events', 200, 0),
    ('events_3_poll_into', 'events_into', 200, 0),
    ('rects_1_calls', 'rects_calls', 200, 1),
    ('rects_16_calls', 'rects_calls', 200, 16),
    ('rects_256_calls', 'rects_calls', 50, 256),
    ('rects_16_batched', 'rects_batched', 200, 16),
    ('rects_256_batched', 'rects_batched', 50, 256),
)


def setup(fn_name, n_rects, iters=200):
    sc = Scene()
    if n_rects:
        sc.rw = sc.d.create_window('Rects', 4, 14, 312, 184)
        sc.d.present(sc.vram)
    return sc, workloads(sc, n_rects, iters)[fn_name]
