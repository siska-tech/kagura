# SPDX-License-Identifier: Apache-2.0
# kagura_audio binding and kagura.music on the unix port, against a device
# that models the FPGA's audio registers (shadow/active, two wave banks
# swapped by AUDIO_COMMIT, PHASE_RESET cleared on acceptance).
#   MICROPYPATH=software/micropython micropython software/audio/tests/test_binding.py
import micropython
import kagura_audio as ka
from kagura.music import AudioSession, Song, Pattern, instrument, note_name, KIND_NOISE, NOTE_OFF, NONE

failures = []


def check(cond, what):
    if not cond:
        failures.append(what)
        print('FAIL', what)


class FakeDevice:
    """The SDK device's audio surface, without the link."""

    def __init__(self, caps=0x5B):
        self.caps, self.busy, self.timeout_us = caps, 0, 100000
        self.shadow, self.active = bytearray(256), bytearray(256)
        self.banks = [bytearray(512), bytearray(512)]
        self.shadow_bank = 0
        self.commits = self.writes = self.wave_writes = 0
        self.log = []

    def _link(self):
        return None

    def write_memory(self, address, data):
        assert 0x9800 <= address and address + len(data) <= 0x9A00, 'wave shadow only'
        o = address - 0x9800
        self.banks[self.shadow_bank][o:o + len(data)] = data
        self.wave_writes += 1
        self.log.append('W')

    def audio_write(self, index, value):
        self.shadow[index] = value
        self.writes += 1
        self.log.append('R')

    def audio_commit(self):
        for v in range(6):
            assert not (v != 3 and self.shadow[v * 16 + 2] & 0x80), 'STEP too large'
        for v in range(6):
            self.shadow[v * 16 + 6] &= ~2
        self.active[:] = self.shadow
        self.shadow_bank ^= 1
        self.commits += 1
        self.log.append('C')

    def enabled(self, v):
        return self.active[v * 16 + 6] & 1

    def step(self, v):
        a = self.active
        return a[v * 16] | a[v * 16 + 1] << 8 | a[v * 16 + 2] << 16

    def wave(self, v):
        return self.banks[self.shadow_bank ^ 1][(v - 4) * 256:(v - 4) * 256 + (1 << self.active[v * 16 + 7])]


def demo_song():
    s = Song.new()
    s.title, s.author = 'TEST', 'KAGURA'
    p = s.patterns[0]
    for r, note in enumerate((49, 53, 56, 61)):
        o = p.offset(r * 4, 0)
        p.cells[o], p.cells[o + 1] = note, 0
    o = p.offset(0, 4)
    p.cells[o], p.cells[o + 1] = 25, 4
    o = p.offset(2, 3)
    p.cells[o], p.cells[o + 1] = 40, 3
    o = p.offset(8, 0)
    p.cells[o] = NOTE_OFF
    return s


def test_session_errors():
    try:
        ka.init(0x01)
        check(False, 'init without wave caps must fail')
    except OSError:
        pass
    ka.deinit()
    for f, args in ((ka.flush, (bytearray(90),)), (ka.advance, ()), (ka.gain, (0, 1, 1))):
        try:
            f(*args)
            check(False, 'call after deinit must raise')
        except RuntimeError:
            pass
    ka.init(0x5B)
    try:
        ka.play()
        check(False, 'play without a song')
    except RuntimeError:
        pass
    for bad in ((ka.gain, (6, 1, 1)), (ka.gain, (0, 256, 1)), (ka.pitch, (0, 128)), (ka.step, (0, 0x800000)),
                (ka.set_wave, (4, bytes(48))), (ka.set_wave, (2, bytes(32))), (ka.flush, (bytearray(10),))):
        try:
            bad[0](*bad[1])
            check(False, 'invalid argument accepted: %r' % (bad[1],))
        except ValueError:
            pass
    ka.deinit()


def test_song_round_trip():
    s = demo_song()
    data = s.to_bytes()
    t = Song.from_bytes(data)
    check(t.to_bytes() == data, 'round trip')
    check(t.title == 'TEST' and t.author == 'KAGURA', 'text')
    check(t.instruments[3][0] == KIND_NOISE, 'instruments')
    check(len(t.waves) == 2 and t.waves[0] == s.waves[0], 'waves')
    check(t.patterns[0].cells == s.patterns[0].cells, 'cells')
    check(note_name(49) == 'C-4' and note_name(NOTE_OFF) == '===' and note_name(0) == '---', 'names')
    p = Pattern(16, 2)
    p.resize(32)
    check(len(p.cells) == 32 * 2 * 5 and p.cells[16 * 2 * 5 + 1] == NONE, 'resize keeps empty cells')
    # Malformed files are refused with a reason.
    for i, value, reason in ((0, 0x41, 'not a KSNG'), (12, 0, 'header'), (48, 9, 'track voices')):
        bad = bytearray(data)
        bad[i] = value
        try:
            ka.validate(bad)
            check(False, 'malformed accepted at %d' % i)
        except ValueError as e:
            check(reason in str(e), 'reason %r in %r' % (reason, str(e)))
    for n in range(0, len(data), 7):
        try:
            Song.from_bytes(data[:n])
            check(False, 'truncated accepted')
        except ValueError:
            pass
    try:
        ka.pack(bytes(10), 16, 1, 1)
        check(False, 'short cells')
    except ValueError:
        pass
    try:
        ka.unpack_into(data, len(data) - 2, 16, 6, 6, bytearray(16 * 6 * 5))
        check(False, 'unpack past the end')
    except ValueError:
        pass
    s.instruments[0][2] = 16
    try:
        s.to_bytes()
        check(False, 'invalid instrument written')
    except ValueError:
        pass


