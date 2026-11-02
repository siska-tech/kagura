# SPDX-License-Identifier: Apache-2.0
"""Independent PC surface versus SDK tile framebuffer, ownership and input."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_driver as T
import unittest
import io
from unittest.mock import patch
from kagura import Kagura, regs as R
from kagura.ui import (App, Widget, Screen, Panel, Label, Button, ProgressBar,
                       ListView, VBox, HBox, Event, EventQueue, TerminalInput,
                       Theme, BitmapFont8, FramebufferBackend, StdinInput)
from kagura.ui.mock import MockBackend
from kagura_ja import Font
from test_framebuffer import decode

ROOT = Path(__file__).resolve().parents[3]


def theme():
    return Theme(BitmapFont8(Font(str(ROOT / 'software/micropython/fonts/misaki8.kfnt'))))


def gallery(app):
    root = VBox(padding=8, spacing=6)
    label = root.add(Label('KAGURA-9\n日本語'))
    button = root.add(Button('START'))
    row = root.add(HBox(spacing=4))
    row.add(ProgressBar(value=30))
    row.add(Panel(width=20, height=12))
    app.set_root(root)
    return root, label, button


class UITests(unittest.TestCase):
    def setUp(self):
        self.backend = MockBackend()
        self.theme = theme()
        self.app = App(backend=self.backend, theme=self.theme)

    def tearDown(self):
        self.app.close()
        self.theme.font.source.close()

    def test_tree_and_cycle(self):
        parent, child = Widget(), Widget()
        self.assertIs(parent.add(child), child)
        self.assertIs(child.parent, parent)
        with self.assertRaises(ValueError): child.add(parent)
        with self.assertRaises(ValueError): parent.add(child)
        parent.remove(child)
        self.assertIsNone(child.parent)

    def test_fixed_layout_and_overflow(self):
        root = VBox(padding=2, spacing=3, width=20, height=20)
        a = root.add(Panel(width=30, height=8, color=4))
        b = root.add(Panel(width=10, height=10, color=5))
        self.app.set_root(root)
        self.app.step()
        self.assertEqual(a.bounds, (2, 2, 32, 10))
        self.assertEqual(b.bounds, (2, 13, 12, 23))
        self.assertEqual(self.backend.pixels[2*320+20], 0)
        self.assertEqual(self.backend.pixels[20*320+2], 0)
        row = HBox(padding=1, spacing=2)
        row.add(Panel(width=5, height=7)); row.add(Panel(width=9, height=3))
        self.assertEqual(row.measure(self.theme.font), (18, 9))

    def test_overlap_move_hide_remove_and_order(self):
        root = Screen(color=2)
        a = root.add(Panel(x=4, y=4, width=20, height=20, color=4))
        b = root.add(Panel(x=10, y=10, width=20, height=20, color=5))
        self.app.set_root(root); self.app.step()
        self.assertEqual(self.backend.pixels[12*320+12], 5)
        b.set_bounds(40, 10); self.app.step()
        self.assertEqual(self.backend.pixels[12*320+12], 4)
        a.set_visible(False); self.app.step()
        self.assertEqual(self.backend.pixels[12*320+12], 2)
        root.remove(b); self.app.step()
        self.assertEqual(self.backend.pixels[12*320+42], 2)

    def test_focus_disable_ancestor_and_buttons(self):
        root = VBox(spacing=2)
        count = []
        a = root.add(Button('A', on_click=lambda: count.append(1)))
        panel = root.add(VBox())
        b = panel.add(Button('B'))
        self.app.set_root(root); self.app.step()
        self.assertIs(self.app.focus.current, a)
        self.app.events.post(Event('enter')); self.app.step()
        self.assertEqual(count, [1]); self.assertTrue(a.pressed)
        self.app.step(); self.assertFalse(a.pressed)
        self.app.events.post(Event('tab')); self.app.step()
        self.assertIs(self.app.focus.current, b)
        panel.set_enabled(False); self.app.step()
        self.assertIs(self.app.focus.current, a)
        panel.set_enabled(True); self.app.step()
        self.app.events.post(Event('tab', shift=True)); self.app.step()
        self.assertIs(self.app.focus.current, b)
        panel.set_visible(False); self.app.step()
        self.assertIs(self.app.focus.current, a)

    def test_focus_scan_reuse_rescan_and_release(self):
        root = VBox()
        class Disabler(Button):
            def handle(widget, event):
                if event.key == 'down':
                    b.set_enabled(False)  # tree change inside handle, then unconsumed
                    return False
                return super().handle(event)
        a = root.add(Disabler('A')); b = root.add(Button('B')); c = root.add(Button('C'))
        self.app.set_root(root); self.app.step()
        self.assertEqual(self.app.focus.count, 3)
        # move() must rescan after the handler's change instead of reusing repair()'s scan.
        self.app.events.post(Event('down')); self.app.step()
        self.assertIs(self.app.focus.current, c)
        self.app.events.post(Event('tab', shift=True)); self.app.step()
        self.assertIs(self.app.focus.current, a)
        # Removed widgets are not retained by the reused result list.
        root.remove(c); self.app.step()
        self.assertEqual(self.app.focus.count, 1)  # b is still disabled
        self.assertNotIn(c, self.app.focus.found)
        root.remove(a); root.remove(b); self.app.step()
        self.assertIsNone(self.app.focus.current)
        self.assertEqual(self.app.focus.found, [None, None, None])
        self.app.set_root(None); self.app.step()
        self.assertEqual(self.app.focus.candidates(), 0)

    def test_queue_overflow_and_bounded_callbacks(self):
        q = EventQueue(2)
        self.assertTrue(q.post(Event('up'))); q.post(Event('down'))
        self.assertFalse(q.post(Event('enter')))
        self.assertEqual(q.dropped, 1)
        self.assertEqual(q.pop().key, 'up'); self.assertEqual(q.pop().key, 'down')
        self.assertIsNone(q.pop())
        b = Button('loop', on_click=lambda: self.app.events.post(Event('enter')))
        self.app.set_root(b); self.app.events.post(Event('enter'))
        self.app.step(); self.assertEqual(self.app.events._count, 1)

    def test_terminal_fragments_utf8_timeout_and_repeat(self):
        clock = [0]
        adapter, q = TerminalInput(clock=lambda: clock[0]), EventQueue()
        for fragment in (b'\x1b', b'[', b'A\x1b[Z\x1b[3~', '日本'.encode()[:2],
                         '日本'.encode()[2:], b'\r\r\x7f\x1b'):
            adapter.feed(fragment, q)
        clock[0] = 30001; adapter.expire(q)
        values = []
        while q._count: values.append(q.pop())
        self.assertEqual([e.key for e in values], ['up','tab','delete','text','text','enter','enter','backspace','escape'])
        self.assertEqual([e.text for e in values[3:5]], ['日','本'])
        self.assertTrue(values[1].shift)

    def test_japanese_clipping_newlines_golden(self):
        root = Screen(color=0)
        root.add(Label('日\n本', x=3, y=2, width=5, height=12))
        self.app.set_root(root); self.app.step()
        expected = bytearray(320*240)
        # Independent glyph bit reference, clipped to label rectangle.
        for i, ch in enumerate('日本'):
            rows = self.theme.font.source.glyph(ord(ch))
            for y in range(8):
                for x in range(5):
                    yy = 2 + i*8 + y
                    if yy < 14:
                        expected[yy*320+3+x] = (rows[y] >> (7-x)) & 1
        self.assertEqual(self.backend.pixels, expected)
        self.assertEqual(self.theme.font.measure('a\n日本'), (16,16))

    def test_noop_damage_and_error_retention(self):
        _, label, _ = gallery(self.app); self.app.step()
        n = self.backend.flushes
        with patch.object(self.app.focus, 'candidates', side_effect=AssertionError('idle focus scan')):
            self.assertFalse(self.app.step())
        self.assertEqual(self.backend.flushes, n)
        label.set_text('1'); self.backend.fail_flush = True
        with self.assertRaises(OSError): self.app.step()
        self.assertTrue(self.app._damage)
        self.backend.fail_flush = False; self.app.step()
        self.assertEqual(self.app._damage, [])
        self.assertEqual(self.backend.flushes, n + 1)

    def test_list_scroll_and_screen_switch(self):
        values = []
        root = Screen()
        view = root.add(ListView(['一','二','三','四'], height=16, on_select=lambda i,v: values.append((i,v))))
        self.app.set_root(root); self.app.step()
        for _ in range(3): self.app.events.post(Event('down'))
        self.app.events.post(Event('enter')); self.app.step()
        self.assertEqual((view.selected,view.top), (3,2)); self.assertEqual(values,[(3,'四')])
        second = Screen(color=4)
        self.app.set_root(second); self.app.step()
        self.assertEqual(self.backend.pixels, bytes([4])*(320*240))
        self.app.set_root(root); self.app.step()
        self.assertIs(self.app.focus.current,view)
        view.set_items([]); self.app.step()
        self.app.events.post(Event('enter')); self.app.step()
        self.assertEqual(view.selected,-1)
        self.assertEqual(values,[(3,'四')])

    def test_callback_error_propagates(self):
        def fail(): raise RuntimeError('callback')
        self.app.set_root(Button('fail',on_click=fail))
        self.app.events.post(Event('enter'))
        with self.assertRaisesRegex(RuntimeError,'callback'): self.app.step()
        self.assertTrue(self.app._damage)

    def test_ascii_fallback_and_missing_glyph(self):
        from viper_emulator import MonoFont
        with patch.dict(sys.modules, {'framebuf': T.types.SimpleNamespace(FrameBuffer=MonoFont, MONO_HLSB=3)}):
            font = BitmapFont8()
            expected = bytearray(8)
            MonoFont(expected,8,8,3).text('A',0,0,1)
            self.assertEqual(bytes(font.glyph('A')), expected)
            self.assertEqual(bytes(font.glyph('日')), bytes(font.glyph('?')))
        self.assertEqual(self.theme.font.glyph('\U0001f600'), self.theme.font.glyph('?'))

    def test_glyph_cache_hits_collisions_fallback_and_close(self):
        source = self.theme.font.source
        font = BitmapFont8(source, cache=4)
        calls = []
        original = source.glyph
        with patch.object(source, 'glyph', side_effect=lambda code: calls.append(code) or original(code)):
            first = font.glyph('日')
            self.assertIs(font.glyph('日'), first)  # hit: same object, no file lookup
            self.assertEqual(calls, [ord('日')])
            self.assertEqual(first, original(ord('日')))
            # A code in the same slot replaces it; the old code is looked up again.
            other = chr(ord('日') + 4)
            font.glyph(other); font.glyph('日')
            self.assertEqual(calls, [ord('日'), ord(other), ord('日')])
            # Missing glyphs cache their '?' fallback under the requested code.
            del calls[:]
            self.assertEqual(font.glyph('\U0001f600'), original(63))
            font.glyph('\U0001f600')
            self.assertEqual(calls, [0x1f600, 63])
        uncached = BitmapFont8(source, cache=0)
        with patch.object(source, 'glyph', side_effect=lambda code: calls.append(code) or original(code)):
            del calls[:]
            uncached.glyph('日'); uncached.glyph('日')
            self.assertEqual(calls, [ord('日'), ord('日')])
        for bad in (3, -1, 1.0, None):
            with self.assertRaises(ValueError): BitmapFont8(source, cache=bad)
        closed = Font(str(ROOT / 'software/micropython/fonts/misaki8.kfnt'))
        cached = BitmapFont8(closed)
        cached.glyph('日'); closed.close()
        with self.assertRaisesRegex(ValueError, 'closed'): cached.glyph('日')

    def test_button_two_fill_border_matches_rect_reference(self):
        from kagura.ui.render import Renderer
        for width, height in ((40,16),(3,3),(2,5),(1,1),(9,2)):
            for focused in (False, True):
                for pressed in (False, True):
                    button = Button('', width=width, height=height)
                    button.focused, button.pressed = focused, pressed
                    button.bounds = (5, 7, 5 + width, 7 + height)
                    new, old = MockBackend(32, 32), MockBackend(32, 32)
                    button.paint(Renderer(new), self.theme)
                    ref = Renderer(old)  # previous drawing: face fill, then 1 px rect
                    ref.fill_rect(5, 7, width, height, self.theme.pressed if pressed else self.theme.button)
                    ref.rect(5, 7, width, height, self.theme.focus if focused else self.theme.disabled)
                    self.assertEqual(new.pixels, old.pixels, (width, height, focused, pressed))

    def test_label_text_size_cached_until_text_or_font_changes(self):
        calls = []
        original = self.theme.font.measure
        with patch.object(self.theme.font, 'measure', side_effect=lambda t: calls.append(t) or original(t)):
            label = Label('日本')
            self.assertEqual(label.measure(self.theme.font), (16, 8))
            label.measure(self.theme.font)
            self.assertEqual(calls, ['日本'])
            label.set_text('ABC')
            self.assertEqual(label.measure(self.theme.font), (24, 8))
            label.text = 'A\nB'  # direct assignment is a new object, so it is measured again
            self.assertEqual(label.measure(self.theme.font), (8, 16))
            self.assertEqual(calls, ['日本', 'ABC', 'A\nB'])
            # Fixed size needs no text measurement at all.
            self.assertEqual(Button('長い文字列', width=30, height=12).measure(self.theme.font), (30, 12))
            self.assertEqual(len(calls), 3)
        other = BitmapFont8(self.theme.font.source, cache=0)
        self.assertEqual(label.measure(other), (8, 16))  # a different font is measured afresh

    def test_terminal_unknown_sequence_crlf_and_malformed_utf8(self):
        q, adapter = EventQueue(), TerminalInput()
        adapter.feed(b'\x1b[1;5A\r\nx\xff',q)
        self.assertEqual(q.pop().key,'enter')
        self.assertEqual(q.pop().text,'x')
        self.assertIsNone(q.pop())

    def test_stdin_poll_bytes_utf8_and_read_bound(self):
        class Poller:
            def register(p, stream, flags): p.stream = stream
            def poll(p, timeout):
                return bool(p.stream.tell() < len(p.stream.getbuffer()))
        stream = io.BytesIO('日'.encode('utf8')+b'\r\n\t\x1b[Z\x1b[3~')
        adapter, q = StdinInput(stream=stream,poller=Poller()), EventQueue()
        adapter.poll(q)
        self.assertEqual(q.pop().text,'日')
        self.assertEqual([q.pop().key for _ in range(4)],['enter','tab','tab','delete'])
        self.assertIsNone(q.pop())
        stream = io.BytesIO(b'a'*40)
        adapter = StdinInput(stream=stream,poller=Poller())
        adapter.poll(EventQueue(64))
        self.assertEqual(stream.tell(),32)

    def test_damage_raised_during_paint_survives(self):
        class Animated(Widget):
            def paint(widget, renderer, theme): widget.invalidate()
        root = Screen()
        root.add(Animated(width=16,height=16))
        self.app.set_root(root); self.app.step()
        self.assertEqual(self.app._damage,[(0,0,16,16)])
        self.app.step(); self.assertTrue(self.app._damage)

    def test_disjoint_damage_skips_the_gap(self):
        def build(app):
            root = Screen(color=2)
            a = root.add(Panel(x=4,y=4,width=20,height=20,color=4))
            b = root.add(Panel(x=200,y=4,width=20,height=20,color=5))
            app.set_root(root); app.step()
            return a, b
        single = App(backend=MockBackend(),theme=self.theme,damage_limit=1)
        try:
            self.app.damage_limit = 4
            for app in (self.app, single):
                a, b = build(app)
                app.backend.pixels[10*320+100] = 7  # sentinel between a and b
                a.invalidate(); b.invalidate()
                self.assertEqual(len(app._damage), 1 if app is single else 2)
                app.step()
            self.assertEqual(self.app.backend.pixels[10*320+100], 7)
            self.assertEqual(single.backend.pixels[10*320+100], 2)
        finally:
            single.close()

    def test_opaque_root_skips_duplicate_background_fill(self):
        fills = []
        original = self.backend.fill_rect
        def counted(x, y, w, h, color):
            fills.append((x, y, w, h, color)); original(x, y, w, h, color)
        self.backend.fill_rect = counted
        root = Screen(color=3, width=100, height=100)
        self.app.set_root(root); self.app.step()
        # Inside the opaque root: only the Screen's own fill, which also clears stale pixels.
        self.backend.pixels[10*320+10] = 7
        del fills[:]; self.app.damage((5,5,20,20)); self.app.step()
        self.assertEqual(fills, [(5,5,15,15,3)])
        self.assertEqual(self.backend.pixels[10*320+10], 3)
        # Partly outside the root: the background fill is still required.
        self.backend.pixels[120*320+120] = 7
        del fills[:]; self.app.damage((50,50,150,150)); self.app.step()
        self.assertEqual(fills[0], (50,50,100,100,self.theme.background))
        self.assertEqual(self.backend.pixels[120*320+120], self.theme.background)
        self.assertEqual(self.backend.pixels[60*320+60], 3)
        # Non-opaque roots keep the background fill.
        self.app.set_root(VBox()); self.app.step()
        del fills[:]; self.app.damage((5,5,20,20)); self.app.step()
        self.assertEqual(fills, [(5,5,15,15,self.theme.background)])

    def test_damage_merge_and_overflow_rules(self):
        app = App(backend=MockBackend(),theme=self.theme,damage_limit=2)
        app.damage((0,0,10,10)); app.damage((5,5,15,15))
        self.assertEqual(app._damage,[(0,0,15,15)])
        app.damage((15,0,20,5))  # shares an edge
        self.assertEqual(app._damage,[(0,0,20,15)])
        app.damage((20,15,30,30))  # corner contact only
        self.assertEqual(app._damage,[(0,0,20,15),(20,15,30,30)])
        app.damage((100,100,110,110))  # overflow joins the cheaper rectangle
        self.assertEqual(app._damage,[(0,0,20,15),(20,15,110,110)])
        app.damage((-5,-5,1000,3))  # clipped to the screen, then absorbs both
        self.assertEqual(app._damage,[(0,0,320,110)])
        self.assertEqual(App(backend=MockBackend()).damage_limit, 1)  # default keeps one rectangle
        for bad in (0,-1,1.5,None):
            with self.assertRaises(ValueError): App(backend=MockBackend(),damage_limit=bad)

    def test_multi_rect_matches_single_rect_and_full_repaint(self):
        def build(app):
            root = Screen(color=2)
            panels = [root.add(Panel(x=10+i*70,y=30,width=40,height=30,color=4+i)) for i in range(3)]
            label = root.add(Label('0',x=8,y=8,width=64,height=8))
            root.add(Button('A',x=8,y=100)); root.add(Button('B',x=250,y=200))
            root.add(ListView(['一','二','三','四'],x=150,y=120,width=64,height=16))
            app.set_root(root); app.step()
            return panels, label
        self.app.damage_limit = 4
        apps = [self.app, App(backend=MockBackend(),theme=self.theme,damage_limit=1)]
        trees = [build(app) for app in apps]
        seed = 12345
        try:
            for n in range(40):
                seed = (seed*1103515245+12345) & 0x7fffffff
                op, value = seed % 5, (seed >> 8) % 280
                for app, (panels, label) in zip(apps, trees):
                    panel = panels[value % 3]
                    if op == 0: panel.set_bounds(value, (value*7) % 200)
                    elif op == 1: panel.set_visible(not panel.visible)
                    elif op == 2: label.set_text(str(value) + ('\n日本' if value & 1 else ''))
                    elif op == 3: app.events.post(Event('tab', shift=bool(value & 1)))
                    else: app.events.post(Event('down'))
                    if n == 20:
                        app.backend.fail_flush = True
                        with self.assertRaises(OSError): app.step()
                        self.assertTrue(app._damage)
                        app.backend.fail_flush = False
                    app.step()
                    self.assertEqual(app._damage, [])
                self.assertEqual(apps[0].backend.pixels, apps[1].backend.pixels, n)
            expected = bytes(self.app.backend.pixels)
            self.app.damage((0,0,320,240)); self.app.step()
            self.assertEqual(bytes(self.app.backend.pixels), expected)
        finally:
            apps[1].close()

    def test_validation_and_outside_focus(self):
        with self.assertRaises(ValueError): Widget(width=-1)
        with self.assertRaises(ValueError): VBox(padding=-1)
        with self.assertRaises(ValueError): ProgressBar(maximum=0)
        with self.assertRaises(TypeError): Label(b'bytes')
        root = Screen()
        root.add(Button('offscreen',x=320,y=0))
        target = root.add(Button('target',x=0,y=0))
        self.app.set_root(root); self.app.step()
        self.assertIs(self.app.focus.current,target)

    def test_all_demo_builders(self):
        import ui_gallery, ui_monitor, ui_studio_mock
        for demo in (ui_gallery,ui_monitor,ui_studio_mock):
            update = demo.build(self.app)
            self.app.step()
            if demo is ui_gallery:
                self.app.events.post(Event('enter')); self.app.step()
                self.assertEqual(self.app.root.children[0].children[2].text,'Count: 1')
            self.app.events.post(Event('tab')); self.app.events.post(Event('enter'))
            self.app.step()
            if demo is ui_gallery:
                self.assertEqual(self.app.root.children[0].children[2].text,'Count: 0')
            if update is not None: update()

    def test_benchmark_one_hour_duration_uses_millisecond_wrap(self):
        import json
        import ui_benchmark as benchmark
        from contextlib import redirect_stdout
        period = 1 << 30
        def diff(a,b): return ((a-b+period//2)%period)-period//2
        # One hour crosses the ms tick origin. No real sleep in this PC test.
        clock = iter((period-10,5,3600000-10,3600000-10))
        output = io.StringIO()
        with patch.object(benchmark,'App',return_value=self.app):
            app, widgets = benchmark.make(None,self.theme.font.source)
        with patch.object(benchmark,'_now_ms',side_effect=lambda:next(clock)), \
                patch.object(benchmark,'elapsed',side_effect=diff), redirect_stdout(output):
            benchmark.run(app,widgets,samples=2,cycles=1,seconds=3600,profile='test')
        lines = output.getvalue().splitlines()
        finish = json.loads(lines[-1].split(' ',1)[1])
        self.assertEqual((finish['cycles'],finish['elapsed_ms']),(1,3600000))
        self.assertEqual(sum(line.startswith('UI_BENCH ') for line in lines),7)
        for seconds in (-1,86401,0.5):
            with self.assertRaises(ValueError): benchmark.run(app,widgets,seconds=seconds)
        for params in (dict(samples=2.5),dict(cycles=1.5)):
            with self.assertRaises(ValueError): benchmark.run(app,widgets,**params)

    def test_quiet_benchmark_retains_bounded_complete_telemetry(self):
        import ui_benchmark as benchmark
        from contextlib import redirect_stdout
        summary = benchmark.Summary()
        output = io.StringIO()
        with patch.object(benchmark,'App',return_value=self.app):
            app,widgets = benchmark.make(None,self.theme.font.source)
        with redirect_stdout(output):
            benchmark.run(app,widgets,samples=2,cycles=2,report=summary.report)
        self.assertEqual(output.getvalue(),'')
        self.assertEqual(summary.finish['cycles'],2)
        self.assertEqual(summary.heap['groups'],2)
        self.assertEqual(len(summary.workloads),7)
        for work in summary.workloads.values():
            self.assertEqual((work['groups'],work['samples']),(2,4))
        self.assertEqual(summary.workloads['idle']['tiles'],0)
        with self.assertRaises(ValueError): summary.report('UI_BENCH',dict(workload='unknown'))
        with self.assertRaises(ValueError): summary.report('unknown',{})


class MeasurementTests(unittest.TestCase):
    def test_soak_requires_completion_full_counts_and_console_restore(self):
        import copy
        import importlib.util
        spec = importlib.util.spec_from_file_location('ui_soak',ROOT/'tools/kagura-ui-soak.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = dict(done=True,error=None,console_paused=False,console_attached=True,
                      finish=dict(elapsed_ms=3600000,cycles=10),heap=dict(groups=10),
                      workloads={name:dict(groups=10,samples=320,tiles=0,pattern_payload_bytes=0)
                                 for name in ('idle','label','button','focus','move','scroll','screen')})
        module.validate_result(result,3600,32)
        changes = (lambda r:r.update(done=False),lambda r:r.update(error='KeyboardInterrupt'),
                   lambda r:r.update(console_paused=True),lambda r:r.update(console_attached=False),
                   lambda r:r['finish'].update(elapsed_ms=3599999),
                   lambda r:r['heap'].update(groups=9),lambda r:r['workloads'].pop('screen'),
                   lambda r:r['workloads']['label'].update(samples=319),
                   lambda r:r['workloads']['idle'].update(tiles=1,pattern_payload_bytes=32))
        for change in changes:
            invalid = copy.deepcopy(result)
            change(invalid)
            with self.assertRaises(RuntimeError): module.validate_result(invalid,3600,32)

    def test_device_timeout_interrupts_before_cleanup_and_keeps_utf8_log(self):
        import importlib.util
        import tempfile
        spec = importlib.util.spec_from_file_location('ui_standard',ROOT/'tools/kagura-ui-standard.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        actions = []
        class Transport:
            def __init__(self,*args,**kwargs):
                self.serial = T.types.SimpleNamespace()
                self.count = 0
            def enter_raw_repl(self,soft_reset): actions.append(('enter',soft_reset))
            def exec_raw(self,source,timeout,data_consumer):
                self.count += 1
                if self.count == 1: raise TimeoutError('simulated device timeout')
                actions.append(('cleanup','app.close()' in source))
                for byte in 'cleanup 日本語\n'.encode(): data_consumer(bytes((byte,)))
                return b'',b''
            def exit_raw_repl(self): actions.append('exit')
            def close(self): actions.append('close')
        class Output(io.StringIO):
            def reconfigure(self,**kwargs): pass
        port = T.types.SimpleNamespace(device='COM_TEST',vid=0x2e8a,serial_number='test')
        modules = {'mpremote':T.types.ModuleType('mpremote'),
                   'mpremote.transport_serial':T.types.SimpleNamespace(SerialTransport=Transport),
                   'serial':T.types.ModuleType('serial'), 'serial.tools':T.types.ModuleType('serial.tools'),
                   'serial.tools.list_ports':T.types.SimpleNamespace(comports=lambda:[port])}
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder)/'log.txt'
            argv = ['ui-standard','--port','COM_TEST','--expected-serial','test','--log',str(path)]
            with patch.dict(sys.modules,modules),patch.object(sys,'argv',argv),patch.object(sys,'stdout',Output()):
                with self.assertRaisesRegex(TimeoutError,'simulated device timeout'): module.main()
            self.assertIn('cleanup 日本語',path.read_text(encoding='utf8'))
            self.assertEqual(actions,[('enter',True),('enter',False),('cleanup',True),'exit','close'])

    def test_summary_preserves_percentile_scope_and_detects_incomplete_run(self):
        import importlib.util
        import json
        spec = importlib.util.spec_from_file_location('ui_summary',ROOT/'tools/summarize-kagura-ui.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        lines = []
        for cycle,median,free in ((0,10,100),(1,30,84)):
            value = dict(profile='glyph8',workload='label',cycle=cycle,samples=32,
                         tiles=2,pattern_payload_bytes=64,frame_us_p50_p95_p99=[median,40,50],
                         flush_us_p50_p95_p99=[2,3,4],latency_samples=2,
                         synthetic_invalidate_us_p50_p95_p99=[1,2,3])
            lines.append('UI_BENCH '+json.dumps(value)+'\n')
            lines.append('UI_HEAP '+json.dumps(dict(cycle=cycle,free=free,elapsed_ms=cycle*1000))+'\n')
        summary = module.summarize(iter(lines+['UI_BENCH {']))
        profile = summary['profiles']['glyph8']
        label = profile['workloads']['label']
        self.assertEqual(label['frame_us_percentile_ranges'],[[10,30],[40,40],[50,50]])
        self.assertEqual((label['samples'],label['tiles'],label['pattern_payload_bytes']),(64,4,128))
        self.assertEqual(label['latency_samples'],4)
        self.assertEqual(label['synthetic_invalidate_us_percentile_ranges'],[[1,1],[2,2],[3,3]])
        self.assertEqual((profile['heap']['first_free'],profile['heap']['last_free']),(100,84))
        self.assertIsNone(profile['finish'])
        self.assertFalse(summary['console_restored'])
        with self.assertRaises(ValueError): module.summarize(['UI_BENCH {\n'])
        lines += ['UI_FINISH {"elapsed_ms": 3600000}\n','STANDARD_RESTORED False True\n']
        self.assertTrue(module.summarize(lines)['console_restored'])


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.model = T.RegisterModel()
        self.model.ext[R.EXT_SCREEN_HEIGHT] = 240
        self.model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
        self.model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
        self.device = Kagura(self.model).probe()
        self.theme = theme()
        self.app = App(self.device, exclusive=True, theme=self.theme)

    def tearDown(self):
        self.app.close(); self.theme.font.source.close()

    def test_reference_python_and_viper_match(self):
        from kagura import framebuffer as F
        from viper_emulator import load
        reference = App(backend=MockBackend(),theme=self.theme)
        gallery(reference); gallery(self.app)
        reference.step(); self.app.step()
        self.assertEqual(decode(self.app.backend.fb.buffer), reference.backend.pixels)
        with patch.object(F, '_viper', load()):
            self.app.backend.fb.set_viper(True)
            for app in (reference, self.app):
                app.root.children[0].set_text('123\n日本語'); app.step()
            self.assertEqual(decode(self.app.backend.fb.buffer), reference.backend.pixels)

    def test_native_glyph_path_matches_reference_and_respects_partial_clip(self):
        from kagura import framebuffer as F
        from viper_emulator import load
        reference = App(backend=MockBackend(),theme=self.theme)
        try:
            with patch.object(F, '_viper', load()):
                self.app.start()
                for x,y,width,height in ((0,0,16,16),(3,5,16,16),(-3,2,16,16),
                                          (5,7,5,12),(315,235,16,16)):
                    for app in (reference,self.app):
                        root = Screen(color=4)
                        root.add(Label('日本\nA',x=x,y=y,width=width,height=height))
                        app.set_root(root)
                    with patch.object(self.app.backend.fb,'glyph8',wraps=self.app.backend.fb.glyph8) as draw:
                        reference.step(); self.app.step()
                        # Partly clipped glyphs also use glyph8, with masked rows; the
                        # MockBackend reference draws them with independent clipped runs.
                        self.assertGreater(draw.call_count,0)
                    self.assertEqual(decode(self.app.backend.fb.buffer),reference.backend.pixels)
                self.assertGreater(self.app.backend.fb.kernel_counts[4],0)
        finally:
            reference.close()

    def test_clipped_glyph_masks_every_edge_against_reference(self):
        from kagura import framebuffer as F
        from viper_emulator import load
        reference = App(backend=MockBackend(),theme=self.theme)
        try:
            with patch.object(F, '_viper', load()):
                self.app.start()
                for viper in (False, True):
                    self.app.backend.fb.set_viper(viper)
                    # Label clips cut glyphs on each side, both sides and the screen edges.
                    for x,y,width,height in ((3,5,13,11),(5,3,6,13),(-5,-3,18,9),(313,233,7,7),
                                              (20,20,1,1),(9,9,15,4)):
                        for app in (reference,self.app):
                            root = Screen(color=4)
                            root.add(Label('日本\nAg',x=x,y=y,width=width,height=height,color=9))
                            app.set_root(root)
                        reference.step(); self.app.step()
                        self.assertEqual(decode(self.app.backend.fb.buffer),reference.backend.pixels,(viper,x,y))
                calls = self.app.backend.fb.kernel_counts[4]
                self.assertGreater(calls,0)
                # Partial glyphs no longer fall back to per-run fill_rect calls.
                with patch.object(self.app.backend,'fill_rect',wraps=self.app.backend.fill_rect) as fill:
                    self.app.damage((0,0,320,240)); self.app.step()
                    self.assertEqual(fill.call_count,1)  # the Screen background only
        finally:
            reference.close()

    def test_glyph_path_falls_back_for_older_sdk_and_sequence_fonts(self):
        self.app.set_root(Label('日本',width=16,height=8))
        self.app.step()
        expected = bytes(self.app.backend.fb.buffer)
        with patch.object(self.app.backend.fb,'glyph8',None):
            self.app.damage((0,0,320,240)); self.app.step()
        self.assertEqual(bytes(self.app.backend.fb.buffer),expected)
        original = self.theme.font.glyph
        with patch.object(self.theme.font,'glyph',side_effect=lambda ch:list(original(ch))):
            self.app.damage((0,0,320,240)); self.app.step()
        self.assertEqual(bytes(self.app.backend.fb.buffer),expected)

    def test_exclusivity_and_mode(self):
        with self.assertRaises(ValueError): App(self.device)
        self.app.start()
        other = App(self.device,exclusive=True)
        with self.assertRaises(RuntimeError): other.start()
        self.app.close(); other.start(); other.close()
        self.device.height = 180
        with self.assertRaises(ValueError): App(self.device,exclusive=True).start()

    def test_builtin_ascii_reuses_sdk_text(self):
        from viper_emulator import MonoFont
        self.app.theme = Theme()
        self.app.set_root(Label('ASCII',width=40,height=8))
        reference = App(backend=MockBackend(),theme=Theme())
        reference.set_root(Label('ASCII',width=40,height=8))
        framebuf = T.types.SimpleNamespace(FrameBuffer=MonoFont,MONO_HLSB=3)
        with patch.dict(sys.modules,{'framebuf':framebuf}):
            self.app.start()
            with patch.object(self.app.backend.fb,'text',wraps=self.app.backend.fb.text) as text:
                self.app.step()
                text.assert_called_once_with('ASCII',0,0,1)
            reference.step()
        self.assertEqual(decode(self.app.backend.fb.buffer),reference.backend.pixels)

    def test_dirty_partial_no_transfer_on_idle(self):
        self.app.set_root(Label('0', width=16, height=8))
        self.app.step(); self.model.calls.clear()
        self.assertFalse(self.app.step()); self.assertEqual(self.model.calls,[])
        self.app.root.set_text('1'); self.app.step()
        self.assertGreater(self.app.last_flush['tiles'],0)
        self.assertLessEqual(self.app.last_flush['tiles'],2)
        self.assertEqual(self.app.last_flush['bytes'],self.app.last_flush['tiles']*32)

    def test_disjoint_damage_reduces_sdk_dirty_tiles(self):
        results = []
        for limit in (4, 1):
            app = App(self.device,exclusive=True,theme=self.theme,damage_limit=limit)
            try:
                root = Screen(color=0)
                left = root.add(Label('0',x=8,y=8,width=16,height=8))
                root.add(Panel(x=100,y=40,width=32,height=32,color=4))
                right = root.add(Label('0',x=280,y=200,width=16,height=8))
                app.set_root(root); app.step()
                left.set_text('1'); right.set_text('1'); app.step()
                results.append((app.last_flush['tiles'], decode(app.backend.fb.buffer)))
            finally:
                app.close()
        (multi, multi_pixels), (single, single_pixels) = results
        self.assertEqual(multi_pixels, single_pixels)
        self.assertLessEqual(multi, 4)
        self.assertGreater(single, multi)

    def test_damage_benchmark_crc_equivalence_and_summary(self):
        import importlib.util, json
        import ui_damage_benchmark as B
        spec = importlib.util.spec_from_file_location('kagura_ui_damage', ROOT / 'tools/kagura-ui-damage.py')
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        # The source sent to the RP2040 must define the same App without relative imports.
        namespace = {}
        exec(compile(tool.branch_app_source(), 'app.py', 'exec'), namespace)
        self.assertTrue(hasattr(namespace['App'], '_add_damage'))
        # --framebuffer: the SDK source runs in its own globals and is handed to the UI.
        from kagura.framebuffer import TileFramebuffer
        fb_namespace = {'__name__': 'damage_framebuffer'}
        exec(compile(tool.framebuffer_source(), 'framebuffer.py', 'exec'), fb_namespace)
        self.assertIsNot(fb_namespace['TileFramebuffer'], TileFramebuffer)
        app, scene = B.make(namespace['App'], self.device, self.theme.font.source, exclusive=True)
        app.backend.fb = fb_namespace['TileFramebuffer'](self.device)
        lines = []
        try:
            B.run(app, scene, samples=4, rounds=2,
                  report=lambda tag, value: lines.append(tag + ' ' + json.dumps(value)))
            self.assertIs(type(app.backend.fb), fb_namespace['TileFramebuffer'])
        finally:
            app.close()
        rows = [json.loads(line.split(' ', 1)[1]) for line in lines if line.startswith('UI_DAMAGE ')]
        self.assertEqual(len(rows), 2 * 2 * len(B.WORKLOADS))
        tiles = {(r['workload'], r['limit']): r['tiles'] for r in rows if r['round'] == 0}
        self.assertLess(tiles[('focus', 4)], tiles[('focus', 1)])
        self.assertLess(tiles[('glyphcut', 4)], tiles[('glyphcut', 1)])
        self.assertEqual(tiles[('idle', 4)], 0)
        table = tool.summarize(lines)
        self.assertIn('| glyphcut | 4 |', table)
        with self.assertRaises(SystemExit): tool.summarize(lines[:-1])

    def test_sdk_flush_error_keeps_dirty_and_damage(self):
        self.app.set_root(Label('0')); self.app.step()
        self.app.root.set_text('1')
        with patch.object(self.device,'fence',side_effect=OSError('fence')):
            with self.assertRaises(OSError): self.app.step()
        self.assertGreater(sum(self.app.backend.fb.dirty),0)
        self.assertTrue(self.app._damage)
        self.app.step(); self.assertEqual(sum(self.app.backend.fb.dirty),0)

    def test_console_pause_restore_and_retry(self):
        class Console:
            def __init__(c, device):
                c.screen = T.types.SimpleNamespace(device=device)
                c.paused, c._attached = False, True
                c.log, c.fail = [], False
            def pause(c): c.paused=True; c.log.append('pause')
            def detach(c): c._attached=False; c.log.append('detach')
            def resume(c):
                if c.fail: raise OSError('restore')
                c.paused=False; c.log.append('resume')
            def attach(c): c._attached=True; c.log.append('attach')
        console = Console(self.device)
        backend = FramebufferBackend(self.device,console)
        backend.start(self.theme)
        self.assertTrue(console.paused); self.assertFalse(console._attached)
        console.fail=True
        with self.assertRaises(OSError): backend.close()
        self.assertTrue(backend.active)
        console.fail=False; backend.close()
        self.assertEqual(console.log,['pause','detach','resume','attach'])

    def test_memory_error_does_not_acquire_lease(self):
        from kagura import framebuffer as F
        with patch.object(F,'TileFramebuffer',side_effect=MemoryError('allocation')):
            with self.assertRaises(MemoryError): self.app.start()
        self.assertFalse(self.app.backend.active)
        self.assertNotIn(self.device,FramebufferBackend._owners)
        self.app.start()

    def test_mixed_legacy_sdk_rejected_before_graphics_io(self):
        self.model.calls.clear()
        with patch.object(type(self.device), '_link', None):
            with self.assertRaisesRegex(RuntimeError, 'SDK version mismatch'):
                self.app.start()
        self.assertEqual(self.model.calls, [])
        self.assertIsNone(self.app.backend.fb)
        self.assertFalse(self.app.backend.active)

    def test_sdk_raster_capability_dependency_preflight(self):
        self.device.caps &= ~R.CAPS_RSCROLL
        self.model.calls.clear()
        with self.assertRaises(NotImplementedError): self.app.start()
        self.assertEqual(self.model.calls, [])
        self.assertIsNone(self.app.backend.fb)

    def test_interrupted_console_pause_restores_owner(self):
        class Console:
            def __init__(c):
                c.screen = T.types.SimpleNamespace(device=self.device)
                c.paused,c._attached = False,True
            def pause(c):
                c.paused = True
                raise KeyboardInterrupt()
            def resume(c): c.paused = False
            def detach(c): c._attached = False
            def attach(c): c._attached = True
        console = Console()
        backend = FramebufferBackend(self.device,console)
        self.model.calls.clear()
        with self.assertRaises(KeyboardInterrupt): backend.start(self.theme)
        self.assertFalse(console.paused)
        self.assertTrue(console._attached)
        self.assertFalse(backend.active)
        self.assertNotIn(self.device,FramebufferBackend._owners)
        self.assertEqual(self.model.calls,[])


def sprite_pixels(data, width, height):
    """Independent TILE4 decoder: row-major 8x8 tiles of 32 B; left pixel in bits 7..4."""
    image = [[0] * width for _ in range(height)]
    for tile in range(width * height // 64):
        ox, oy = tile % (width // 8) * 8, tile // (width // 8) * 8
        for yy in range(8):
            for pair in range(4):
                value = data[tile * 32 + yy * 4 + pair]
                image[oy + yy][ox + pair * 2] = value >> 4
                image[oy + yy][ox + pair * 2 + 1] = value & 15
    return image


class RecordingBackend(MockBackend):
    def __init__(self):
        super().__init__()
        self.fills = []

    def fill_rect(self, x, y, width, height, color):
        self.fills.append((x, y, x + width, y + height))
        super().fill_rect(x, y, width, height, color)


class CanvasTests(unittest.TestCase):
    def setUp(self):
        self.backend = RecordingBackend()
        self.theme = theme()
        self.app = App(backend=self.backend, theme=self.theme)

    def tearDown(self):
        self.app.close()
        self.theme.font.source.close()

    def editor(self, x=40, y=24, zoom=8, sprite=None, **kwargs):
        from kagura.ui import SpriteCanvas
        root = Screen(color=2)
        canvas = root.add(SpriteCanvas(sprite, x=x, y=y, zoom=zoom, **kwargs))
        self.app.set_root(root)
        self.app.step()
        return canvas

    def expected(self, canvas, pixel):
        """Screen colour at (px, py) from the sprite alone, cursor outline included."""
        def at(px, py):
            left, top, z = canvas.bounds[0], canvas.bounds[1], canvas.zoom
            cx, cy = (px - left) // z, (py - top) // z
            if canvas.focused and z >= 3 and (cx, cy) == canvas.cursor:
                if (px - left) % z in (0, z - 1) or (py - top) % z in (0, z - 1):
                    return self.theme.focus
            return pixel(cx, cy) or canvas.backdrop
        return at

    def assert_screen(self, canvas, pixel):
        at = self.expected(canvas, pixel)
        left, top, right, bottom = canvas.bounds
        for py in range(max(0, top), min(240, bottom)):
            for px in range(max(0, left), min(320, right)):
                self.assertEqual(self.backend.pixels[py * 320 + px], at(px, py), (px, py))

    def test_sprite4_layout_matches_reference_decoder(self):
        from kagura.ui import Sprite4
        s = Sprite4(16, 16)
        self.assertEqual(len(s.export()), 128)
        # Fixed vectors: nibble order, tile order TL, TR, BL, BR (= 16x16 sprite patterns).
        s.set(0, 0, 1); s.set(1, 0, 2)
        self.assertEqual(s.data[0], 0x12)
        s.set(8, 0, 3); self.assertEqual(s.data[32], 0x30)
        s.set(0, 8, 4); self.assertEqual(s.data[64], 0x40)
        s.set(15, 15, 5); self.assertEqual(s.data[127], 0x05)
        s.set(7, 1, 6); self.assertEqual(s.data[4 + 3], 0x06)
        # Pseudo-random pixels over several sizes against the independent decoder.
        for width, height in ((8, 8), (16, 16), (24, 8), (16, 32)):
            s = Sprite4(width, height)
            want = [[0] * width for _ in range(height)]
            seed = 12345
            for _ in range(width * height * 2):
                seed = (seed * 1103515245 + 12345) & 0x7fffffff
                x, y, c = seed % width, (seed >> 8) % height, (seed >> 16) & 15
                s.set(x, y, c); want[y][x] = c
            self.assertEqual(sprite_pixels(s.export(), width, height), want)
            self.assertEqual([[s.get(x, y) for x in range(width)] for y in range(height)], want)

    def test_sprite4_validation_and_import_export(self):
        from kagura.ui import Sprite4
        for args in ((0, 16), (12, 16), (16, -8)):
            with self.assertRaises(ValueError): Sprite4(*args)
        for args in ((16.0, 16), (True, 16)):
            with self.assertRaises(TypeError): Sprite4(*args)
        s = Sprite4()
        s.set(3, 4, 9)
        before = s.export()
        for args, error in (((16, 0, 1), IndexError), ((0, -1, 1), IndexError), ((0, 0, 16), ValueError),
                            ((0, 0, -1), ValueError), ((0, 0, True), TypeError), ((0.0, 0, 1), TypeError)):
            with self.assertRaises(error): s.set(*args)
        with self.assertRaises(ValueError): s.load(bytes(127))
        with self.assertRaises(TypeError): s.load([0] * 128)
        self.assertEqual(s.export(), before)
        self.assertFalse(s.set(3, 4, 9))
        self.assertTrue(s.set(3, 4, 0))
        data = bytes(range(128))
        t = Sprite4(data=data)
        self.assertEqual(t.export(), data)
        self.assertIsNot(t.data, data)
        u = Sprite4(); u.load(bytearray(t.export()))
        self.assertEqual(sprite_pixels(u.export(), 16, 16), sprite_pixels(data, 16, 16))

    def test_sprite4_source_blits_with_transparent_zero(self):
        from kagura import framebuffer as F
        from kagura.framebuffer import TileFramebuffer
        from kagura.ui import Sprite4
        from kagura.ui.canvas import TILE4
        self.assertEqual(TILE4, F.TILE4)
        model = T.RegisterModel()
        model.ext[R.EXT_SCREEN_HEIGHT] = 240
        model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
        model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
        fb = TileFramebuffer(Kagura(model).probe())
        s = Sprite4(data=bytes((k * 37) & 0xff for k in range(128)))
        want = sprite_pixels(s.export(), 16, 16)
        for x, y in ((40, 24), (43, 21), (-5, 230)):
            fb.fill(7)
            fb.blit(s.source(), x, y, key=0)
            image = decode(fb.buffer)
            for sy in range(16):
                for sx in range(16):
                    px, py = x + sx, y + sy
                    if 0 <= px < 320 and 0 <= py < 240:
                        self.assertEqual(image[py * 320 + px], want[sy][sx] or 7, (x, y, sx, sy))

    def test_canvas_mapping_and_construction(self):
        from kagura.ui import Canvas
        for args in ((0, 4), (4, 4, 0), (4, -1)):
            with self.assertRaises(ValueError): Canvas(*args)
        with self.assertRaises(TypeError): Canvas(4.0, 4)
        c = Canvas(4, 3, zoom=5, x=10, y=20)
        self.assertEqual(c.measure(self.theme.font), (20, 15))
        root = Screen(); root.add(c); self.app.set_root(root); self.app.step()
        self.assertEqual(c.bounds, (10, 20, 30, 35))
        self.assertEqual(c.cell_rect(3, 2), (25, 30, 30, 35))
        self.assertEqual(c.cell_at(10, 20), (0, 0))
        self.assertEqual(c.cell_at(29, 34), (3, 2))
        for x, y in ((9, 20), (30, 20), (10, 35), (10, 19)):
            self.assertIsNone(c.cell_at(x, y))

    def test_full_paint_matches_reference_and_runs_merge(self):
        from kagura.ui import Sprite4
        s = Sprite4(data=bytes((k * 29) & 0xff for k in range(128)))
        canvas = self.editor(sprite=s, backdrop=9)
        ref = sprite_pixels(s.export(), 16, 16)
        self.assertTrue(canvas.focused)
        self.assertEqual(canvas.cursor, (0, 0))
        self.assert_screen(canvas, lambda cx, cy: ref[cy][cx])
        # A blank sprite is one fill per row (plus the cursor outline).
        self.backend.fills.clear()
        canvas.reload(bytes(128)); self.app.step()
        rows = [f for f in self.backend.fills if f[2] - f[0] == 128 and f[3] - f[1] == 8]
        self.assertEqual(len(rows), 16)
        self.assert_screen(canvas, lambda cx, cy: 0)

    def test_cursor_keys_edit_and_partial_redraw(self):
        changes = []
        canvas = self.editor(on_change=lambda x, y: changes.append((x, y)))
        app = self.app
        def press(key, text=''):
            self.backend.fills.clear()
            app.events.post(Event(key, text))
            app.step()
            return list(self.backend.fills)
        # Cursor: clamped at the edges, keys consumed (focus stays on the canvas).
        for key in ('left', 'up'):
            self.assertEqual(press(key), [])
        self.assertEqual(canvas.cursor, (0, 0))
        self.assertTrue(canvas.focused)
        for _ in range(20): press('right')
        for _ in range(3): press('down')
        self.assertEqual(canvas.cursor, (15, 3))
        self.assertTrue(canvas.focused)
        # Moving repaints only the old and new cursor cells (adjacent: one merged damage rect).
        fills = press('left')
        old, new = canvas.cell_rect(15, 3), canvas.cell_rect(14, 3)
        both = (new[0], new[1], old[2], old[3])
        self.assertTrue(fills)
        for f in fills:
            self.assertTrue(both[0] <= f[0] and both[1] <= f[1] and f[2] <= both[2] and f[3] <= both[3], f)
        # Far apart (damage_limit=4 keeps them separate): each fill lies in one of the two cells.
        app.damage_limit = 4
        canvas.set_cursor(2, 9)
        self.backend.fills.clear(); app.step()
        cells = (canvas.cell_rect(14, 3), canvas.cell_rect(2, 9))
        self.assertTrue(self.backend.fills)
        for f in self.backend.fills:
            self.assertTrue(any(c[0] <= f[0] and c[1] <= f[1] and f[2] <= c[2] and f[3] <= c[3] for c in cells), f)
        app.damage_limit = 1
        canvas.set_cursor(14, 3); app.step()
        # Hex digit picks the colour; Space/Enter paint; Delete/Backspace erase.
        press('text', 'b'); self.assertEqual(canvas.color, 11)
        fills = press('text', ' ')
        cell = canvas.cell_rect(14, 3)
        self.assertTrue(fills and all(cell[0] <= f[0] and f[2] <= cell[2] and cell[1] <= f[1] and f[3] <= cell[3]
                                      for f in fills), fills)
        self.assertEqual(canvas.sprite.get(14, 3), 11)
        self.assertEqual(changes, [(14, 3)])
        # Same colour again: no change, no damage, no callback.
        self.assertEqual(press('enter'), [])
        self.assertEqual(changes, [(14, 3)])
        press('right'); press('text', 'F'); press('enter')
        press('backspace'); press('left'); press('delete')
        self.assertEqual((canvas.sprite.get(15, 3), canvas.sprite.get(14, 3)), (0, 0))
        self.assertEqual(changes, [(14, 3), (15, 3), (15, 3), (14, 3)])
        # Unknown text and releases are not consumed.
        self.assertFalse(canvas.handle(Event('text', 'g')))
        self.assertFalse(canvas.handle(Event('text', 'ab')))
        self.assertFalse(canvas.handle(Event('enter', kind='release')))
        # Tab leaves the canvas.
        root = canvas.parent
        other = root.add(Button('OK', x=200, y=24))
        app.step()
        press('tab')
        self.assertFalse(canvas.focused)
        self.assertTrue(other.focused)

    def test_partial_redraw_reads_only_visible_cells(self):
        from kagura.ui import Canvas
        class Counting(Canvas):
            reads = 0
            def cell(self, cx, cy):
                self.reads += 1
                return (cx + cy) & 15
        canvas = Counting(16, 16, zoom=8, x=40, y=24)
        root = Screen(color=2); root.add(canvas)
        self.app.set_root(root); self.app.step()
        self.assertEqual(canvas.reads, 256)
        canvas.reads = 0
        canvas.invalidate_cell(5, 7); self.app.step()
        self.assertEqual(canvas.reads, 1)
        canvas.reads = 0
        self.app.damage((canvas.bounds[0] + 4, canvas.bounds[1] + 4, canvas.bounds[0] + 20, canvas.bounds[1] + 12))
        self.app.step()
        self.assertEqual(canvas.reads, 3 * 2)  # columns 0..2 of rows 0..1, partly covered

    def test_incremental_edits_equal_full_repaint(self):
        canvas = self.editor()
        seed = 7
        for _ in range(60):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            canvas.set_cursor(seed % 16, (seed >> 8) % 16)
            canvas.set_color((seed >> 16) & 15)
            canvas.handle(Event('enter'))
            if seed & 3 == 0:
                self.app.step()
        self.app.step()
        incremental = bytes(self.backend.pixels)
        self.app.damage((0, 0, 320, 240)); self.app.step()
        self.assertEqual(bytes(self.backend.pixels), incremental)
        ref = sprite_pixels(canvas.sprite.export(), 16, 16)
        self.assert_screen(canvas, lambda cx, cy: ref[cy][cx])

    def test_clipping_by_parent_and_screen_edges(self):
        from kagura.ui import SpriteCanvas, Sprite4
        s = Sprite4(data=bytes([0x9a] * 128))
        root = Screen(color=2)
        # The panel's right/bottom edges cut through cells (41 and 31 px are not multiples of 4).
        frame = root.add(Panel(x=50, y=50, width=41, height=31, color=3))
        inner = frame.add(SpriteCanvas(s, x=-20, y=-10, zoom=4))
        edge = root.add(SpriteCanvas(s, x=300, y=220, zoom=4))
        self.app.set_root(root); self.app.step()
        px = self.backend.pixels
        colour = lambda x: 9 if (x - inner.bounds[0]) // 4 % 2 == 0 else 10
        # Inside the panel: sprite colours, up to the partly visible last row/column.
        for x, y in ((50, 50), (90, 50), (50, 80), (90, 80)):
            self.assertEqual(px[y * 320 + x], colour(x), (x, y))
        # Outside it: untouched screen colour.
        for x, y in ((50, 49), (49, 50), (91, 60), (60, 81)):
            self.assertEqual(px[y * 320 + x], 2, (x, y))
        for f in self.backend.fills:
            self.assertTrue(0 <= f[0] and f[2] <= 320 and 0 <= f[1] and f[3] <= 240, f)
        # Off-screen part of the edge canvas is skipped, the visible part painted.
        self.assertIn(px[239 * 320 + 319], (9, 10))
        before = len(self.backend.fills)
        edge.invalidate_cell(15, 15); self.app.step()
        self.assertEqual(len(self.backend.fills), before)


class SpriteEditorTests(unittest.TestCase):
    GRID, PREVIEW, PALETTE = (8, 20), (152, 20), (152, 48)

    def setUp(self):
        import ui_sprite_editor
        self.module = ui_sprite_editor
        self.backend = RecordingBackend()
        self.theme = theme()
        self.app = App(backend=self.backend, theme=self.theme)

    def tearDown(self):
        self.app.close()
        self.theme.font.source.close()

    def build(self, data=None):
        self.module.build(self.app, data)
        self.app.step()
        return self.module.editor

    def press(self, key, text=''):
        self.backend.fills.clear()
        self.app.events.post(Event(key, text))
        self.app.step()
        return list(self.backend.fills)

    def assert_sprite_on_screen(self, editor):
        """Grid (8x, cursor cell excepted) and 1:1 preview both show the TILE4 data."""
        want = sprite_pixels(editor.sprite.export(), 16, 16)
        px = self.backend.pixels
        gx, gy = self.GRID
        px0, py0 = self.PREVIEW
        for y in range(16):
            for x in range(16):
                shown = want[y][x] or 0
                self.assertEqual(px[(py0 + y) * 320 + px0 + x], shown, ('preview', x, y))
                if (x, y) != editor.grid.cursor:
                    self.assertEqual(px[(gy + y * 8 + 4) * 320 + gx + x * 8 + 4], shown, ('grid', x, y))

    def test_layout_initial_render_and_palette(self):
        data = bytes((k * 41) & 0xff for k in range(128))
        e = self.build(data)
        self.assertIs(self.app.focus.current, e.grid)
        self.assertEqual(self.app.damage_limit, 4)
        self.assertEqual((e.grid.zoom, e.grid.columns, e.grid.rows), (8, 16, 16))
        self.assertEqual(e.grid.bounds, (8, 20, 136, 148))
        self.assertIs(e.preview.sprite, e.sprite)
        self.assertIs(e.grid.sprite, e.sprite)
        self.assertFalse(e.preview.focusable)
        self.assert_sprite_on_screen(e)
        bx, by = self.PALETTE
        for c in range(16):
            self.assertEqual(self.backend.pixels[(by + c // 4 * 16 + 8) * 320 + bx + c % 4 * 16 + 8], c)
        self.assertEqual(self.backend.pixels[60 * 320 + 236], 1)  # swatch = colour 1
        self.assertEqual((e.color_label.text, e.cursor_label.text), ('Color 1', 'X 0 Y 0'))

    def test_keyboard_paint_erase_select_and_indicators(self):
        e = self.build()
        self.press('text', 'c')
        self.assertEqual((e.grid.color, e.color_label.text, e.swatch.color, e.palette.cursor), (12, 'Color 12', 12, (0, 3)))
        self.press('enter'); self.press('right'); self.press('text', ' ')
        self.press('down'); self.press('text', '0'); self.press('enter')  # colour 0 paints transparent
        self.assertEqual(e.color_label.text, 'Color 0 (clear)')
        self.assertEqual([e.sprite.get(0, 0), e.sprite.get(1, 0), e.sprite.get(1, 1)], [12, 12, 0])
        self.assertEqual(e.cursor_label.text, 'X 1 Y 1')
        self.press('up'); self.press('delete')
        self.assertEqual(e.sprite.get(1, 0), 0)
        # Palette: Tab focuses it, arrows move, Enter selects; the grid keeps its cursor.
        self.press('tab')
        self.assertIs(self.app.focus.current, e.palette)
        self.press('right'); self.press('down'); self.press('enter')
        self.assertEqual(e.grid.color, 5)
        self.press('text', 'F')
        self.assertEqual((e.grid.color, e.palette.cursor), (15, (3, 3)))
        self.press('tab'); self.press('enter')
        self.assertEqual(e.sprite.get(1, 0), 15)
        self.assert_sprite_on_screen(e)
        self.assertFalse(e.grid.handle(Event('text', 'g')))

    def test_one_level_undo_and_redo(self):
        e = self.build()
        self.press('text', 'u')
        self.assertEqual(e.status.text, 'Nothing to undo')
        self.press('text', '3'); self.press('enter'); self.press('right'); self.press('enter')
        before = e.sprite.export()
        self.press('delete'); self.press('delete')  # second delete changes nothing: undo keeps the first
        self.press('text', 'U')
        self.assertEqual(e.sprite.export(), before)
        self.assertEqual(e.status.text, 'Undo')
        self.press('text', 'u')  # one level: undo again redoes
        self.assertEqual(e.sprite.get(1, 0), 0)
        self.press('text', 'u')
        self.assertEqual((e.sprite.get(0, 0), e.sprite.get(1, 0)), (3, 3))
        self.assert_sprite_on_screen(e)

    def test_hex_export_import_and_print(self):
        import binascii, io
        from contextlib import redirect_stdout
        e = self.build()
        for x, y, c in ((0, 0, 1), (1, 0, 2), (8, 0, 3), (0, 8, 4), (15, 15, 5)):
            e.grid.put(x, y, c)
        text = e.export_hex()
        self.assertEqual(len(text), 256)
        self.assertEqual(text, binascii.hexlify(e.sprite.export()).decode())
        raw = binascii.unhexlify(text)  # TILE4: (0,0)(1,0) in byte 0; tiles TL, TR, BL, BR
        self.assertEqual((raw[0], raw[32], raw[64], raw[127]), (0x12, 0x30, 0x40, 0x05))
        image = bytes(range(128))
        before = e.sprite.export()
        for bad in (text[:-1], 'zz' + text[2:], text + '00', 7):
            with self.assertRaises((ValueError, TypeError)): e.import_hex(bad)
        self.assertEqual(e.sprite.export(), before)
        spaced = ' '.join(binascii.hexlify(image).decode()[i:i + 32] for i in range(0, 256, 32)) + '\n'
        e.import_hex(spaced.upper()); self.app.step()
        self.assertEqual(e.sprite.export(), image)
        self.assertEqual(e.status.text, 'Imported')
        self.assert_sprite_on_screen(e)
        e.undo(); self.app.step()
        self.assertEqual(e.sprite.export(), before)
        self.assert_sprite_on_screen(e)
        out = io.StringIO()
        with redirect_stdout(out):
            self.press('text', 'p')
        self.assertEqual(out.getvalue(), 'SPRITE_HEX %s\n' % e.export_hex())
        # run(data_hex=...) preloads the same data.
        self.assertEqual(self.module.SpriteEditor(App(backend=MockBackend(), theme=self.theme), image).sprite.export(), image)

    def test_editing_redraws_only_small_regions(self):
        e = self.build()
        def area(fills):
            return sum((f[2] - f[0]) * (f[3] - f[1]) for f in fills)
        steps = {
            'paint': lambda: self.press('enter'),
            'erase': lambda: self.press('delete'),
            'move': lambda: self.press('right'),
            'select': lambda: self.press('text', '9'),
            'undo': lambda: self.press('text', 'u'),
        }
        for name, step in steps.items():
            fills = step()
            self.assertTrue(fills, name)
            # A cell is 64 px; labels are 8 px high. Full screen would be 76800 px.
            self.assertLess(area(fills), 4000, (name, fills))
            for f in fills:
                self.assertLess((f[2] - f[0]) * (f[3] - f[1]), 3000, (name, f))
        self.backend.fills.clear()
        text = e.export_hex()
        e.import_hex(text[:-1] + ('0' if text[-1] != '0' else 'f')); self.app.step()  # one changed pixel
        self.assertLess(area(self.backend.fills), 4000)
        # (15,15) changed; (14,15) shares its byte but did not change, so it is not repainted.
        n = e.grid.cell_rect(14, 15)
        for f in self.backend.fills:
            self.assertFalse(f[0] < n[2] and n[0] < f[2] and f[1] < n[3] and n[1] < f[3], f)
        incremental = bytes(self.backend.pixels)
        self.app.damage((0, 0, 320, 240)); self.app.step()
        self.assertEqual(bytes(self.backend.pixels), incremental)

    def test_sdk_backend_with_preview_blit_matches_reference(self):
        # The SDK framebuffer (preview drawn by one blit) must equal the Mock reference screen.
        import binascii
        model = T.RegisterModel()
        model.ext[R.EXT_SCREEN_HEIGHT] = 240
        model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
        model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
        sdk = App(Kagura(model).probe(), exclusive=True, theme=self.theme)
        try:
            editors = []
            for app in (self.app, sdk):
                self.module.build(app, bytes((k * 41) & 0xff for k in range(128)))
                editors.append(self.module.editor)
                app.step()
            blits = []
            fb = sdk.backend.fb
            original = fb.blit
            fb.blit = lambda *a, **k: (blits.append(a[1:3]), original(*a, **k))
            pattern = binascii.hexlify(bytes((k * 73) & 0xff for k in range(128))).decode()
            script = [('event', 'text', 'c'), ('event', 'enter', ''), ('event', 'right', ''), ('event', 'delete', ''),
                      ('import', pattern), ('event', 'text', 'u'), ('event', 'down', ''), ('event', 'text', '5'),
                      ('event', 'enter', ''), ('event', 'tab', ''), ('event', 'right', ''), ('event', 'enter', ''),
                      ('import', '00' * 128), ('event', 'text', 'u'), ('event', 'tab', ''), ('full',)]
            for step in script:
                for app, e in ((self.app, editors[0]), (sdk, editors[1])):
                    if step[0] == 'event':
                        app.events.post(Event(step[1], step[2]))
                    elif step[0] == 'import':
                        e.import_hex(step[1])
                    else:
                        app.damage((0, 0, 320, 240))
                    app.step()
                self.assertEqual(decode(fb.buffer), self.backend.pixels, step)
            self.assertEqual(editors[0].export_hex(), editors[1].export_hex())
            self.assertGreaterEqual(blits.count((152, 20)), 3)
            # A single-pixel edit repaints that preview pixel only, without a blit.
            before = len(blits)
            for app, e in ((self.app, editors[0]), (sdk, editors[1])):
                e.grid.put(3, 4, 15 - e.sprite.get(3, 4)); app.step()
            self.assertEqual(len(blits), before)
            self.assertEqual(decode(fb.buffer), self.backend.pixels)
        finally:
            sdk.close()

    def test_no_layout_pass_or_hidden_palette_repaint_while_editing(self):
        e = self.build()
        layouts = []
        original = self.app.request_layout
        self.app.request_layout = lambda: (layouts.append(1), original())
        palette = e.palette.bounds
        for key, text in (('right', ''), ('down', ''), ('text', 'c'), ('enter', ''), ('delete', ''),
                          ('text', 'u'), ('text', '0'), ('text', 'p')):
            fills = self.press(key, text) if key != 'text' or text != 'p' else None
            if fills is None:
                import io
                from contextlib import redirect_stdout
                with redirect_stdout(io.StringIO()):
                    fills = self.press(key, text)
            for f in fills:
                inside = palette[0] <= f[0] and f[2] <= palette[2] and palette[1] <= f[1] and f[3] <= palette[3]
                self.assertFalse(inside, (key, text, f))
        e.import_hex('11' * 128); self.app.step()
        self.assertEqual(layouts, [])
        self.assertEqual((e.cursor_label.text, e.color_label.text, e.status.text), ('X 1 Y 1', 'Color 0 (clear)', 'Imported'))
        # The palette cursor followed the selection while hidden; focusing shows it there.
        self.assertEqual(e.palette.cursor, (0, 0))
        self.press('text', '9'); self.press('tab')
        x, y = e.palette.cell_rect(1, 2)[:2]
        self.assertEqual(self.backend.pixels[y * 320 + x], self.theme.focus)
        self.assertEqual(self.backend.pixels[(y + 8) * 320 + x + 8], 9)

    def test_bulk_import_invalidates_grid_and_preview_once(self):
        e = self.build()
        damage = []
        original = self.app.damage
        self.app.damage = lambda rect: (damage.append(rect), original(rect))
        e.import_hex('12' * 128)  # 256 changed pixels
        self.assertEqual(sorted(damage), sorted([e.grid.bounds, e.preview.bounds, e.status.bounds]))
        self.app.step()
        self.assert_sprite_on_screen(e)
        damage.clear()
        text = e.export_hex()
        e.import_hex('34' + text[2:])  # 2 changed pixels: per pixel, as before
        self.assertEqual(len(damage), 2 * 2)  # status already reads 'Imported': not repainted
        self.app.step()
        self.assert_sprite_on_screen(e)
        # The threshold counts pixels, not bytes: 16 pixels (8 bytes) stay per pixel, 17 (9 bytes) go bulk.
        for pixels, bulk in ((16, False), (17, True)):
            base = e.export_hex()
            digits = list(base)
            for k in range(pixels):
                digits[k] = '0' if digits[k] != '0' else '7'
            damage.clear()
            e.import_hex(''.join(digits))
            self.assertEqual(len(damage), 2 if bulk else 2 * pixels, pixels)
            self.app.step()
            self.assert_sprite_on_screen(e)


if __name__ == '__main__':
    unittest.main()
