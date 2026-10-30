# SPDX-License-Identifier: Apache-2.0
"""Paired opt-in dirty-gap / existing DMA-option experiment, not default tuning.

Run with an exclusive initialized framebuffer_diagnostic.Session. Requires
framebuffer_transport_benchmark.py on the import path. No timed logging.
"""
import gc
import time
from array import array
from framebuffer_diagnostic import report
from framebuffer_transport_benchmark import detail, indices, scenes


def run(session, repetitions=30):
    if not 10 <= repetitions <= 100:
        raise ValueError('repetitions 10..100')
    f = session.fb
    original = f.flush
    overridden = False
    session.pcm_start()
    try:
        for chunk, gap in ((128, 0), (128, 1), (512, 1)):
            session.accel.close()
            session.accel = session.raw.accelerate(chunk=chunk)
            assert session.accel.enabled
            # Same renderer, buffers, stimulus, FW and observer for all options.
            f.flush = lambda: original(max_gap=gap)
            overridden = True
            report('gap_config', chunk=chunk, max_gap=gap,
                   clock_hz=__import__('machine').freq(), baudrate=session.raw.baudrate)
            cases = (('clean', ()), ('one', (0,)), ('bank_gap', (1022, 1024)),
                     ('dispersed100', indices(100, 'dispersed')),
                     ('compact256', indices(256, 'compact_rect')),
                     ('full1200', range(1200)))
            for name, selected in cases:
                f.fill(0)
                f.flush()
                elapsed = array('I')
                for n in range(repetitions + 3):
                    for tile in selected:
                        f.pixel(tile % 40 * 8, tile // 40 * 8, 1 + n % 15)
                    gc.collect()
                    session.counter.reset()
                    start = time.ticks_us()
                    stats = f.flush()
                    duration = time.ticks_diff(time.ticks_us(), start)
                    if n >= 3:
                        elapsed.append(duration)
                report('gap_micro', case=name, chunk=chunk, max_gap=gap,
                       warmup=3, timing=detail(elapsed), last_flush=stats,
                       transactions=session.counter.writes+session.counter.reads,
                       telemetry=session.telemetry())
            scenes(session, repetitions)
            report('gap_config_complete', chunk=chunk, max_gap=gap,
                   telemetry=session.telemetry())
        # Final full-plane/map/upper check with PCM still running.
        session.verify(full=True)
        report('gap_complete', telemetry=session.telemetry())
    finally:
        # Remove instance override rather than retain a captured bound method.
        if overridden:
            del f.flush
