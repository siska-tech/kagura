# SPDX-License-Identifier: Apache-2.0
"""Music on KAGURA-9: the native audio HAL and KSNG player (kagura_audio).

    from kagura.music import AudioSession, Song
    with AudioSession(device) as audio:
        audio.load(song_bytes)        # a .ksng file, or Song(...).to_bytes()
        audio.play()
        while ...:
            audio.pump()      # at safe points: runs due ticks, sends one frame

Register logic lives in C (software/audio). This module only sends the
frames the HAL produces, through the same SDK device as the console and the
desktop: one hardware owner, one transport. pump() and send() allocate
nothing, so they may run under heap_lock().

Timing: ticks fall at exact times of the C clock, whenever pump() runs. A
late pump() plays the ticks it missed at once (the music state stays exact,
only the sound is late); stats() reports how late. See software/audio/README.md.
"""
import kagura_audio as _ka
from time import ticks_us, ticks_diff

WAVE_SHADOW = _ka.WAVE_SHADOW


class AudioSession:
    def __init__(self, device, clock=None):
        self.device = device
        # The player's time in us (uint32, wrapping): kagura_audio's own clock
        # unless clock() is given (tests drive time by hand).
        self.clock = clock
        _ka.init(device.caps)   # OSError(ENODEV) without HDMI audio and wave voices
        self._pairs = bytearray(2 * _ka.FRAME_PAIRS)
        # Wave uploads of 32..256 bytes: views made once, so send() allocates nothing.
        self._waves = tuple(tuple(_ka.wave(v)[:32 << k] for k in range(4)) for v in (4, 5))
        link = device._link()
        self._lpairs = link.audio_writes if link is not None else None
        self._lcommit = link.audio_commit if link is not None else None
        self._lwrite = link.write_memory if link is not None else None
        self.sent = 0                 # frames sent
        self.send_max_us = 0          # longest send(), for measurements
        self._open = True
        self.send()                   # the first frame writes everything: silence

    def send(self):
        """Sends the HAL's pending frame (wave uploads, registers, AUDIO_COMMIT)."""
        r = _ka.flush(self._pairs)
        if not r:
            return 0
        t0 = ticks_us()
        d = self.device
        n = r & 63
        d.busy += 1
        try:
            for w in (0, 1):
                if r >> (8 + w) & 1:
                    data = self._waves[w][r >> (10 + 2 * w) & 3]
                    if self._lwrite is not None:
                        self._lwrite(WAVE_SHADOW + 256 * w, data, d.timeout_us)
                    else:
                        d.write_memory(WAVE_SHADOW + 256 * w, data)
            if self._lpairs is not None:
                self._lpairs(self._pairs, n)
            else:
                p = self._pairs
                for i in range(n):
                    d.audio_write(p[2 * i], p[2 * i + 1])
            if r & 0x40:
                # The next commit waits for APPLY_BUSY first; no need to wait here.
                if self._lcommit is not None:
                    self._lcommit(d.timeout_us, False)
                else:
                    d.audio_commit()
        except BaseException:
            _ka.invalidate()      # the hardware state is unknown: rewrite it all next time
            raise
        finally:
            d.busy -= 1
        self.sent += 1
        dt = ticks_diff(ticks_us(), t0)
        if dt > self.send_max_us:
            self.send_max_us = dt
        return n

    def _now(self):
        return self.clock() if self.clock is not None else None

    def pump(self, now=None):
        """Runs the ticks due now and sends the result. Returns ticks run."""
        t = _ka.advance(self._now() if now is None else now)
        self.send()
        return t

    def invalidate(self):
        """After other code wrote audio registers (kagura.audio.Audio)."""
        _ka.invalidate()

    def close(self):
        """Silences every voice and stops PCM, then ends the session."""
        if not self._open:
            return
        self._open = False
        try:
            _ka.close()
            self.send()
        finally:
            _ka.deinit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # The player, for convenience (kagura_audio has the full API).
    def load(self, data):
        _ka.load(data)

    def play(self, mode=_ka.SONG, order=0, row=0):
        _ka.play(mode, order, row, self._now())

    def preview(self, track, note, inst, hold=24):
        """Plays a note on a track now; False if the instrument cannot play there."""
        return _ka.preview(track, note, inst, hold, self._now())

    def pause(self):
        _ka.pause(self._now())
        self.send()

    def resume(self):
        _ka.resume(self._now())
        self.send()

    def stop(self):
        _ka.stop()
        self.send()

    def position(self):
        """(state, order, row, tick)"""
        p = _ka.position()
        return p >> 24, p >> 16 & 255, p >> 8 & 255, p & 255

    def stats(self):
        s = _ka.stats()
        s['sent'] = self.sent
        s['send_max_us'] = self.send_max_us
        return s


# --- KSNG songs ---------------------------------------------------------------

KIND_PULSE, KIND_WAVE, KIND_NOISE = 0, 1, 2
NOTE_OFF = _ka.NOTE_OFF
NONE = _ka.NONE
CELL = _ka.CELL_BYTES
NOTE_NAMES = ('C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-')


