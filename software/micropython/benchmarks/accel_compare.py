# SPDX-License-Identifier: Apache-2.0
"""Real RP2040 native-kernel equivalence and renderer/transport A/B tests."""
import gc
from time import ticks_us, ticks_diff, sleep_ms
import shooter
from shooter_oam_viper import build as native_build
import kagura_dma_pack as packing


def equivalence():
    class Device:
        caps = 0
        height = 180
    totals = [[0, 0, 0] for _ in range(4)]
    loads = ('NORMAL', 'HEAVY', 'STRESS', 'EXTREME')
    for height in (180, 240):
        d = Device()
        d.height = height
        g = shooter.Game(d, mode='BASE')
        g.glyphs = {ch: 32 + i for i, ch in enumerate(sorted(shooter.FONT))}
        for frame in range(128):
            g.enhanced = frame % 7 != 0
            group = (frame // 16) % 4
            g.load = loads[group]
            g.extreme_sprites = 128 if frame < 64 else 256
            g.particle_limit = 8 << ((frame // 32) % 4)
            g.step()
            g.power = 3 if frame & 4 else 0
            if frame % 9 == 0:
                g.emit(56, height // 2, True)
                g.hostile.spawn(-7, 24)
            if frame % 13 == 0:
                g.bullets.spawn(-8, -1)
                g.enemies.spawn(319, height - 1)
            # Warm changed HUD once, equally for both timed builders.
            g.update_hud()
            before = bytes(g.oam)
            previous, culled = g.oam_count, g.stats.particle_culled
            g._oam_builder = None
            stamp = ticks_us()
            g.build_oam()
            python_us = ticks_diff(ticks_us(), stamp)
            expected = bytes(g.oam)
            expected_bands = bytes(g.scanlines)
            expected_info = (g.oam_count, g.oam_bytes, g.active_sprites, g.stats.particle_culled)
            g.oam[:] = before
            g.oam_count, g.stats.particle_culled = previous, culled
            g._oam_builder = native_build
            stamp = ticks_us()
            g.build_oam()
            native_us = ticks_diff(ticks_us(), stamp)
            if g.oam != expected or g.scanlines != expected_bands or expected_info != (g.oam_count, g.oam_bytes, g.active_sprites, g.stats.particle_culled):
                raise AssertionError('OAM mismatch height=%d frame=%d load=%s' % (height, frame, g.load))
            totals[group][0] += python_us
            totals[group][1] += native_us
            totals[group][2] += 1
            gc.collect()
    # Every possible byte, both lane tables, boundary lengths and nonzero start.
    from array import array
    source = bytes(range(256)) * 9
    cases = 0
    for shift in (6, 7):
        for queued in (0, 0x8000):
            high = array('H', [queued | value << shift for value in range(256)])
            for start in (0, 1, 127, 255):
                for count in (1, 15, 16, 127, 128):
                    a = array('H', [0x55AA] * 256)
                    b = array('H', a)
                    packing.python_pack(source, high, a, start, count)
                    packing.viper_pack(source, high, b, start, count)
                    if a != b:
                        raise AssertionError('DMA encoding mismatch')
                    cases += 1
    print('EQUIVALENCE_PASS', 256, 'OAM states', cases, 'DMA cases')
    for i in range(4):
        print('OAM_COMPARE', loads[i], 'python_us', totals[i][0]/totals[i][2], 'viper_us', totals[i][1]/totals[i][2])
        sleep_ms(10)


def benchmark(console, frames=400, renderer='python', dma='python', mode='HEAVY'):
    print('ACCEL_BEGIN', renderer, dma, mode)
    result = shooter.run(console=console, mode=mode, frames=frames,
                         renderer=renderer, dma=dma, target_fps=0, input_fn=lambda: 0)
    print('ACCEL_END', renderer, dma, mode)
    return result
