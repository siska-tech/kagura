# SPDX-License-Identifier: Apache-2.0
"""Presentation asset/wire/lifecycle contracts, not simulated hardware timing."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_framebuffer as F
from kagura import Kagura, regs as R, image256
import showcase as S
import showcase_slides as L
import showcase_scenery as B

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'software/micropython/examples/showcase_assets'


def device():
    model = F.PsramModel()
    model.ext[R.EXT_SCREEN_HEIGHT] = 240
    model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
    model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
    return Kagura(model).probe(), model


class ShowcaseTests(unittest.TestCase):
    def test_baked_scenery_is_c_golden_and_streamed_without_tile_cache(self):
        from test_sakura import C_SHA256
        d, m = device()
        path = ASSETS / 'sakura.scenery'
        raw = path.read_bytes()
        count = B.load(d, bytearray(4096), str(path))
        d.fence()
        self.assertEqual(count, 265)
        tiles = bytes(m.memory[256 * 32:(256 + count) * 32])
        tilemap = bytes(m.memory[0x8000:0x9000])
        self.assertEqual(hashlib.sha256(tiles).hexdigest(), C_SHA256['scenery'])
        self.assertEqual(hashlib.sha256(tilemap).hexdigest(), C_SHA256['map'])
        B.preload(d, str(path))
        m.memory[0x2000:0x2000 + len(tiles)] = bytes(len(tiles))
        B.restore(d, None, None, None)
        self.assertEqual(bytes(m.memory[0x2000:0x2000 + len(tiles)]), tiles)
        self.assertGreaterEqual(B.CACHE_BASE, image256.SLOT_BASE + len(S.SLIDES) * image256.SLOT_SIZE)
        manifest = json.loads((ASSETS / 'manifest.json').read_text())['scenery']
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest['sha256'])
        broken = bytearray(raw)
        broken[-1] ^= 1
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / 'bad.scenery'
            bad.write_bytes(broken)
            before = len(m.calls)
            with self.assertRaisesRegex(ValueError, 'CRC'):
                B.load(d, bytearray(4096), str(bad))
            self.assertEqual(len(m.calls), before)

    def test_controls_advance_then_quit(self):
        stream = io.StringIO('nq')
        class Poller:
            def register(self, *args):
                pass
            def poll(self, timeout):
                return ((0, 1),)
        select = types.SimpleNamespace(poll=Poller, POLLIN=1)
        with patch.dict(sys.modules, select=select), patch.object(sys, 'stdin', stream):
            control = S._Controls()
            self.assertTrue(control.poll())
            with self.assertRaises(S._Stop):
                control.poll()

    def test_sakura_interrupt_stops_the_whole_presentation(self):
        calls = []
        class Demo:
            interrupted = True
            sound = types.SimpleNamespace(stop=lambda: calls.append('stop'))
            def __init__(self, *a, **kw):
                pass
            def run(self, seconds):
                return True
        module = types.ModuleType('sakura')
        module.Sakura = Demo
        with patch.dict(sys.modules, sakura=module), \
             patch.object(S.gc, 'mem_free', return_value=100000, create=True):
            with self.assertRaises(S._Stop):
                S._sakura(None, types.SimpleNamespace(poll=lambda: False), 'assets', 'font', 1)
        self.assertEqual(calls, ['stop'])

    def test_every_slide_crc_palette_and_manifest(self):
        manifest = json.loads((ASSETS / 'manifest.json').read_text())
        self.assertEqual(tuple(row['name'] for row in manifest['slides']), S.SLIDES)
        for row in manifest['slides']:
            path = ASSETS / (row['name'] + '.kimg')
            data = path.read_bytes()
            self.assertEqual(len(data), 40120)
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])
            palette, cells = image256.check(str(path))
            for n in range(16):
                self.assertEqual(palette[n * 32:n * 32 + 2], palette[:2])
            self.assertEqual(len(cells), 1200)
        for name in ('plasma', 'tunnel', 'tesseract', 'ribbon'):
            raw = (ASSETS / (name + '.caption')).read_bytes()
            self.assertEqual(len(raw), 3840)
            self.assertTrue(all((v >> 4) in (1, 2, 3) and (v & 15) in (1, 2, 3) for v in raw))

    def test_slide_copy_without_cpu_framebuffer_and_after_other_demo(self):
        d, m = device()
        deck = L.Deck(d)
        self.assertFalse(hasattr(deck.surface, 'buffer'))
        self.assertEqual(len(deck.surface.dirty), 1200)
        deck.slots.save_file(0, str(ASSETS / 'opening.kimg'))
        deck.restore()
        deck.show(0)
        data = (ASSETS / 'opening.kimg').read_bytes()
        pixels = data[1716:-4]
        self.assertEqual(m.memory[:32768] + m.memory[0xB000:0xC600], pixels)
        palette, cells = image256.check(str(ASSETS / 'opening.kimg'))
        self.assertEqual(m.memory[0x9400:0x9600], palette)
        for y in range(30):
            for x in range(40):
                tile, address = y * 40 + x, 0x8000 + (y * 64 + x) * 2
                word = int.from_bytes(m.memory[address:address + 2], 'little')
                self.assertEqual(word & 1023, tile & 1023)
                self.assertEqual(word >> 10, cells[tile])
                high = m.memory[0x9000 + (y * 64 + x) // 8] >> (x & 7) & 1
                self.assertEqual(high, tile >> 10)
        # A game left sprites, scroll and raster active. Restoring a slide
        # must clear them; PSRAM slide slots must survive low-region audio writes.
        m.memory[0xA000:0xA800] = bytes((255,)) * 2048
        d.ext_write(R.EXT_SCROLL_X_L, 79)
        d.ext_write(R.EXT_RS_COUNT, 8)
        d.write_memory(0x400000, b'PCM')
        deck.restore()
        deck.show(0)
        self.assertEqual(m.memory[0xA000:0xA800], bytes(2048))
        self.assertEqual(m.ext[R.EXT_SCROLL_X_L], 0)
        self.assertEqual(m.ext[R.EXT_RS_COUNT], 0)
        self.assertEqual(m.memory[:32768] + m.memory[0xB000:0xC600], pixels)
        self.assertEqual(d.busy, 0)

    def test_bad_slide_crc_changes_no_device_state(self):
        d, m = device()
        deck = L.Deck(d)
        raw = bytearray((ASSETS / 'opening.kimg').read_bytes())
        raw[-1] ^= 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.kimg'
            path.write_bytes(raw)
            before = len(m.calls)
            with self.assertRaisesRegex(ValueError, 'CRC'):
                deck.slots.save_file(0, str(path))
            self.assertEqual(len(m.calls), before)

    def test_module_unload_is_scoped(self):
        names = ('testchapter', 'testchapter_native', 'testchapterology')
        with patch.dict(sys.modules, {name: types.ModuleType(name) for name in names}):
            S._unload('testchapter')
            self.assertNotIn(names[0], sys.modules)
            self.assertNotIn(names[1], sys.modules)
            self.assertIn(names[2], sys.modules)

    def test_show_order_and_owned_cleanup_on_second_loop(self):
        d, m = device()
        events = []
        def cards(deck, control, assets, rows, speed):
            events.extend(S.SLIDES[n] for n, _ in rows)
        fake_open = unittest.mock.mock_open(read_data=b'asset')
        with patch.object(S, '_warm_names', return_value=True), \
             patch.object(S, '_preload', lambda *a: events.append('load')), patch.object(S, '_Controls', lambda: None), \
             patch.object(S, '_cards', cards), patch.object(S, '_graphics', lambda *a: events.append('graphics')), \
             patch.object(S, '_game', lambda *a: events.append('game-live')), \
             patch.object(S, '_sakura', lambda *a: events.append('sakura-live')), \
             patch('builtins.open', fake_open):
            S.run(device=d, loops=2)
        one = ['opening', 'architecture', 'colour', 'graphics', 'game', 'game-live',
               'orchestra', 'sakura-live', 'create', 'closing']
        self.assertEqual(events, ['load'] + one + one)
        self.assertFalse(m.closed)
        self.assertEqual(m.reg[R.REG_DISPLAY_CTRL], 0)
        self.assertEqual(d.busy, 0)

    def test_repeat_requires_prepared_identifier_table(self):
        d,m = device()
        with patch.object(S,'_warm_names',return_value=False), patch.object(S,'_Controls',lambda:None), \
             patch('builtins.open',unittest.mock.mock_open(read_data=b'a')):
            with self.assertRaisesRegex(ValueError,'prepare-showcase'):
                S.run(device=d,loops=2)
        self.assertEqual(d.busy,0)

    def test_quit_and_error_both_silence_and_blank(self):
        for error in (S._Stop(), KeyboardInterrupt(), OSError('transfer failed')):
            d, m = device()
            with patch.object(S, '_preload', side_effect=error), patch.object(S, '_Controls', lambda: None), \
                 patch('builtins.open', unittest.mock.mock_open(read_data=b'a')):
                if isinstance(error, OSError):
                    with self.assertRaisesRegex(OSError, 'transfer failed'):
                        S.run(device=d, loops=1)
                else:
                    S.run(device=d, loops=1)
            self.assertEqual(d.busy, 0)
            self.assertEqual(m.reg[R.REG_DISPLAY_CTRL], 0)
            self.assertEqual([m.audio[ch * 16 + R.AUDIO_CONTROL] for ch in range(6)], [0] * 6)


if __name__ == '__main__':
    unittest.main()
