# SPDX-License-Identifier: Apache-2.0
"""Bounded RAM telemetry. No output or sample-list growth during play."""
from array import array
from time import ticks_us, ticks_diff

CATEGORIES = ('input', 'movement', 'collision', 'oam_build', 'oam_transfer',
              'scroll', 'commit', 'audio', 'monitor', 'gc', 'sleep')
INPUT, MOVE, COLLIDE, BUILD, TRANSFER, SCROLL, COMMIT, AUDIO, MONITOR, GC, SLEEP = range(11)


class Stats:
    def __init__(self, samples=1024):
        if not 16 <= samples <= 8192:
            raise ValueError('samples must be 16..8192')
        self.samples = array('I', [0] * samples)
        self.totals = [0] * len(CATEGORIES)
        self.maxima = [0] * len(CATEGORIES)
        self.current = [0] * len(CATEGORIES)
        self.frames = self.commits = self.elapsed_us = self.frame_sum = self.frame_max = 0
        self.counter_delta = 0
        self.counter_valid = True
        self.last_counter = None
        self.counter_time = 0
        self.error_count = self.error_stored = 0
        # frame, enabled sprites, OAM bytes, wire bytes, error code, audio,
        # PCM0, PCM1, overflow index, overflow line (last 32 incidents).
        self.errors = array('I', [0] * 320)
        self.audio_errors = self.sprite_overflows = 0
        self.dropped_events = self.particle_culled = 0

    def add(self, category, duration):
        self.totals[category] += duration
        self.current[category] += duration
        if self.current[category] > self.maxima[category]:
            self.maxima[category] = self.current[category]

    def finish(self, duration):
        self.samples[self.frames % len(self.samples)] = duration
        self.frames += 1
        self.frame_sum += duration
        self.frame_max = max(self.frame_max, duration)
        for i in range(len(CATEGORIES)):
            self.current[i] = 0

    def counter(self, value, now):
        if self.last_counter is not None:
            # 8bit counter at 60Hz wraps in ~4.27 seconds. Do not invent wraps.
            if ticks_diff(now, self.counter_time) >= 4000000:
                self.counter_valid = False
            self.counter_delta += (value - self.last_counter) & 255
        self.last_counter, self.counter_time = value, now

    def error(self, sprites, oam_bytes, wire_bytes, code, audio, pcm0, pcm1,
              overflow_index=0, overflow_line=0):
        offset = (self.error_count % 32) * 10
        values = (self.frames, sprites, oam_bytes, wire_bytes, code, audio,
                  pcm0, pcm1, overflow_index, overflow_line)
        for i in range(10):
            self.errors[offset + i] = values[i]
        self.error_count += 1
        self.error_stored = min(32, self.error_count)

    def summary(self):
        count = min(self.frames, len(self.samples))
        ordered = sorted(self.samples[:count])
        means = {}
        maxima = {}
        for i in range(len(CATEGORIES)):
            means[CATEGORIES[i]] = self.totals[i] / max(1, self.frames)
            maxima[CATEGORIES[i]] = self.maxima[i]
        incidents = []
        for i in range(self.error_stored):
            offset = ((self.error_count - self.error_stored + i) % 32) * 10
            incidents.append(list(self.errors[offset:offset + 10]))
        return dict(frames=self.frames,
                    logic_fps=self.frames * 1000000 / max(1, self.elapsed_us),
                    commit_successes=self.commits,
                    hardware_frame_delta=self.counter_delta if self.counter_valid else None,
                    frame_mean_us=self.frame_sum / max(1, self.frames),
                    frame_p95_us=ordered[(count * 95 + 99) // 100 - 1] if count else None,
                    p95_window_frames=count, frame_max_us=self.frame_max,
                    mean_us=means, max_us=maxima, audio_errors=self.audio_errors,
                    sprite_overflows=self.sprite_overflows, error_count=self.error_count,
                    errors=incidents, dropped_audio_events=self.dropped_events,
                    particle_culled=self.particle_culled)


class TransportMeter:
    """Application-scoped wrapper around the existing DMA-capable transport.

    Wire-byte/time totals include all register headers/status reads, not just
    OAM payload. These totals overlap the outer stage timings.
    """
    def __init__(self, transport):
        self.raw = transport
        self.wire_bytes = self.io_us = self.dma_payload = 0

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def write(self, offset, data, inc=False):
        stamp = ticks_us()
        try:
            return self.raw.write(offset, data, inc)
        finally:
            self.io_us += ticks_diff(ticks_us(), stamp)
            self.wire_bytes += len(data) + 1
            if not inc and len(data) >= 16 and getattr(self.raw, '_dma_tx', None) is not None:
                self.dma_payload += len(data)

    def readinto(self, offset, buffer, inc=False):
        stamp = ticks_us()
        try:
            return self.raw.readinto(offset, buffer, inc)
        finally:
            self.io_us += ticks_diff(ticks_us(), stamp)
            self.wire_bytes += len(buffer) + 3
