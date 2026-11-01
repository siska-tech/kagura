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
                        if width==5 or x==315:
                            draw.assert_not_called()
                        else:
                            self.assertGreater(draw.call_count,0)
                    self.assertEqual(decode(self.app.backend.fb.buffer),reference.backend.pixels)
                self.assertGreater(self.app.backend.fb.kernel_counts[4],0)
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


if __name__ == '__main__':
    unittest.main()