def test_playback_through_device():
    d = FakeDevice()
    audio = AudioSession(d)
    check(d.commits == 1 and d.wave_writes == 2, 'first frame writes everything')
    check(d.log.index('W') < d.log.index('C') and d.log[-1] == 'C', 'waves and registers before the commit')
    song = demo_song()
    data = bytearray(song.to_bytes())
    audio.load(data)
    for i in range(len(data)):   # the binding keeps its own copy
        data[i] = 0
    ka.play(ka.SONG, 0, 0, 1000)
    t = 1000
    ka.advance(t)
    audio.send()
    check(d.enabled(0) and d.step(0) == ka.note_step(60), 'C-4 on voice 0')
    check(d.enabled(4) and d.step(4) == ka.note_step(36), 'C-2 on wave voice 4')
    check(bytes(d.wave(4)) == bytes(song.waves[0]), 'triangle in the active bank')
    tick = 20000                  # tempo 125
    for _ in range(12):
        t += tick
        audio.pump(t)
    check(d.enabled(3), 'noise drum at row 2')
    for _ in range(6 * 6):
        t += tick
        audio.pump(t)
    pos = audio.position()
    check(pos[0] == ka.PLAYING and pos[2] == 8, 'row 8, got %r' % (pos,))
    # Pause silences, resume brings the held notes back.
    ka.pause(t + 5)
    audio.send()
    check(not any(d.enabled(v) for v in range(6)), 'paused: silent')
    ka.resume(t + 10)
    audio.send()
    check(d.enabled(4), 'resumed')
    # A late pump plays every due tick: same position as on-time pumps.
    before = ka.stats()['ticks']
    t += 10 * tick
    ran = audio.pump(t + 10)
    check(ran in (10, 11) and ka.stats()['ticks'] == before + ran, 'late pump ran %d ticks' % ran)
    st = audio.stats()
    check(st['folded'] >= 9 and st['late_max_us'] >= 9 * tick, 'stats %r' % (st,))
    # Further behind than 250 ms (a long stall): resynchronise, like a pause.
    resyncs = st['resyncs']
    t += 64 * tick
    check(audio.pump(t) == 1 and ka.stats()['resyncs'] == resyncs + 1, 'resync')
    # Previews while stopped, then close silences everything.
    ka.stop()
    check(ka.preview(0, 61, 0, 3, t), 'preview')
    check(not ka.preview(0, 61, 4, 3, t), 'wave instrument on a pulse track is refused')
    audio.pump(t)
    check(d.enabled(0) and d.step(0) == ka.note_step(72), 'preview note')
    audio.close()
    check(not any(d.enabled(v) for v in range(6)), 'closed: silent')
    try:
        ka.advance()
        check(False, 'session closed')
    except RuntimeError:
        pass


def test_edit_while_playing():
    d = FakeDevice()
    audio = AudioSession(d)
    song = demo_song()
    audio.load(song.to_bytes())
    ka.play(ka.SONG, 0, 0, 0)
    t = 0
    for _ in range(30):
        audio.pump(t)
        t += 20000
    before = ka.position()
    o = song.patterns[0].offset(10, 1)
    song.patterns[0].cells[o], song.patterns[0].cells[o + 1] = 49, 1
    ka.load(song.to_bytes())
    check(ka.position() == before, 'reload keeps the position')
    for _ in range(32):
        audio.pump(t)
        t += 20000
    check(d.enabled(1), 'the edited note plays')
    audio.close()


def test_no_allocation():
    d = FakeDevice()
    audio = AudioSession(d)
    audio.load(demo_song().to_bytes())
    ka.play(ka.SONG, 0, 0, 0)
    pairs = bytearray(2 * ka.FRAME_PAIRS)
    t = 0
    micropython.heap_lock()
    try:
        for _ in range(500):
            ka.advance(t)
            ka.flush(pairs)
            ka.position()
            t += 20000
    finally:
        micropython.heap_unlock()
    check(ka.stats()['ticks'] == 500, 'ticks under heap_lock')
    audio.close()


def test_sizes():
    s = ka.sizes()
    print('SIZES', sorted(s.items()))
    check(s['state'] < 4096, 'static state under 4 KB')


for name in ('test_session_errors', 'test_song_round_trip', 'test_playback_through_device',
             'test_edit_while_playing', 'test_no_allocation', 'test_sizes'):
    globals()[name]()
print('kagura_audio binding: %d failures' % len(failures))
if failures:
    raise SystemExit(1)
