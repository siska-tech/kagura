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
            self.device.reg[offset + (i if inc else 0)] = value


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
    def test_piano_asset_is_the_c_sample(self):
        header = (ROOT / 'software/pico/piano_c4_sample.h').read_text()
        values = [int(v) for v in re.findall(r'-?\d+', header[header.index('{') + 1:header.rindex('}')])]
        self.assertEqual((Path(ASSETS) / 'piano_c4.pcm').read_bytes(), bytes(v & 255 for v in values))

    def test_piano_notes_match_c(self):
        demo = Demo()
        demo.d = d = Device()
        demo.work = bytearray(8192)
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


class Run(unittest.TestCase):
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
