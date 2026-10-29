# SPDX-License-Identifier: Apache-2.0
"""Bounded priority audio queue. Existing Audio API; no driver changes."""
from array import array
from time import ticks_diff, ticks_add
from kagura.audio import Audio
from kagura import regs as R

SHOT, ENEMY_SHOT, POWERUP, EXPLOSION, STAGE, SPECIAL, WARNING = range(7)
PRIORITY = (1, 1, 4, 3, 5, 6, 5)
PCM_NAMES = ('', '', 'powerup', 'explosion', 'stage', 'special', '')
FREQUENCIES = (1200, 580, 1500, 0, 660, 1800, 320)
STEPS = tuple(round(frequency * 16777216 / 48000) for frequency in FREQUENCIES)
ERROR_MASK = R.AUDIO_PCM_STATUS_UNDERRUN | R.AUDIO_PCM_STATUS_CONFIG_ERROR | R.AUDIO_PCM_STATUS_MEMORY_ERROR


class Sound:
    def __init__(self, device, psg=True, pcm=True, music=True, assets='star_runner_assets', bgm_gain=224):
        if not isinstance(bgm_gain, int) or not 0 <= bgm_gain <= 255:
            raise ValueError('bgm_gain must be 0..255')
        self.device, self.audio = device, Audio(device)
        available = bool(device.caps & R.CAPS_HDMI_AUDIO)
        self.psg = available and psg
        self.wave = self.psg and bool(device.caps & R.CAPS_WAVE)
        self.pcm = available and pcm and bool(device.caps & R.CAPS_PSRAM)
        self.music = music
        self.assets = assets
        self.bgm_gain = bgm_gain
        self.reason = ''
        self.events = bytearray(8)
        self.count = self.dropped = 0
        self.deadlines = array('I', [0] * 6)
        self.on = bytearray(6)
        self.samples = {}
        self.pcm_priority = 0
        self.pcm_until = 0
        self.pending_pcm = None
        self.pending_since = 0
        self.status0 = self.status1 = self.audio_status = 0
        self.bgm_inactive = 0
        self.pcm_fault = bytearray(2)
        self.poll_frame = 0
        self.max_commands = 2
        self.channel_frequency = array('H', [0] * 6)

    def initialize(self):
        if not (self.psg or self.pcm):
            # BASE must be silent even if an earlier application left a voice
            # enabled. This one-time stop is outside the measurement interval.
            if self.device.caps & R.CAPS_HDMI_AUDIO:
                self.stop(force=True)
            return
        # Own the audio engine during the demo; deterministic starting state.
        self.stop()
        if self.wave:
            for _ in range(2):
                for channel in (4, 5):
                    # Wavetable fallback keeps PSG mode asset-independent.
                    try:
                        with open(self.assets + '/wave%d.bin' % (channel - 4), 'rb') as stream:
                            data = stream.read(32)
                    except OSError:
                        data = bytes(((i * 8 - 124) if channel == 4 else
                                      (96 if i < 16 else -96)) & 255 for i in range(32))
                    self.audio.wave(channel, data)
                self.device.audio_commit()
        if self.psg:
            for channel in range(6):
                if channel >= 4 and not self.wave:
                    continue
                if channel == 3:
                    self.audio.noise(180, left=72, right=72)
                else:
                    frequency = (1200, 580, 1500, 0, 660, 1800)[channel]
                    gain = (48, 40, 72, 0, 64, 64)[channel]
                    self.audio.tone(channel, frequency, left=gain, right=gain,
                                    duty=64 if channel == 0 else 128)
                    self.channel_frequency[channel] = frequency
                self.audio.stop(channel)
            self.device.audio_commit()
        if self.pcm:
            try:
                import json
                with open(self.assets + '/manifest.json') as stream:
                    manifest = json.load(stream)
                if manifest['rate'] != 48000 or manifest['format'] != 'signed8-mono':
                    raise ValueError('PCM requires signed8-mono/48000Hz')
                previous_end = 0x400000
                for sample in manifest['samples']:
                    start, end = sample['start'], sample['end']
                    if not previous_end <= start < end <= 0x800000:
                        raise ValueError('PCM ranges overlap or exceed PSRAM')
                    previous_end = end
                    self.samples[sample['name']] = sample
                for name in ('bgm', 'explosion', 'powerup', 'stage', 'special'):
                    if name not in self.samples:
                        raise ValueError('missing PCM sample ' + name)
                buffer = bytearray(1024)
                view = memoryview(buffer)
                for sample in manifest['samples']:
                    address = sample['start']
                    with open(self.assets + '/' + sample['file'], 'rb') as stream:
                        while True:
                            size = stream.readinto(buffer)
                            if not size:
                                break
                            if address + size > sample['end']:
                                raise ValueError('PCM file longer than manifest')
                            self.device.write_memory(address, view if size == len(buffer) else view[:size])
                            address += size
                    if address != sample['end']:
                        raise ValueError('PCM file shorter than manifest')
                self.device.fence()
                base = R.AUDIO_PCM_BASE + R.AUDIO_PCM_STRIDE
                self.device.audio_write(base + R.AUDIO_PCM_GAIN_L, 144)
                self.device.audio_write(base + R.AUDIO_PCM_GAIN_R, 144)
                if self.music:
                    sample = self.samples['bgm']
                    self.audio.prepare_pcm(0, sample['start'], sample['end'], loop=sample['start'])
                    self.audio.play_pcm(0, left=self.bgm_gain, right=self.bgm_gain)
            except OSError as error:
                # Missing local assets permit the legacy no-assets invocation.
                # Communication/device errors must propagate, never be hidden.
                if getattr(error, 'errno', None) != 2 and (not error.args or error.args[0] != 2):
                    raise
                self.pcm = False
                self.reason = 'PCM assets missing: ' + self.assets
        self.enqueue(STAGE)

    def enqueue(self, event):
        for i in range(self.count):
            if self.events[i] == event:
                self.dropped += 1
                return
        if self.count < len(self.events):
            self.events[self.count] = event
            self.count += 1
        else:
            weakest = 0
            for i in range(1, self.count):
                if PRIORITY[self.events[i]] < PRIORITY[self.events[weakest]]:
                    weakest = i
            if PRIORITY[event] > PRIORITY[self.events[weakest]]:
                self.events[weakest] = event
            self.dropped += 1

    def pcm_command(self, channel, command):
        self.device.audio_write(R.AUDIO_PCM_BASE + channel * R.AUDIO_PCM_STRIDE + R.AUDIO_PCM_CMD, command)

    def _prepare_effect(self, event, now):
        sample = self.samples[PCM_NAMES[event]]
        # Nonblocking equivalent of prepare_pcm. Upload/fence already completed.
        # Touch ch1 only: PREPARE stops only this channel; BGM ch0 is unchanged.
        self.pcm_command(1, R.AUDIO_PCM_CMD_STOP | R.AUDIO_PCM_CMD_CLEAR)
        base = R.AUDIO_PCM_BASE + R.AUDIO_PCM_STRIDE
        for offset, value in ((R.AUDIO_PCM_START_L, sample['start']),
                              (R.AUDIO_PCM_END_L, sample['end'])):
            for i in range(3):
                self.device.audio_write(base + offset + i, (value >> (i * 8)) & 255)
        self.device.audio_write(base + R.AUDIO_PCM_CONTROL, 0)
        self.pcm_command(1, R.AUDIO_PCM_CMD_PREPARE)
        self.pending_pcm = event
        self.pending_since = now
        self.pcm_priority = PRIORITY[event]

    def service(self, now):
        dirty = False
        for channel in range(6):
            if self.on[channel] and ticks_diff(now, self.deadlines[channel]) >= 0:
                self.audio.stop(channel)
                self.on[channel] = 0
                dirty = True
        if self.pending_pcm is not None and not self.pcm_fault[1]:
            status = self.audio.pcm_status(1)
            self.status1 = status
            if status & ERROR_MASK:
                self.pcm_fault[1] = 1  # Preserve sticky bits for the monitor.
                self.pending_pcm = None
            elif status & R.AUDIO_PCM_STATUS_READY:
                base = R.AUDIO_PCM_BASE + R.AUDIO_PCM_STRIDE
                self.device.audio_write(base + R.AUDIO_PCM_CONTROL, R.AUDIO_PCM_CONTROL_ENABLE)
                sample = self.samples[PCM_NAMES[self.pending_pcm]]
                self.pcm_until = ticks_add(now, (sample['end'] - sample['start']) // 48)
                self.pending_pcm = None
                dirty = True
            elif ticks_diff(now, self.pending_since) > 1000:
                raise OSError('PCM1 PREPARE timed out')
        for _ in range(min(self.max_commands, self.count)):
            strongest = 0
            for i in range(1, self.count):
                if PRIORITY[self.events[i]] > PRIORITY[self.events[strongest]]:
                    strongest = i
            event = self.events[strongest]
            self.count -= 1
            self.events[strongest] = self.events[self.count]
            if self.psg:
                channel = (0, 1, 2, 3, 4 if self.wave else 2,
                           5 if self.wave else 2, 5 if self.wave else 1)[event]
                # Gains/duty/noise period are static, configured once. A shot
                # normally costs one CONTROL write instead of seven writes.
                if channel != 3 and self.channel_frequency[channel] != FREQUENCIES[event]:
                    step = STEPS[event]
                    for i in range(3):
                        self.device.audio_write(channel * 16 + R.AUDIO_STEP_L + i, (step >> (i * 8)) & 255)
                    self.channel_frequency[channel] = FREQUENCIES[event]
                self.device.audio_write(channel * 16 + R.AUDIO_CONTROL,
                                        R.AUDIO_CONTROL_ENABLE | R.AUDIO_CONTROL_PHASE_RESET)
                self.on[channel] = 1
                self.deadlines[channel] = ticks_add(now, (60, 90, 200, 170, 300, 250, 180)[event])
                dirty = True
            if self.pcm and PCM_NAMES[event] and not self.pcm_fault[1]:
                if (self.pending_pcm is None and ticks_diff(now, self.pcm_until) >= 0
                        or PRIORITY[event] > self.pcm_priority):
                    self._prepare_effect(event, now)
        if dirty:
            # Exactly one batched commit at most per service call. Both wave
            # banks were initialized identically; ch0 PCM control is preserved.
            self.device.audio_commit()

    def monitor(self):
        if not (self.psg or self.pcm):
            return
        self.audio_status = self.device.audio_read(R.AUDIO_STATUS)
        if self.pcm:
            self.status0 = self.audio.pcm_status(0)
            self.status1 = self.audio.pcm_status(1)
            for channel, status in ((0, self.status0), (1, self.status1)):
                if status & ERROR_MASK:
                    self.pcm_fault[channel] = 1
            if self.music and not self.status0 & R.AUDIO_PCM_STATUS_ACTIVE:
                self.bgm_inactive += 1

    def stop(self, force=False):
        if not (self.psg or self.pcm or force):
            return
        first_error = None
        for channel in range(6):
            try:
                self.audio.stop(channel)
            except BaseException as error:
                if first_error is None:
                    first_error = error
            self.on[channel] = 0
        if self.device.caps & R.CAPS_PSRAM:
            for channel in (0, 1):
                base = R.AUDIO_PCM_BASE + channel * R.AUDIO_PCM_STRIDE
                try:
                    self.device.audio_write(base + R.AUDIO_PCM_CONTROL, 0)
                    self.pcm_command(channel, R.AUDIO_PCM_CMD_STOP)
                except BaseException as error:
                    if first_error is None:
                        first_error = error
        try:
            self.device.audio_commit()
        except BaseException as error:
            if first_error is None:
                first_error = error
        if first_error is not None:
            raise first_error
