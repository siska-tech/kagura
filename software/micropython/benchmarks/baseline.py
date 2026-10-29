# SPDX-License-Identifier: Apache-2.0
"""Run untouched v1 on hardware. Copy shooter_v1.py and this file to Pico.

The old interleaved movement/collision step cannot be timed separately without
editing it. That field is deliberately reported as combined, never inferred.
"""
import gc
from time import ticks_us, ticks_diff, sleep_ms
from array import array
import shooter_v1


class TimedDevice:
    def __init__(self, device):
        self.raw = device
        self.height, self.caps, self.busy = device.height, device.caps, 0
        self.transfer_us = self.commit_us = self.audio_us = self.bytes = 0

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def write_memory(self, address, data):
        start = ticks_us()
        self.raw.write_memory(address, data)
        self.transfer_us += ticks_diff(ticks_us(), start)
        self.bytes += len(data)

    def commit(self):
        start = ticks_us()
        self.raw.commit()
        self.commit_us += ticks_diff(ticks_us(), start)

    def audio_write(self, index, value):
        start = ticks_us()
        self.raw.audio_write(index, value)
        self.audio_us += ticks_diff(ticks_us(), start)

    def audio_commit(self):
        start = ticks_us()
        self.raw.audio_commit()
        self.audio_us += ticks_diff(ticks_us(), start)


def run(console, frames=300, sound=False):
    device = console.screen.device
    proxy = TimedDevice(device)
    game = shooter_v1.Game(proxy, sound=sound)
    times = array('I', [0] * frames)
    step_us = draw_us = gc_us = 0
    was_enabled = gc.isenabled()
    console.pause()
    try:
        game.initialize()
        proxy.transfer_us = proxy.commit_us = proxy.audio_us = proxy.bytes = 0
        first = device.read_reg(shooter_v1.R.REG_FRAME_COUNT_L)
        display_frames = 0
        gc.collect()
        gc.disable()
        start = ticks_us()
        for i in range(frames):
            begin = ticks_us()
            stamp = ticks_us()
            game.step()
            step_us += ticks_diff(ticks_us(), stamp)
            stamp = ticks_us()
            game.draw()
            draw_us += ticks_diff(ticks_us(), stamp)
            now = device.read_reg(shooter_v1.R.REG_FRAME_COUNT_L)
            display_frames += (now - first) & 255
            first = now
            if True:  # Same explicit collection policy as v2 benchmark runs.
                stamp = ticks_us()
                gc.collect()
                gc_us += ticks_diff(ticks_us(), stamp)
            times[i] = ticks_diff(ticks_us(), begin)
        elapsed = ticks_diff(ticks_us(), start)
    finally:
        try:
            if game.sound:
                for ch in range(4):
                    game.audio.stop(ch)
                device.audio_commit()
        finally:
            if was_enabled:
                gc.enable()
            console.resume()
    ordered = sorted(times)
    result = dict(kind='hardware-v1', frames=frames, sound=sound,
                  height=device.height, lanes=device.transport.lanes,
                  baudrate=device.transport.baudrate,
                  logic_fps=frames * 1000000 / elapsed,
                  frame_mean_us=sum(times) / frames,
                  frame_p95_us=ordered[(frames * 95 + 99) // 100 - 1],
                  frame_max_us=max(times), movement_collision_us=step_us / frames,
                  draw_combined_us=draw_us / frames,
                  transfer_us=proxy.transfer_us / frames,
                  commit_us=proxy.commit_us / frames,
                  audio_us=proxy.audio_us / frames, gc_us=gc_us / frames,
                  oam_bytes=proxy.bytes, commit_successes=frames,
                  hardware_frame_delta=display_frames)
    for key in sorted(result):
        print('BASELINE', key, result[key])
        sleep_ms(10)  # USB output only after the timed interval.
    return result
