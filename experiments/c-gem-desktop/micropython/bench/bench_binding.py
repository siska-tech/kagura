# SPDX-License-Identifier: Apache-2.0
"""MicroPython side of the stage 3A comparison (see bench_native.c).

The same scene and workloads as kdm_bench, driven from Python through the
kagura_desktop binding. Per workload: p50/p90/max time per iteration (op +
present into a TILE4 mirror), tiles exported, heap bytes allocated per
iteration (separate pass with GC disabled), and the framebuffer and mirror
CRCs, which must equal kdm_bench's.

Also: per-call overhead of the binding, heap and native RAM, and GC.

  micropython bench/bench_binding.py [--quick]
"""
import binascii
import gc
import sys
import time

import kagura_desktop as kd
import workloads as wl
from workloads import Scene, TABLE, setup

ticks_us, ticks_diff = time.ticks_us, time.ticks_diff


def run_workload(fn_name, n, n_rects):
    """Pass 1 (GC off): mean over the whole loop and heap bytes per iteration.
    Pass 2 (GC on): per-iteration distribution, tiles and CRCs."""
    tick_start = wl.tick
    sc, op = setup(fn_name, n_rects, n)
    d, vram = sc.d, sc.vram
    for i in range(-4, 0):
        op(i)
        d.present(vram)
    gc.collect()
    gc.disable()
    a0 = gc.mem_alloc()
    t0 = ticks_us()
    for i in range(n):
        op(i)
        d.present(vram)
    mean = ticks_diff(ticks_us(), t0) / n
    alloc = (gc.mem_alloc() - a0) / n
    gc.enable()

    wl.tick = tick_start   # the second pass sees the same event times
    sc, op = setup(fn_name, n_rects, n)
    d, vram = sc.d, sc.vram
    times = [0] * n
    tiles = 0
    gc.collect()
    for i in range(-4, n):
        t0 = ticks_us()
        op(i)
        k = d.present(vram)
        t1 = ticks_us()
        if i >= 0:
            times[i] = ticks_diff(t1, t0)
            tiles += k
    times.sort()
    return (mean, times[n // 2], times[(n - 1) * 9 // 10], times[-1], tiles / n, alloc, d.crc(),
            binascii.crc32(vram))


def call_overhead(n):
    d = kd.Desktop()
    w = d.create_window('W', 10, 20, 100, 80)
    f = w.fill_rect(0, 0, 10, 10, 4)

    def py(a, b):
        return a

    def loop(body):
        t0 = ticks_us()
        for _ in range(n):
            body()
        return ticks_diff(ticks_us(), t0) * 1000 // n   # ns per iteration

    rows = []
    t0 = ticks_us()
    for _ in range(n):
        pass
    base = ticks_diff(ticks_us(), t0) * 1000 // n
    rows.append(('empty loop iteration', base))
    rows.append(('Python function call, 2 args', loop(lambda: py(1, 2)) - loop(lambda: None)))
    rows.append(('w.is_open() (handle check only)', loop(w.is_open) - base))
    rows.append(('w.set_color(id, same colour) (5 checks, no change)', loop(lambda: w.set_color(f, 4)) - loop(lambda: None)))
    rows.append(('w.fill_rect(...) + w.remove(id)', loop(lambda: w.remove(w.fill_rect(1, 1, 2, 2, 3))) - loop(lambda: None)))
    rows.append(('d.present() with no damage', loop(d.present) - base))
    lst = [None] * 8
    rows.append(('d.poll_into(lst), queue empty', loop(lambda: d.poll_into(lst)) - loop(lambda: None)))
    d.close()
    return rows


def memory():
    gc.collect()
    h0 = gc.mem_alloc()
    sc = Scene()
    gc.collect()
    h1 = gc.mem_alloc()
    sizes = kd.sizes()

    def collect_us():
        gc.collect()
        t = []
        for _ in range(21):
            t0 = ticks_us()
            gc.collect()
            t.append(ticks_diff(ticks_us(), t0))
        t.sort()
        return t[10]

    c_scene = collect_us()
    heap_fb = bytearray(38400)   # a KAGURA-UI-sized framebuffer in the heap, for comparison
    heap_fb[0] = 1
    c_heap_fb = collect_us()
    del heap_fb
    out = (h1 - h0, sizes, c_scene, c_heap_fb, gc.mem_free() + gc.mem_alloc())
    sc.d.close()
    return out


def main():
    quick = '--quick' in sys.argv
    print('# bench_binding: MicroPython %s, kagura_desktop (op + present into a TILE4 mirror), per iteration'
          % '.'.join(str(v) for v in sys.implementation.version[:3]))
    print('| workload | mean us | p50 us | p90 us | max us | tiles | heap B/iter | fb crc | vram crc |')
    print('|---|---:|---:|---:|---:|---:|---:|---:|---:|')
    for name, fn, n, n_rects in TABLE:
        if quick:
            n = 8
        mean, p50, p90, mx, tiles, alloc, crc, vcrc = run_workload(fn, n, n_rects)
        print('| %s | %.2f | %d | %d | %d | %.1f | %.0f | %08x | %08x |' % (name, mean, p50, p90, mx, tiles, alloc, crc,
                                                                       vcrc))
    print()
    print('| call (100,000 iterations, loop overhead subtracted) | ns |')
    print('|---|---:|')
    for what, ns in call_overhead(10000 if quick else 100000):
        print('| %s | %d |' % (what, ns))
    print()
    heap, sizes, c_scene, c_heap_fb, total = memory()
    print('heap: scene objects (Desktop, 2 Windows, Sprite, mirror bytearray 32,000 B) %d B of %d B' % (heap, total))
    print('native static: %s' % ', '.join('%s %d' % kv for kv in sorted(sizes.items())))
    print('gc.collect(): %d us with the scene; %d us with an extra 38,400 B bytearray alive' % (c_scene, c_heap_fb))


main()
