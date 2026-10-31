# SPDX-License-Identifier: Apache-2.0
"""sakura.py on PC: its Viper kernels run on bounds-checked pointers.

The SHA-256 values come from the Pico C `stress` showcase (stress_demo.c)
built for PC with stubbed transport and the same inputs: the port must
reproduce its scenery, petals, aurora, palettes, sprites, raster table, HUD
text, piano notes and PSG register writes byte for byte. Hardware timing is
never simulated here.
"""
import hashlib
from pathlib import Path
import re
import sys
import time
import unittest
from array import array
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_driver
from viper_emulator import load
time.ticks_ms = lambda: time.monotonic_ns() // 1000000
ROOT = test_driver.ROOT
EXAMPLES = ROOT / 'software/micropython/examples'
sys.path.insert(0, str(EXAMPLES))
sys.modules['sakura_viper'] = load(EXAMPLES / 'sakura_viper.py')
import sakura as S
sys.modules['sakura_hud_viper'] = load(EXAMPLES / 'sakura_hud_viper.py')
import sakura_hud as H
from kagura import regs as R
from kagura.device import DeviceError

FONT = str(ROOT / 'software/micropython/fonts/misaki8.kfnt')
ASSETS = str(EXAMPLES / 'sakura_assets')
TIMES = (0, 1, 7, 100, 12345, 216000)
C_SHA256 = {
    'map': '8042ff048dadc456effa1d7ef5072f011e6985a7373d2d74c37e1539be6e0b64',
    'scenery': '7fbb439c73c9349d6bfb469531aade624b367bd1ac25cbf5d4c8294b5a4500af',
    'petals': '405bb8e13ccbdf275f859075ea9f8e5561e09c5bb8b9c712788303ff8d2c3973',
    'aurora': 'ad4890c294677363daf47d4d500786962f46ddb3ceda098539c0d34a66048e2a',
    'palette': '342f2bfa9a47ef544b66f18ad202e158777c4b09475d97be522b2c33d7266a0b',
    'oam240': 'e3e5801d27d1feffdb42a28658e952de0e34cd4bebd6215aba0280e5241c5565',
    'oam180': '4b2ebe7f6f6e607339420132d3a1fa1527c5134ad330629c3e5fcece2781c9d6',
    'bands240': '2c73978a97d8091959253d828203f334f2f1ce74528b30a18bec1b2b71a50555',
    'bands180': 'a802c9d7aa077cf7d0db4b4683770962e6972ab00097d2fd1355f58a07e127b9',
    'marquee': 'd00df83665a67ce3a9eb3597e21f923f45f0376c76eae0d2bff64ff03c001d0f',
    'hud': '708a03f683ed6bbebfe88b39ad39fa9b4590a9bb3b9327d09cc8fb15c5abc025',
    'hud_loading': 'c562beb3dcbe463e4489bcbd5abe993c1e89401b6e5de4b683ac7c69c56939ba',
    'piano': '8988a8738ddecc891cb6df4fe9e943d6849588bd10513c406358064d51549d12',
    # With PCM the gust sweep differs by one step LSB: C rounds in float, CPython in double.
    'psg_only_audio': 'e45dac34dbb61ae988a3c119ed2dba1155130f62cb388d02ade117f0d4535247',
}


def sha(*parts):
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
    return h.hexdigest()


class Transport:
    def __init__(self, device):
        self.device = device

    def write(self, offset, data, inc=False):
        assert self.device.busy > 0, 'bare transport write outside device.busy'
        for i, value in enumerate(data):
            if offset == R.REG_COMMAND and not inc:
                self.device.write_reg(offset, value)
            else:
                self.device.reg[offset + (i if inc else 0)] = value

    def readinto(self, offset, buffer, inc=False):
        assert self.device.busy > 0, 'bare transport read outside device.busy'
        assert len(buffer) == 1 and not inc
        if offset == R.REG_AUDIO_REG_DATA:
            buffer[0] = self.device.audio_read(self.device.reg[R.REG_AUDIO_REG_INDEX])
        else:
            buffer[0] = self.device.read_reg(offset)