def note_name(note):
    """Cell note 1..96 -> 'C-4'; 97 -> '==='; 0 -> '---'."""
    if note == 0:
        return '---'
    if note == NOTE_OFF:
        return '==='
    n = note - 1
    return NOTE_NAMES[n % 12] + str(n // 12)


def instrument(kind=KIND_PULSE, data=128, volume=15, pan=128, attack=0, decay=0, sustain=15, release=0):
    return bytearray((kind, data, volume, pan, attack, decay, sustain, release))


def _text(s):
    b = s.encode()[:16]
    for c in b:
        if not 0x20 <= c <= 0x7E:
            raise ValueError('title/author: printable ASCII')
    return b + bytes(16 - len(b))


class Pattern:
    """rows x tracks cells of 5 bytes: note, instrument, volume, effect, parameter."""

    def __init__(self, rows, tracks, cells=None):
        if rows not in (16, 32, 64):
            raise ValueError('rows: 16, 32 or 64')
        self.rows, self.tracks = rows, tracks
        if cells is None:
            cells = bytearray(rows * tracks * CELL)
            for i in range(rows * tracks):
                cells[i * CELL + 1] = NONE
                cells[i * CELL + 2] = NONE
        self.cells = cells

    def offset(self, row, track):
        return (row * self.tracks + track) * CELL

    def resize(self, rows):
        """Keeps the rows that still fit; new rows are empty."""
        other = Pattern(rows, self.tracks)
        n = min(rows, self.rows) * self.tracks * CELL
        other.cells[:n] = self.cells[:n]
        self.rows, self.cells = rows, other.cells


class Song:
    """A KSNG song in an editable form; to_bytes() / from_bytes() convert."""

    def __init__(self, voices=(0, 1, 2, 3, 4, 5), rows=64):
        self.title = 'UNTITLED'
        self.author = ''
        self.voices = list(voices)
        self.tempo, self.speed = 125, 6
        self.loop, self.loop_order = True, 0
        self.instruments = [instrument()]
        self.waves = []
        self.patterns = [Pattern(rows, len(self.voices))]
        self.orders = [0]

    @property
    def tracks(self):
        return len(self.voices)

    def to_bytes(self):
        n_inst, tracks = len(self.instruments), self.tracks
        head = bytearray(48)
        head[0:4] = b'KSNG'
        head[4:14] = bytes((1, 1 if self.loop else 0, tracks, n_inst, len(self.waves), len(self.patterns),
                            len(self.orders), self.loop_order, self.speed, self.tempo))
        head[16:32] = _text(self.title)
        head[32:48] = _text(self.author)
        parts = [head, bytes(self.voices), bytes(self.orders)]
        parts.extend(bytes(i) for i in self.instruments)
        for w in self.waves:
            log2 = {32: 5, 64: 6, 128: 7, 256: 8}.get(len(w))
            if log2 is None:
                raise ValueError('wave length: 32, 64, 128 or 256')
            parts.append(bytes((log2,)))
            parts.append(bytes(w))
        for p in self.patterns:
            packed = _ka.pack(p.cells, p.rows, tracks, n_inst)
            parts.append(bytes((p.rows, len(packed) & 255, len(packed) >> 8)))
            parts.append(packed)
        data = b''.join(parts)
        _ka.validate(data)
        return data

    @classmethod
    def from_bytes(cls, data):
        _ka.validate(data)   # everything below is in bounds
        tracks, n_inst, n_waves, n_pat, n_ord = data[6], data[7], data[8], data[9], data[10]
        s = cls(voices=data[48:48 + tracks])
        s.loop, s.loop_order, s.speed, s.tempo = bool(data[5] & 1), data[11], data[12], data[13]
        s.title = bytes(data[16:32]).rstrip(b'\0').decode()
        s.author = bytes(data[32:48]).rstrip(b'\0').decode()
        at = 48 + tracks
        s.orders = list(data[at:at + n_ord])
        at += n_ord
        s.instruments = [bytearray(data[at + 8 * i:at + 8 * i + 8]) for i in range(n_inst)]
        at += 8 * n_inst
        s.waves = []
        for _ in range(n_waves):
            n = 1 << data[at]
            s.waves.append(bytearray(data[at + 1:at + 1 + n]))
            at += 1 + n
        s.patterns = []
        for _ in range(n_pat):
            rows, size = data[at], data[at + 1] | data[at + 2] << 8
            p = Pattern(rows, tracks)
            _ka.unpack_into(data, at + 3, rows, tracks, n_inst, p.cells)
            s.patterns.append(p)
            at += 3 + size
        return s

    @classmethod
    def new(cls):
        """Six tracks, one per voice, and a starter instrument for each kind."""
        s = cls()
        s.waves = [triangle_wave(), saw_wave()]
        s.instruments = [
            instrument(KIND_PULSE, 128, 12, 128, 0, 8, 9, 4),     # 00 square lead
            instrument(KIND_PULSE, 64, 11, 128, 0, 4, 10, 2),     # 01 25% pulse
            instrument(KIND_PULSE, 32, 10, 128, 0, 2, 8, 2),      # 02 12.5% pulse
            instrument(KIND_NOISE, 0, 13, 128, 0, 6, 0, 0),       # 03 noise drum
            instrument(KIND_WAVE, 0, 14, 128, 0, 0, 15, 3),       # 04 triangle bass
            instrument(KIND_WAVE, 1, 10, 128, 1, 6, 10, 4),       # 05 saw
        ]
        return s


def triangle_wave(n=32):
    return bytearray((((4 * i * 127 // n) if i < n // 2 else (4 * (n - i) * 127 // n)) - 127) & 255
                     for i in range(n))


def saw_wave(n=32):
    return bytearray(((i * 255 // (n - 1)) - 128) & 255 for i in range(n))
