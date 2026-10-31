# SPDX-License-Identifier: Apache-2.0
"""Public SDK operations, GC enabled. No firmware changes or GC suppression.

Pass an otherwise idle connected device. OAM is overwritten and committed;
run before an application initializes its scene. net_heap is not gross
allocation: VM frames explicitly freed before sampling are invisible.
"""
import gc
from array import array
from time import ticks_us, ticks_diff
from kagura import regs as R


def run(d, iterations=100):
    if hasattr(gc, 'isenabled') and not gc.isenabled():
        raise RuntimeError('benchmark requires GC enabled')
    if not 1 <= iterations <= 10000:
        raise ValueError('iterations (1..10000)')
    oam = bytearray(R.VRAM_OAM_SIZE)
    ext = bytes((R.EXT_SCROLL_X_L, 0, R.EXT_SCROLL_X_H, 0, R.EXT_SCROLL_Y, 0))
    def ext_pairs():
        if hasattr(d, 'ext_writes'):
            d.ext_writes(ext)
        else:
            for i in range(0, len(ext), 2):
                d.ext_write(ext[i], ext[i + 1])
    cases = (
        ('read_reg', lambda: d.read_reg(R.REG_STATUS)),
        ('write_reg', lambda: d.write_reg(R.REG_FENCE_TAG, 0)),
        ('audio_read', lambda: d.audio_read(R.AUDIO_STATUS)),
        ('ext_writes_3', ext_pairs),
        ('oam_2048', lambda: d.write_memory(R.VRAM_OAM_BASE, oam)),
        ('commit_wait', lambda: d.commit()),
    )
    rows = []
    for name, call in cases:
        samples = array('I', (0 for _ in range(iterations)))
        call()  # warm persistent caches, outside measurement
        gc.collect()
        before = gc.mem_alloc()
        for i in range(iterations):
            start = ticks_us()
            call()
            samples[i] = ticks_diff(ticks_us(), start)
        net = gc.mem_alloc() - before
        ordered = sorted(samples)
        row = (name, sum(samples) / iterations, ordered[iterations // 2],
               max(samples), net)
        rows.append(row)
        print('SDKBENCH %s mean=%.1f median=%d max=%d us net_heap=%d B n=%d' % (row + (iterations,)))
    d.check_errors()
    print('SDKBENCH PASS (GC enabled; net_heap is not gross allocation)')
    return rows