class Device:
    """The Kagura calls sakura.py makes, with the ordering rules it must keep."""

    def __init__(self, height=240, caps=0x7B):
        self.height, self.caps, self.busy = height, caps, 0
        self.memory = bytearray(0x800000)
        self.reg, self.ext, self.audio = bytearray(32), bytearray(256), bytearray(256)
        self.transport = Transport(self)
        self.audio_log = []
        self.pending = False
        self.frame = 0
        self.vblanks_per_read = 1
        self.commits = self.copies = 0
        self.fail_commit = None       # raise DeviceError at this COMMIT
        self.overflow_commit = None   # report a sprite overflow after this COMMIT
        self.interrupt_commit = None  # raise KeyboardInterrupt at this COMMIT
        self.closed = False

    def write_memory(self, address, data):
        assert 0 <= address and address + len(data) <= len(self.memory), 'invalid memory write'
        self.memory[address:address + len(data)] = data

    def fill(self, address, length, value=0):
        self.write_memory(address, bytes((value,)) * length)

    def fence(self):
        pass

    def write_reg(self, offset, value):
        if offset == R.REG_COMMAND and value == R.CMD_COPY:
            self.copies += 1
        self.reg[offset] = value

    def read_reg(self, offset):
        if offset == R.REG_FRAME_COUNT_L:
            self.frame = (self.frame + self.vblanks_per_read) & 255
            return self.frame
        if offset == R.REG_IRQ_STATUS:
            return R.IRQ_STATUS_SPR_OVERFLOW if self.commits == self.overflow_commit else 0
        return 0

    def ext_write(self, index, value):
        self.ext[index] = value

    def ext_writes(self, pairs):
        for i in range(0, len(pairs), 2):
            if pairs[i] in (R.EXT_RS_COUNT, R.EXT_RS_LINE, R.EXT_RS_X_L, R.EXT_RS_X_H, R.EXT_RS_Y):
                assert not self.pending, 'raster table written during COMMIT_BUSY'
            self.ext[pairs[i]] = pairs[i + 1]

    def audio_write(self, index, value):
        self.audio[index] = value

    def audio_writes(self, pairs):
        for i in range(0, len(pairs), 2):
            self.audio_log.append('%d %d' % (pairs[i], pairs[i + 1]))
            self.audio[pairs[i]] = pairs[i + 1]

    def audio_read(self, index):
        return R.AUDIO_PCM_STATUS_READY

    def audio_commit(self):
        self.audio_log.append('commit')

    def wait_status(self, mask, value):
        if mask == R.STATUS_COMMIT_BUSY and value == 0:
            self.pending = False

    def commit(self, wait=True):
        assert not self.pending, 'COMMIT during COMMIT_BUSY'
        self.commits += 1
        if self.commits == self.fail_commit:
            raise DeviceError(R.ERROR_CODE_LINE_UNDERRUN)
        if self.commits == self.interrupt_commit:
            raise KeyboardInterrupt
        self.pending = not wait

    def clear_errors(self):
        pass

    def deinit(self):
        self.closed = True


class Demo:
    """Bare attributes for calling one Sakura method."""
    opt = ()
    hud_width = S.Sakura.hud_width


class ShortLink:
    """Decode Link._short's header through the existing fake transport."""
    def __init__(self, raw):
        from types import SimpleNamespace
        self.raw = raw
        self.k = SimpleNamespace(_short=object())
        self.calls = 0

    def _fast(self, name, kernel, n, operation, value):
        assert kernel is self.k._short and n == 2
        self.calls += 1
        offset = operation & 31
        if operation & 0x80:
            assert name == 'read'
            out = bytearray(1)
            self.raw.readinto(offset, out)
            return out[0]
        assert name == 'write'
        size = operation >> 8
        data = bytes((value >> (8 * i)) & 255 for i in range(size))
        self.raw.write(offset, data, bool(operation & 0x40))
        return 0


def petals():
    xs, phases = array('H', [0] * 256), bytearray(256)
    for i in range(256):
        h = S.mix(i * 2654435761 + 7)
        xs[i], phases[i] = h % 352, h >> 16 & 255
    return xs, phases


