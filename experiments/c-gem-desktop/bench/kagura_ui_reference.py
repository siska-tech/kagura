# SPDX-License-Identifier: Apache-2.0
"""KAGURA-UI reference workloads on a PC, for comparison with kd_bench.

Runs the unchanged KAGURA-UI (software/micropython/kagura/ui) and the sprite
editor example on one of three backends:

  sdk       CPython only. The real SDK TileFramebuffer over the register
            model of tests/test_driver.py: dirty tiles and pattern payload are
            exactly what the SDK would send. Raster is pure Python here.
  framebuf  MicroPython only. Raster by the VM's native framebuf (C), standing
            in for the Viper kernels used on RP2040; measures widget, layout
            and VM overhead. No transport.
  mock      Both. KAGURA-UI's MockBackend (per-pixel Python loop).

The widget workloads are those of examples/ui_benchmark.py (same layout and
operations), whose RP2040 timings are recorded in docs/kagura-ui-damage.md;
the sprite workloads use examples/ui_sprite_editor.py as in #67.
Host times are not RP2040 times.

  python3 -I bench/kagura_ui_reference.py --backend sdk
  MICROPYPATH=software/micropython:software/micropython/examples \
      micropython bench/kagura_ui_reference.py --backend framebuf
"""
import sys

MP = sys.implementation.name == 'micropython'
if not MP:
    from pathlib import Path
    sys.dont_write_bytecode = True
    _root = Path(__file__).resolve().parents[3] / 'software/micropython'
    sys.path[:0] = [str(_root / 'tests'), str(_root), str(_root / 'examples')]
    FONT = str(_root / 'fonts/misaki8.kfnt')
    import test_driver  # noqa: E402,F401  (provides MicroPython's time.ticks_* on CPython)
else:
    FONT = 'software/micropython/fonts/misaki8.kfnt'

import time  # noqa: E402
from kagura.ui import App, Screen, Label, Button, Panel, ListView, Event, Theme, BitmapFont8  # noqa: E402
from kagura.ui.mock import MockBackend  # noqa: E402
from kagura_ja import Font  # noqa: E402
import ui_sprite_editor  # noqa: E402

# The two sample sprites of the C Studio (kd_sample_sprite_hex 0 and 1).
SAMPLES = (
    '00000000000000000000001100001188000118dd00118ddd0018dd210018dd11'
    '000000000000000011000000dd110000dddd1000ddddd100dd21dd10dd11dd10'
    '018ddddd018ddd6d018dddd60188dddd00188888000111110000000000000000'
    'ddddddd1ddd6ddd1666dddd1dddddd8188888810111111000000000000000000',
    '0000000000111000016661001666661016626661162666661666666616666666'
    '0000000000111000016661001666661066666610666666106666661066666610'
    '0166666600166666000166660000166600000166000000160000000100000000'
    '6666610066661000666100006610000061000000100000000000000000000000',
)


def now_us():
    return time.ticks_us() if MP else time.perf_counter_ns() // 1000


def elapsed(a, b):
    return time.ticks_diff(b, a) if MP else b - a


class FramebufBackend:
    def __init__(self):
        import framebuf
        self.width, self.height = 320, 240
        # Not "fb": the sprite editor takes that name to mean the SDK framebuffer.
        self._fb = framebuf.FrameBuffer(bytearray(320 * 240 // 2), 320, 240, framebuf.GS4_HMSB)

    def start(self, theme):
        pass

    def fill_rect(self, x, y, width, height, color):
        self._fb.fill_rect(x, y, width, height, color)

    def flush(self):
        return {}

    def close(self):
        pass


def make_app(backend_name, font):
    theme = Theme(BitmapFont8(font))
    if backend_name == 'sdk':
        import test_driver as T
        from kagura import Kagura, regs as R
        model = T.RegisterModel()
        model.ext[R.EXT_SCREEN_HEIGHT] = 240
        model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
        model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
        app = App(Kagura(model).probe(), exclusive=True, theme=theme)
    elif backend_name == 'framebuf':
        app = App(backend=FramebufBackend(), theme=theme)
    else:
        app = App(backend=MockBackend(), theme=theme)
    app.input = None
    return app


def gallery(app):
    """examples/ui_benchmark.py make(), widget for widget."""
    root = Screen(color=0)
    label = root.add(Label('0', x=8, y=8, width=64, height=8))
    panel = root.add(Panel(x=100, y=40, width=32, height=32, color=4))
    root.add(ListView(['A', 'B', 'C', 'D', 'E', 'F'], x=200, y=40, width=64, height=24))
    clicked = [0]

    def click():
        clicked[0] += 1
        label.set_text(str(clicked[0]))
    button = root.add(Button('GO', x=8, y=40, on_click=click))
    app.set_root(root)
    return label, panel, button


def flush_counts(app):
    stats = getattr(app, 'last_flush', None) or {}
    return stats.get('tiles', 0), stats.get('bytes', 0)


def measure(app, op, samples):
    times = []
    tiles = payload = 0
    for n in range(-3, samples):
        start = now_us()
        op(n)
        changed = app.step()
        t = elapsed(start, now_us())
        if n < 0:
            continue
        times.append(t)
        if changed:
            a, b = flush_counts(app)
            tiles += a
            payload += b
    times.sort()
    pick = lambda p: times[(len(times) - 1) * p // 100]  # noqa: E731
    return dict(p50=pick(50), p90=pick(90), max=times[-1], tiles=tiles / samples, bytes=payload / samples)


def main():
    backend = 'sdk' if not MP else 'framebuf'
    samples = 32
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--backend':
            backend = args[i + 1]
        elif a == '--samples':
            samples = int(args[i + 1])
    font = Font(FONT)
    results = []
    try:
        app = make_app(backend, font)
        label, panel, button = gallery(app)
        app.step()

        def full(n):
            app.damage((0, 0, 320, 240))

        def press(n):
            app.focus.set(button)
            app.events.post(Event('enter'))

        def text(n):
            label.set_text(str(n % 10))

        def move(n):
            panel.set_bounds(100 + (n % 2) * 4, 40)
        for name, op in (('full_redraw', full), ('button_press', press),
                         ('label_one_char', text), ('panel_move_4px', move)):
            results.append((name, measure(app, op, samples)))
        app.close()

        app = make_app(backend, font)
        ui_sprite_editor.build(app)
        editor = ui_sprite_editor.editor
        app.step()
        hexes = SAMPLES

        def pixel(n):
            editor.grid.put(5, 6, 9 if n & 1 else 3)

        def imp(n):
            editor.import_hex(hexes[n & 1])
        for name, op in (('sprite_full_redraw', full), ('sprite_pixel', pixel), ('sprite_import', imp)):
            results.append((name, measure(app, op, samples)))
        app.close()
    finally:
        font.close()
    impl = '%s %s' % (sys.implementation.name, '.'.join(str(v) for v in sys.implementation.version[:3]))
    print('# KAGURA-UI reference: backend %s, %s, %d samples (+3 warm-up)' % (backend, impl, samples))
    print('| workload | step p50 us | p90 | max | tiles | pattern bytes |')
    print('|---|---:|---:|---:|---:|---:|')
    for name, r in results:
        print('| %s | %d | %d | %d | %.1f | %.0f |' % (name, r['p50'], r['p90'], r['max'], r['tiles'], r['bytes']))


main()
