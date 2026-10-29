# SPDX-License-Identifier: Apache-2.0
"""Bounded RAM telemetry. No output or sample-list growth during play."""
from array import array
from time import ticks_us, ticks_diff

CATEGORIES = ('input', 'movement', 'collision', 'oam_build', 'oam_transfer',
              'scroll', 'commit', 'audio', 'monitor', 'gc', 'sleep',
              'commit_wait', 'commit_issue', 'logic', 'memory_poll')
INPUT, MOVE, COLLIDE, BUILD, TRANSFER, SCROLL, COMMIT, AUDIO, MONITOR, GC, SLEEP = range(11)
COMMIT_WAIT, COMMIT_ISSUE, LOGIC = 11, 12, 13
MEMORY_POLL = 14


class Stats:
    def __init__(self, samples=1024, detail=False):
        if not 16 <= samples <= 8192:
            raise ValueError('samples must be 16..8192')
        self.samples = array('I', [0] * samples)
        self.periods = array('I', [0] * samples)
        self.period_count = self.period_sum = self.period_max = 0
        self.last_begin = None
        self.totals = [0] * len(CATEGORIES)
        self.maxima = [0] * len(CATEGORIES)
        self.current = [0] * len(CATEGORIES)
        self.detail_window = min(samples, 128) if detail else 0
        # Separate 512-byte columns avoid a large contiguous allocation on a
        # long-lived REPL heap, even when total free RAM is ample.
        self.detail = [array('I', [0] * self.detail_window) for _ in CATEGORIES] if detail else []
        self.commit_completed = self.oam_writes = self.oam_bytes = 0
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

    def period_end(self, stamp):
        if self.last_begin is not None:
            period = ticks_diff(stamp, self.last_begin)
            self.periods[self.period_count % len(self.periods)] = period
            self.period_count += 1
            self.period_sum += period
            self.period_max = max(self.period_max, period)
        self.last_begin = stamp

    def finish(self, duration, begin=None):
        if begin is not None:
            # Consecutive frame starts include the preceding frame's telemetry
            # bookkeeping and loop condition, which duration alone excludes.
            self.period_end(begin)
        self.add(LOGIC, self.current[MOVE] + self.current[COLLIDE])
        if self.detail_window:
            offset = self.frames % self.detail_window
            for i in range(len(CATEGORIES)):
                self.detail[i][offset] = self.current[i]
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
        periods = sorted(self.periods[:min(self.period_count,len(self.periods))])
        pn = len(periods)
        means = {}
        maxima = {}
        medians = {}
        p95s = {}
        for i in range(len(CATEGORIES)):
            means[CATEGORIES[i]] = self.totals[i] / max(1, self.frames)
            maxima[CATEGORIES[i]] = self.maxima[i]
            if self.detail_window:
                n = min(self.frames, self.detail_window)
                values = sorted(self.detail[i][:n])
                medians[CATEGORIES[i]] = (values[(n - 1) // 2] + values[n // 2]) / 2 if n else None
                p95s[CATEGORIES[i]] = values[(n * 95 + 99) // 100 - 1] if n else None
        incidents = []
        for i in range(self.error_stored):
            offset = ((self.error_count - self.error_stored + i) % 32) * 10
            incidents.append(list(self.errors[offset:offset + 10]))
        exclusive = (INPUT, MOVE, COLLIDE, BUILD, TRANSFER, SCROLL, COMMIT_WAIT,
                     COMMIT_ISSUE, AUDIO, MONITOR, GC, SLEEP, MEMORY_POLL)
        accounted = sum(self.totals[i] for i in exclusive)
        return dict(frames=self.frames,
                    logic_fps=self.frames * 1000000 / max(1, self.elapsed_us),
                    commit_successes=self.commits,
                    commit_completions_observed=self.commit_completed,
                    commit_issue_hz=self.commits * 1000000 / max(1, self.elapsed_us),
                    commit_complete_hz=self.commit_completed * 1000000 / max(1, self.elapsed_us),
                    actual_pixel_update_hz=None,
                    loop_wall_mean_us=self.elapsed_us / max(1,self.frames),
                    loop_frame_mean_us=self.period_sum / self.period_count if self.period_count else None,
                    loop_frame_median_us=(periods[(pn-1)//2]+periods[pn//2])/2 if pn else None,
                    loop_frame_p95_us=periods[(pn*95+99)//100-1] if pn else None,
                    loop_frame_max_us=self.period_max if pn else None,
                    loop_p95_window_frames=pn,
                    oam_write_calls=self.oam_writes, oam_payload_bytes=self.oam_bytes,
                    oam_payload_bytes_per_second=self.oam_bytes * 1000000 / max(1, self.elapsed_us),
                    hardware_frame_delta=self.counter_delta if self.counter_valid else None,
                    frame_mean_us=self.frame_sum / max(1, self.frames),
                    exclusive_stage_sum_us=accounted / max(1, self.frames),
                    unclassified_mean_us=(self.frame_sum - accounted) / max(1, self.frames),
                    frame_p95_us=ordered[(count * 95 + 99) // 100 - 1] if count else None,
                    frame_median_us=(ordered[(count - 1) // 2] + ordered[count // 2]) / 2 if count else None,
                    p95_window_frames=count, frame_max_us=self.frame_max,
                    mean_us=means, max_us=maxima, median_us=medians, p95_us=p95s,
                    detail_window_frames=min(self.frames, self.detail_window), audio_errors=self.audio_errors,
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
