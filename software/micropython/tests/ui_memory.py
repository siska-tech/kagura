# SPDX-License-Identifier: Apache-2.0
"""MicroPython unix heap observation, NOT an RP2040 acceptance test.

64x48 mock surface; fixed widgets. Two 1024-update windows, GC enabled.
Net live heap is distinct from allocations and from the unknown GC count.
"""
import gc
import sys
if sys.implementation.name != 'micropython':
    sys.dont_write_bytecode = True
    import test_driver
from kagura.ui import App, Label, Theme, BitmapFont8
from kagura.ui.mock import MockBackend
from kagura_ja import Font

font = Font(sys.argv[1])
gc.collect()
before = gc.mem_alloc()
app = App(backend=MockBackend(64,48),theme=Theme(BitmapFont8(font)))
label = Label('000',width=32,height=8)
app.set_root(label)
for window in range(3):
    for n in range(1024):
        label.set_text('%03d' % (n%1000))
        app.step()
    gc.collect()
    print('UI_MEMORY',window,'alloc',gc.mem_alloc(),'free',gc.mem_free(),
          'delta_from_constructor_start',gc.mem_alloc()-before)
app.close()
font.close()
