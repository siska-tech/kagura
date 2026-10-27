# SPDX-License-Identifier: Apache-2.0
from . import regs as R
from .device import _range


class Audio:
    def __init__(self, device):
        self.device = device

    def tone(self, channel, frequency, left=64, right=64, duty=128, reset=True):
        """Configure pulse (0..2) or wave (4..5); caller audio_commit()."""
        if channel not in (0, 1, 2, 4, 5) or not 0 <= frequency < 24000:
            raise ValueError("tone channel/frequency")
        for value in (left, right, duty):
            _range(value, 0, 255, "tone gain/duty")
        if channel >= 4:
            self.device.require(R.CAPS_WAVE)
        step = round(frequency * 16777216 / 48000)
        base = channel * R.AUDIO_CH_STRIDE
        d = self.device
        d.busy += 1
        try:
            for i in range(3):
                d.audio_write(base + R.AUDIO_STEP_L + i, (step >> (8 * i)) & 255)
            d.audio_write(base + R.AUDIO_DUTY, duty)
            d.audio_write(base + R.AUDIO_GAIN_L, left)
            d.audio_write(base + R.AUDIO_GAIN_R, right)
            d.audio_write(base + R.AUDIO_CONTROL, R.AUDIO_CONTROL_ENABLE
                          | (R.AUDIO_CONTROL_PHASE_RESET if reset else 0))
        finally:
            d.busy -= 1

    def noise(self, period, left=32, right=32, reset=True):
        _range(period, 0, 65535, "noise period")
        _range(left, 0, 255, "left gain")
        _range(right, 0, 255, "right gain")
        d = self.device
        d.busy += 1
        try:
            base = 3 * R.AUDIO_CH_STRIDE
            for index, value in ((R.AUDIO_NOISE_PERIOD_L, period & 255),
                                 (R.AUDIO_NOISE_PERIOD_H, period >> 8),
                                 (R.AUDIO_GAIN_L, left), (R.AUDIO_GAIN_R, right),
                                 (R.AUDIO_CONTROL, 1 | (2 if reset else 0))):
                d.audio_write(base + index, value)
        finally:
            d.busy -= 1

    def wave(self, channel, samples):
        """Write one shadow wave bank. Call twice with commits at startup."""
        if channel not in (4, 5) or len(samples) not in (32, 64, 128, 256):
            raise ValueError("wave channel or length")
        self.device.require(R.CAPS_WAVE)
        self.device.busy += 1
        try:
            self.device.write_memory(0x9800 + (channel - 4) * 256, samples)
            self.device.audio_write(channel * 16 + R.AUDIO_LEN_LOG2,
                                    {32: 5, 64: 6, 128: 7, 256: 8}[len(samples)])
        finally:
            self.device.busy -= 1

    def stop(self, channel):
        _range(channel, 0, 5, "audio channel")
        self.device.audio_write(channel * 16 + R.AUDIO_CONTROL, 0)

    def _pcm_base(self, channel):
        self.device.require(R.CAPS_PSRAM)
        _range(channel, 0, 1, "PCM channel")
        return R.AUDIO_PCM_BASE + channel * R.AUDIO_PCM_STRIDE

    def pcm_status(self, channel):
        return self.device.audio_read(self._pcm_base(channel) + R.AUDIO_PCM_STATUS)

    def prepare_pcm(self, channel, start, end, loop=None):
        base = self._pcm_base(channel)
        if not 0x400000 <= start < end <= 0x800000:
            raise ValueError("PCM start/end")
        if loop is not None and not start <= loop < end:
            raise ValueError("PCM loop")
        d = self.device
        d.busy += 1
        try:
            d.fence()
            d.audio_write(base + R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_CLEAR)
            for offset, value in ((R.AUDIO_PCM_START_L, start), (R.AUDIO_PCM_END_L, end),
                                  (R.AUDIO_PCM_LOOP_L, start if loop is None else loop)):
                for i in range(3):
                    d.audio_write(base + offset + i, (value >> (8 * i)) & 255)
            d.audio_write(base + R.AUDIO_PCM_CONTROL,
                          R.AUDIO_PCM_CONTROL_LOOP_ENABLE if loop is not None else 0)
            d.audio_write(base + R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_PREPARE)
            def ready():
                status = self.pcm_status(channel)
                if status & (R.AUDIO_PCM_STATUS_UNDERRUN | R.AUDIO_PCM_STATUS_CONFIG_ERROR
                             | R.AUDIO_PCM_STATUS_MEMORY_ERROR):
                    raise OSError("PCM prepare status 0x%02x" % status)
                return bool(status & R.AUDIO_PCM_STATUS_READY)
            d._wait(ready, "PCM PREPARE")
        finally:
            d.busy -= 1

    def play_pcm(self, channel, left=64, right=64):
        base = self._pcm_base(channel)
        _range(left, 0, 255, "left gain")
        _range(right, 0, 255, "right gain")
        d = self.device
        d.busy += 1
        try:
            if not self.pcm_status(channel) & R.AUDIO_PCM_STATUS_READY:
                raise OSError("PCM must be prepared before play")
            d.audio_write(base + R.AUDIO_PCM_GAIN_L, left)
            d.audio_write(base + R.AUDIO_PCM_GAIN_R, right)
            control = d.audio_read(base + R.AUDIO_PCM_CONTROL)
            d.audio_write(base + R.AUDIO_PCM_CONTROL, control | R.AUDIO_PCM_CONTROL_ENABLE)
            d.audio_commit()
        finally:
            d.busy -= 1
