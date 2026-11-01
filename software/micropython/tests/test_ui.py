# SPDX-License-Identifier: Apache-2.0
"""Independent PC surface versus SDK tile framebuffer, ownership and input."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_driver as T
import unittest
from unittest.mock import patch
from kagura import Kagura, regs as R
from kagura.ui import (App, Widget, Screen, Panel, Label, Button, ProgressBar,
                       ListView, VBox, HBox, Event, EventQueue, TerminalInput,
                       Theme, BitmapFont8, FramebufferBackend)
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
        self.assertFalse(self.app.step()); self.assertEqual(self.backend.flushes, n)
        label.set_text('1'); self.backend.fail_flush = True
        with self.assertRaises(OSError): self.app.step()
        self.assertIsNotNone(self.app._damage)
        self.backend.fail_flush = False; self.app.step()
        self.assertIsNone(self.app._damage)
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
        self.assertIsNotNone(self.app._damage)

    def test_ascii_fallback_and_missing_glyph(self):
        from viper_emulator import MonoFont
        with patch.dict(sys.modules, {'framebuf': T.types.SimpleNamespace(FrameBuffer=MonoFont, MONO_HLSB=3)}):
            font = BitmapFont8()
            expected = bytearray(8)
            MonoFont(expected,8,8,3).text('A',0,0,1)
            self.assertEqual(bytes(font.glyph('A')), expected)
            self.assertEqual(bytes(font.glyph('日')), bytes(font.glyph('?')))
        self.assertEqual(self.theme.font.glyph('\U0001f600'), self.theme.font.glyph('?'))

    def test_terminal_unknown_sequence_crlf_and_malformed_utf8(self):
        q, adapter = EventQueue(), TerminalInput()
        adapter.feed(b'\x1b[1;5A\r\nx\xff',q)
        self.assertEqual(q.pop().key,'enter')
        self.assertEqual(q.pop().text,'x')
        self.assertIsNone(q.pop())

    def test_damage_raised_during_paint_survives(self):
        class Animated(Widget):
            def paint(widget, renderer, theme): widget.invalidate()
        root = Screen()
        root.add(Animated(width=16,height=16))
        self.app.set_root(root); self.app.step()
        self.assertEqual(self.app._damage,(0,0,16,16))
        self.app.step(); self.assertIsNotNone(self.app._damage)

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
            self.app.events.post(Event('tab')); self.app.events.post(Event('enter'))
            self.app.step()
            if update is not None: update()


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

    def test_sdk_flush_error_keeps_dirty_and_damage(self):
        self.app.set_root(Label('0')); self.app.step()
        self.app.root.set_text('1')
        with patch.object(self.device,'fence',side_effect=OSError('fence')):
            with self.assertRaises(OSError): self.app.step()
        self.assertGreater(sum(self.app.backend.fb.dirty),0)
        self.assertIsNotNone(self.app._damage)
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


if __name__ == '__main__':
    unittest.main()
