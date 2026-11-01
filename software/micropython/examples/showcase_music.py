# SPDX-License-Identifier: Apache-2.0
"""Quiet PSG interlude for the presentation cards (Am/F/C/G, 120 BPM)."""
from time import ticks_us, ticks_diff, ticks_add
from kagura import regs as R

CHORDS = ((57, 60, 64), (57, 60, 65), (55, 60, 64), (55, 59, 62))
STEPS = tuple(round(440 * 2 ** ((n - 69) / 12) * 16777216 / 48000) for n in range(96))


class Music:
    def __init__(self, d):
        self.d, self.n, self.next = d, 0, ticks_us()
        self.ops = bytearray(12)
        d.audio_write(R.AUDIO_MASTER_GAIN, 32)
        for ch, gain, duty in ((0, 12, 64), (2, 18, 128)):
            for index, value in ((R.AUDIO_GAIN_L, gain), (R.AUDIO_GAIN_R, gain),
                                 (R.AUDIO_DUTY, duty), (R.AUDIO_CONTROL, 1)):
                d.audio_write(ch * 16 + index, value)
        d.audio_commit()

    def play(self):
        now = ticks_us()
        if ticks_diff(now, self.next) < 0:
            return
        chord = CHORDS[self.n // 16 & 3]
        for ch, note, offset in ((0, chord[self.n % 3] + 12, 0), (2, chord[0] - 12, 6)):
            step = STEPS[note]
            for i in range(3):
                self.ops[offset + i * 2] = ch * 16 + R.AUDIO_STEP_L + i
                self.ops[offset + i * 2 + 1] = step >> (8 * i) & 255
        self.d.audio_writes(self.ops)
        self.d.audio_commit()
        self.n += 1
        self.next = ticks_add(now, 125000)  # late card COPYs do not trigger a burst

    def stop(self):
        for ch in (0, 2):
            self.d.audio_write(ch * 16 + R.AUDIO_CONTROL, 0)
        self.d.audio_commit()