def oam_frame(xs, phases, lines, t):
    oam, p = bytearray(2048), array('i', [t, lines, t * 37 // 16, t * 21 // 16, t * 11 // 16])
    S.K.build_oam(oam, xs, phases, S.SINE_BYTES, S.LAYERS, p)
    return oam


class Scene(unittest.TestCase):
    def test_scenery_matches_c(self):
        d = Device()
        strip, packed, work = bytearray(4096), bytearray(2048), bytearray(8192)
        count = S.build_scenery(d, strip, packed, work)
        self.assertEqual(count, 265)
        self.assertEqual(sha(d.memory[0x8000:0x9000]), C_SHA256['map'])
        self.assertEqual(sha(d.memory[256 * 32:(256 + count) * 32]), C_SHA256['scenery'])

    def test_petals_aurora_and_palettes_match_c(self):
        work, strip, packed = bytearray(8192), bytearray(4096), bytearray(2048)
        S.make_petals(work)
        self.assertEqual(sha(work[:384]), C_SHA256['petals'])
        frames = []
        for f in range(16):
            S.make_aurora(f, strip, packed, work)
            frames.append(bytes(work[:1024]))
        self.assertEqual(sha(*frames), C_SHA256['aurora'])
        palettes = []
        for t in TIMES:
            pal = bytearray(512)
            S.build_palette(pal, t)
            palettes.append(bytes(pal))
            before = bytes(pal)
            S.palette_frame(pal, t + 1)
            self.assertEqual(pal[192:], before[192:], 'per-frame changes stay in palettes 0..5')
        self.assertEqual(sha(*palettes), C_SHA256['palette'])

    def test_sprites_and_raster_table_match_c(self):
        xs, phases = petals()
        for lines in (240, 180):
            self.assertEqual(sha(*(oam_frame(xs, phases, lines, t) for t in TIMES)), C_SHA256['oam%d' % lines])
            demo = Demo()
            demo.ext, demo.lines, demo.rscroll, demo.copy = bytearray(80), lines, True, False
            text = ''
            for t in TIMES:
                n = S.Sakura.bands(demo, t)
                text += ''.join('%d %d\n' % (demo.ext[i], demo.ext[i + 1]) for i in range(0, n, 2))
            self.assertEqual(sha(text.encode()), C_SHA256['bands%d' % lines])

    def test_no_line_holds_more_than_16_sprites(self):
        xs, phases = petals()
        for lines in (240, 180):
            for t in range(0, 2400, 37):
                oam = oam_frame(xs, phases, lines, t)
                used = [0] * 512
                for i in range(256):
                    e = oam[i * 8:i * 8 + 8]
                    y = e[2] | (e[3] & 3) << 8
                    for line in range(y, y + (16 if e[3] & 8 else 8)):
                        used[line] += 1
                self.assertLessEqual(max(used[:lines]), 16, (lines, t))

    def test_hud_and_marquee_text_match_c(self):
        demo = Demo()
        demo.d = d = Device()
        demo.text = S.Text(FONT)
        demo.hud_rows = [b'', b'']
        demo.upload = lambda first, tiles, row=None: S.Sakura.upload(demo, first, tiles, row)
        # The C version's text; this port adds "+ MicroPython" and lets the loop supply the last ◆.
        c_marquee = S.MARQUEE.replace(' + MicroPython', ' ◆')
        self.assertNotEqual(c_marquee, S.MARQUEE)
        with patch.object(S, 'MARQUEE', c_marquee):
            S.Sakura.draw_marquee(demo)
        self.assertEqual(sha(d.memory[96 * 32:160 * 32]), C_SHA256['marquee'])
        self.assertLessEqual(demo.text.text(4, S.MARQUEE, 0), 512, 'the marquee fits its 64 tiles')
        hud = {'fps10': 598, 'status': None, 'overflow': 0, 'underrun': 3, 'line_underrun': 0,
               'psram_bytes': 123456789, 'psram_kbs': 345, 'errors': 0x20}
        S.Sakura.draw_hud(demo, hud)
        self.assertEqual(sha(d.memory[16 * 32:96 * 32]), C_SHA256['hud'])
        S.Sakura.draw_hud(demo, {'fps10': 0, 'status': '%s 3/11' % S.LOADING[3]})
        self.assertEqual(sha(d.memory[16 * 32:96 * 32]), C_SHA256['hud_loading'])
        # An unchanged row is not uploaded again.
        d.memory[16 * 32:96 * 32] = bytes(80 * 32)
        S.Sakura.draw_hud(demo, {'fps10': 0, 'status': '%s 3/11' % S.LOADING[3]})
        self.assertEqual(bytes(d.memory[16 * 32:96 * 32]), bytes(80 * 32))


class Sound(unittest.TestCase):
    def test_reserved_views_cover_melody_with_skipped_vblanks(self):
        for pcm in (False, True):
            for dt in range(1, 9):
                d = Device()
                d.audio_writes = lambda pairs: None
                sound = S.Sound(d, pcm, True)
                sound.reserve_views()
                reserved = set(sound.views)
                for t in range(0, 1920, dt):
                    for tick in range(t, t + dt):
                        sound.tick(tick, tick == t + dt - 1)
                    sound.send()
                self.assertEqual(set(sound.views), reserved, (pcm, dt, set(sound.views) - reserved))

    def test_steady_played_matches_original_at_time_boundaries(self):
        sound = S.Sound(Device(), True, True)
        for length in (0, 100, 23040, 48000, 96000):
            sound.length[0] = length
            for elapsed in (-1, 0, 1, 20833, 500000, 999999, 1000000, 23000000, 500000000):
                with patch.object(S, 'ticks_diff', lambda now, start: elapsed):
                    sound.steady = False
                    original = sound.played(0, 0)
                    sound.steady = True
                    self.assertEqual(sound.played(0, 0), original, (length, elapsed))

    def test_piano_asset_is_the_c_sample(self):
        header = (ROOT / 'software/pico/piano_c4_sample.h').read_text()
        values = [int(v) for v in re.findall(r'-?\d+', header[header.index('{') + 1:header.rindex('}')])]
        self.assertEqual((Path(ASSETS) / 'piano_c4.pcm').read_bytes(), bytes(v & 255 for v in values))

    def test_piano_notes_match_c(self):
        self.check_piano_notes_match_c(4096)
        self.check_piano_notes_match_c(8192)

    def check_piano_notes_match_c(self, work_size):
        demo = Demo()
        demo.d = d = Device()
        demo.work = bytearray(work_size)
        demo.piano = ASSETS + '/piano_c4.pcm'
        demo.window = bytearray(S.PIANO_WINDOW)
        demo.sound = S.Sound(d, True, True)
        demo.loading = lambda what: None
        reads = []
        real_open = open

        class Recorded:
            """The file, recording how much each readinto() asks for."""
            def __init__(self, f):
                self.f = f
            def readinto(self, buf):
                reads.append(len(buf))
                return self.f.readinto(buf)
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                self.f.close()
        S.open = lambda path, mode: Recorded(real_open(path, mode))
        try:
            self.assertEqual(S.Sakura.upload_piano(demo), 685700)
        finally:
            del S.open
        # One pass over the file through the window, never the whole recording at once.
        self.assertLessEqual(max(reads), S.PIANO_WINDOW)
        self.assertLess(sum(reads), 72000 + 2 * S.PIANO_WINDOW)
        notes = []
        for n in range(S.NOTES):
            for short in range(2):
                base = S.PSRAM_SHORT_NOTES + n * S.SHORT_SLOT if short else S.PSRAM_NOTES + n * S.NOTE_SLOT
                notes.append(d.memory[base:base + demo.sound.note_len[n][short]])
        self.assertEqual(sha(*notes), C_SHA256['piano'])

    def test_psg_register_writes_match_c(self):
        d = Device()
        sound = S.Sound(d, False, True)
        sound.init(bytearray(8192))
        for t in range(2000):
            d.audio_log.append('frame %d' % t)
            sound.tick(t, True)
            sound.send()
            d.audio_commit()
        self.assertEqual(sha(('\n'.join(d.audio_log) + '\n').encode()), C_SHA256['psg_only_audio'])

    def test_skipped_vblanks_keep_tempo_and_write_gains_once(self):
        def play(every):
            d = Device()
            sound = S.Sound(d, False, True)
            per_update = []
            for t in range(0, 960, every):    # one update per `every` VBlanks
                for tick in range(t, t + every):
                    sound.tick(tick, tick == t + every - 1)
                start = len(d.audio_log)
                sound.send()
                per_update.append([int(w.split()[0]) for w in d.audio_log[start:]])
            return per_update, (sound.noise, sound.bass, sound.bell, sound.lead)
        smooth, end1 = play(1)
        skipping, end4 = play(4)
        # The drum notes land on the same eighth notes and the envelopes end alike.
        drums = lambda updates: sum(u.count(3 * 16 + R.AUDIO_NOISE_PERIOD_L) for u in updates)
        self.assertEqual(drums(smooth), drums(skipping))
        self.assertEqual(end1, end4)
        # Every update writes each envelope gain once, however many VBlanks it covers.
        for update in skipping:
            gains = sorted(i for i in update if i % 16 == R.AUDIO_GAIN_L)
            self.assertEqual(gains, [2 * 16 + 4, 3 * 16 + 4, 4 * 16 + 4, 5 * 16 + 4])


class Optimized(unittest.TestCase):
    """Each main-loop optimization against the code it replaces."""

    def test_palette_tables_match_palette_frame(self):
        fast = S.PaletteFrame()
        a, b = bytearray(512), bytearray(512)
        S.build_palette(a, 0)
        S.build_palette(b, 0)
        for t in list(range(0, 3000)) + [3000 + 7 * i for i in range(400)] + [216000, 216003]:
            S.palette_frame(a, t)
            fast(b, t)
            self.assertEqual(a, b, t)

    def test_oam_hoisted_divisions_match_original(self):
        xs, phases = petals()
        for lines in (180, 240):
            for t in list(range(0, 300, 7)) + list(TIMES) + [999999]:
                expected = oam_frame(xs, phases, lines, t)
                p = array('i', [t, lines, t * 37 // 16, t * 21 // 16, t * 11 // 16])
                out = bytearray(2048)
                H.K.build_oam_fast(out, xs, phases, S.SINE_BYTES, S.LAYERS, p)
                self.assertEqual(out, expected, (lines, t))

    def test_allocation_free_replacements_are_exact(self):
        # The gust sweep's whole-hertz steps: 700 .. 700 + 120 * 22 + 64 * 6, and beyond.
        for hz in range(0, 4096):
            self.assertEqual(S.step_whole_hz(hz), S.step_hz(hz), hz)
        # The lantern flame in native words against mix() in Python integers.
        for key in list(range(0, 3000)) + [72000 + 7919 * i for i in range(300)] + [(1 << 30) - 1]:
            f = S.mix(key)
            self.assertEqual(S.K.flame(key), S.rgb(15, 10 + f % 4, 3 + (f >> 8) % 3), key)
        self.assertEqual(S.SEMI_STEPS[-3], S.semi_step(-3))

    def test_band_template_matches_bands(self):
        for lines in (240, 180):
            for rscroll in (True, False):
                for copy in (True, False):
                    slow, quick = Demo(), Demo()
                    for demo in (slow, quick):
                        demo.ext, demo.lines, demo.rscroll, demo.copy = bytearray(80), lines, rscroll, copy
                    quick.bands = lambda t: S.Sakura.bands(quick, t)
                    S.Sakura.bands_template(quick)
                    for t in list(range(0, 1100, 3)) + [216000, 999999]:
                        n = S.Sakura.bands(slow, t)
                        self.assertEqual(S.Sakura.bands_fast(quick, t), n)
                        self.assertEqual(slow.ext[:n], quick.ext[:n], (lines, rscroll, copy, t))

    def test_hud_by_difference_matches_full_redraw(self):
        self.check_hud_by_difference(())
        self.check_hud_by_difference(('hudascii',))
        self.check_hud_by_difference(('hudascii', 'hudbuf'))
        self.check_hud_by_difference(('hudascii', 'hudbuf', 'hudglyph'))

    def check_hud_by_difference(self, opt):
        import random
        rng = random.Random(3)
        full, diff = Demo(), Demo()
        for demo in (full, diff):
            demo.d = Device()
            demo.text = S.Text(FONT)
            demo.hud_rows = [b'', b'']
            demo.upload = (lambda demo: lambda first, tiles, row=None: S.Sakura.upload(demo, first, tiles, row))(demo)
        diff.hud_strips = [diff.text.strip, bytearray(4096)]
        diff.hud_placed = [None, None]
        diff.opt = opt
        for name in ('hud_prepare', 'hud_paint', 'hud_upload'):   # the loop's separate steps
            setattr(diff, name, getattr(S.Sakura, name).__get__(diff))
        fixed = H.Hud(diff) if 'hudbuf' in opt else None
        hud = {'fps10': 600, 'status': None, 'overflow': 0, 'underrun': 0, 'line_underrun': 0,
               'psram_bytes': 0, 'psram_kbs': 0, 'errors': 0}
        sent = []
        for step in range(150):
            if step:
                hud['fps10'] = rng.choice((600, 598, 437, 1, 999, hud['fps10']))
                hud['psram_bytes'] += rng.choice((0, 5, 70000, 1 << 20, 3 << 22))
                hud['psram_kbs'] = rng.choice((0, 9, 345, 12345, hud['psram_kbs']))
                if rng.random() < 0.1:
                    hud['overflow'] += rng.choice((1, 9, 90))
                if rng.random() < 0.1:
                    hud['underrun'] += rng.choice((1, 12))
                if rng.random() < 0.05:
                    hud['errors'] |= rng.choice((0x20, 0x80, 0x01))
                    hud['line_underrun'] += 1
            S.Sakura.draw_hud(full, hud)
            sent.append(sum(fixed.update(hud, row) if fixed else
                            S.Sakura.hud_row(diff, row, S.Sakura.hud_runs(diff, hud, row)) for row in range(2)))
            self.assertEqual(full.d.memory[16 * 32:96 * 32], diff.d.memory[16 * 32:96 * 32], step)
        self.assertEqual(sent[0], 80)
        self.assertLess(sum(sent[1:]) / len(sent[1:]), 40, 'mostly a few tiles per update')
        if 'hudascii' in opt and not fixed:
            self.assertFalse(any(s.startswith(('FPS ', 'ERR ')) or s[0].isdigit()
                                 for s in diff.text.layouts), 'numeric layouts do not enter the cache')
        if fixed:
            self.assertEqual([fixed.update(hud, row) for row in range(2)], [0, 0])

    def test_fixed_hud_number_fields_match_formatting(self):
        tx = S.Text(FONT)
        out = bytearray(192)
        reverse = {slot: chr(code) for code, slot in tx.slots.items()}
        for value in (0, 1, 9, 10, 15, 16, 99, 100, 255, 256, 595, 600, 999, 1000, 0x3fffffff):
            for mode, expected in ((0, '%d' % value),
                                   (1, 'FPS %d.%d' % (value // 10, value % 10)),
                                   (2, 'ERR %02X' % value)):
                n = H.K.number_field(out, tx.atlas, 0, value, mode, 0)
                self.assertEqual(''.join(reverse[out[4 * i + 2]] for i in range(n)), expected)
            for kbs in (0, 9, 345, 0x3fffffff):
                n = H.K.number_field(out, tx.atlas, 0, value, 3, kbs)
                self.assertEqual(''.join(reverse[out[4 * i + 2]] for i in range(n)),
                                 '%d.%02dMB %dKB/s' % (value // 100, value % 100, kbs))

    def test_fixed_hud_float32_rounding(self):
        import random
        import struct
        from viper_emulator import int32_checked

        def f32(x):
            return struct.unpack('<f', struct.pack('<f', x))[0]

        def expected(n):
            value = f32(n) / 1048576
            initial = int(f32(f32(value * 100) + 0.5))
            low = int(value * 100)
            return min((low, low + 1), key=lambda c:
                       (abs(f32(c / 100) - value), c % 10 != 0, c != initial))

        rng = random.Random(931)
        values = [0, 1, 131072, 655360, 1179648, 1221591, 10732175,
                  16782458, 16782459, 16782460, 0x3fffffff]
        values += [rng.randrange(1 << 30) for _ in range(2000)]
        checked = int32_checked(H.K.cents)
        for value in values:
            self.assertEqual(checked(value), expected(value), value)

    def test_fixed_hud_float32_fields_match_full_pixels(self):
        full = S.Sakura(Device(), pcm=False, font=FONT, assets=ASSETS)
        diff = S.Sakura(Device(), pcm=False, font=FONT, assets=ASSETS)
        with patch.object(H, 'FLOAT32', True):
            fixed = H.Hud(diff)
        cases = ((0, 0), (131072, 13), (655360, 63), (1179648, 113),
                 (1221591, 117), (16782458, 1600), (16782459, 1601),
                 (104857600, 10000), (0x3fffffff, 102400), (0, 0))
        for i, (bytecount, hundredths) in enumerate(cases):
            hud = {'fps10': 598, 'status': None, 'overflow': i, 'underrun': 0,
                   'line_underrun': 0, 'psram_bytes': bytecount, 'psram_kbs': i * 345,
                   'errors': 0x20 if i & 1 else 0}
            # Feed the full renderer the already-established RP2 decimal value;
            # CPython's own binary ties/float size differ from the RP2 formatter.
            expected = dict(hud, psram_bytes=hundredths * 1048576 / 100)
            full.draw_hud(expected)
            fixed.update(hud, 0)
            fixed.update(hud, 1)
            self.assertEqual(full.d.memory[16 * 32:96 * 32], diff.d.memory[16 * 32:96 * 32], bytecount)

    def test_native_bandwidth_matches_unbounded_integer_expression(self):
        import random
        from viper_emulator import int32_checked
        rng = random.Random(912)
        checked = int32_checked(H.K.bandwidth)
        cases = [(n, elapsed) for n in (0, 1, 65535, 65536, 1 << 20, 1 << 24, 0x3fffffff)
                 for elapsed in (1000000, 1000123, 2000000, 0x7ffffff)]
        cases += [(rng.randrange(1 << 30), rng.randrange(1000000, 1 << 27)) for _ in range(300)]
        for n, elapsed in cases:
            self.assertEqual(checked(n, elapsed), n * 1000000 // elapsed // 1024, (n, elapsed))

    def test_fixed_hud_large_counter_fallback_and_reentry(self):
        full = S.Sakura(Device(), pcm=False, font=FONT, assets=ASSETS)
        diff = S.Sakura(Device(), pcm=False, font=FONT, assets=ASSETS)
        fixed = H.Hud(diff)
        hud = {'fps10': 600, 'status': None, 'overflow': 0, 'underrun': 0,
               'line_underrun': 0, 'psram_bytes': 0, 'psram_kbs': 0, 'errors': 0}
        for overflow, kbs in ((0, 0), (1 << 30, 300), (7, 300),
                              (7, 10 ** 50), (0, 0), (-1, 0), (0, 0)):
            hud['overflow'], hud['psram_kbs'] = overflow, kbs
            full.draw_hud(hud)
            for row in range(2):
                fixed.update(hud, row)
            self.assertEqual(full.d.memory[16 * 32:96 * 32], diff.d.memory[16 * 32:96 * 32])

    def test_fixed_hud_dirty_glyphs_limit_transfer(self):
        demo = S.Sakura(Device(), pcm=False, font=FONT, assets=ASSETS)
        fixed = H.Hud(demo)
        hud = {'fps10': 600, 'status': None, 'overflow': 0, 'underrun': 0,
               'line_underrun': 0, 'psram_bytes': 1048576, 'psram_kbs': 345, 'errors': 0}
        self.assertEqual(fixed.update(hud, 0), 40)
        self.assertEqual(fixed.update(hud, 1), 40)
        hud['fps10'] = 601
        self.assertLessEqual(fixed.update(hud, 0), 2)
        hud['psram_bytes'] += 11000
        self.assertLessEqual(fixed.update(hud, 1), 2)
        hud['psram_kbs'] = 346
        self.assertLessEqual(fixed.update(hud, 1), 2)

    def test_every_option_alone_and_together_passes(self):
        for opt in [()] + [(o,) for o in S.OPTS] + [('steady',), S.OPTS, S.STEADY_OPTS]:
            d = Device()
            d.vblanks_per_read = 2
            stats = S.Stats()
            demo = S.Sakura(d, font=FONT, assets=ASSETS, pcm=False, opt=opt)
            demo.load()
            self.assertTrue(demo.loop(0.3, stats), opt)
            self.assertEqual(d.busy, 0)
            self.assertGreater(d.copies, 0)
            self.assertEqual(d.ext[R.EXT_RS_COUNT], S.BANDS + 1)
            self.assertGreater(stats.n, 3)
            # The fake counter moves on every read: a constant cadence means one shown frame per update.
            self.assertEqual(sum(1 for c in stats.cadence if c), 1, opt)
            self.assertEqual(stats.vblanks, sum(c * stats.cadence[c] for c in range(16)))
            stats.report(' '.join(opt) or 'none', stats.seconds)


class Run(unittest.TestCase):
    def test_display_count_waits_for_successful_commit_application(self):
        d = Device()
        demo = S.Sakura(d, pcm=False, font=FONT, assets=ASSETS)
        demo.load()
        before = d.commits
        d.interrupt_commit = before + 12
        stats = S.Stats()
        self.assertTrue(demo.loop(0, stats))
        # The 12th commit is interrupted; the preceding 11 have already
        # been observed idle by wait_status, including the final iteration.
        self.assertEqual(demo.displayed, 11)
        self.assertEqual(stats.confirmed, 11)
        self.assertEqual(d.busy, 0)

    def test_keyboard_warmup_does_not_consume_pending_key(self):
        from types import SimpleNamespace
        reads = []
        stream = SimpleNamespace(read=lambda n: reads.append('q') or 'q')
        poll = SimpleNamespace(register=lambda *args: None,
                               ipoll=lambda timeout: iter(((stream, 1),)),
                               poll=lambda timeout: ())
        with patch.dict(sys.modules, {'select': SimpleNamespace(poll=lambda: poll, POLLIN=1)}):
            with patch.object(S.sys, 'stdin', stream):
                pressed = S._keyboard()
                self.assertEqual(reads, [])
                self.assertTrue(pressed())
                self.assertEqual(reads, ['q'])

    def test_short_transactions_match_transport_and_release_busy(self):
        original, quick = Device(), Device()
        quick.transport.link = link = ShortLink(quick.transport)
        for d, opt in ((original, tuple(o for o in S.OPTS if o != 'short')), (quick, S.OPTS)):
            d.vblanks_per_read = 2
            d.interrupt_commit = 80
            self.assertTrue(S.run(0, device=d, font=FONT, assets=ASSETS, pcm=False, opt=opt))
            self.assertEqual(d.busy, 0)
        self.assertGreater(link.calls, 100)
        self.assertEqual(original.memory, quick.memory)
        self.assertEqual(original.audio_log, quick.audio_log)
        self.assertEqual(original.ext, quick.ext)

    def run_demo(self, d, **kwargs):
        return S.run(0.4, device=d, font=FONT, assets=ASSETS, **kwargs)

    def test_runs_and_passes_on_both_heights(self):
        for height in (240, 180):
            d = Device(height)
            d.vblanks_per_read = 3
            self.assertTrue(self.run_demo(d, pcm=False))
            self.assertEqual(d.busy, 0)
            self.assertGreater(d.copies, 0)
            self.assertEqual(d.ext[R.EXT_RS_COUNT], S.BANDS + 1)
            self.assertEqual([d.audio[ch * 16 + R.AUDIO_CONTROL] for ch in range(6)], [0] * 6)
            self.assertFalse(d.closed, 'a passed-in device stays open')

    def test_device_errors_and_overflows_are_counted_not_fatal(self):
        d = Device(caps=0x53)       # no PSRAM: no COPY, no piano
        d.fail_commit, d.overflow_commit = 12, 15
        self.assertFalse(self.run_demo(d))
        self.assertGreater(d.commits, 16, 'the loop kept running')
        self.assertEqual(d.copies, 0)

    def test_ctrl_c_stops_sound_and_releases_busy(self):
        d = Device()
        d.interrupt_commit = 12
        self.assertTrue(self.run_demo(d, pcm=False, copy=False))
        self.assertEqual(d.commits, 12)
        self.assertEqual(d.copies, 0)
        self.assertEqual(d.busy, 0)
        self.assertEqual([d.audio[ch * 16 + R.AUDIO_CONTROL] for ch in range(6)], [0] * 6)

    def test_driver_without_ext_writes(self):
        d = Device()
        d.ext_writes = None           # kagura frozen into a UF2 from before ext_writes()
        self.assertTrue(self.run_demo(d, pcm=False))
        self.assertEqual(d.ext[R.EXT_RS_COUNT], S.BANDS + 1)

    def test_missing_piano_asset_falls_back_to_psg(self):
        d = Device()
        demo = S.Sakura(d, font=FONT, assets=str(EXAMPLES / 'no_such_assets'))
        self.assertFalse(demo.pcm)
        self.assertTrue(demo.copy)


if __name__ == '__main__':
    unittest.main()
