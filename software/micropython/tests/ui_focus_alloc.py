# SPDX-License-Identifier: Apache-2.0
"""unix MicroPython v1.26 only: GC-visible heap bytes per focus operation.

gc is disabled around repeated calls and gc.mem_alloc() is compared. This is
the unix port (64-bit object sizes), not RP2040; it guards against regressions
such as per-node generators or clip tuples in the focus scan.
"""
import gc
from kagura.ui import App, Screen, VBox, HBox, Button, Label, Event
from kagura.ui.mock import MockBackend


def build(n):
    app = App(backend=MockBackend(320, 240))
    root = Screen()
    column = root.add(VBox(spacing=1))
    for i in range(n):
        row = column.add(HBox())
        row.add(Label('L'))
        row.add(Button('B%d' % i))
    app.set_root(root)
    app.step()
    return app


def per_call(fn, reps=16):
    fn()
    gc.collect()
    gc.disable()
    try:
        start = gc.mem_alloc()
        for _ in range(reps):
            fn()
        return (gc.mem_alloc() - start) // reps
    finally:
        gc.enable()


tab = Event('tab')
for n in (4, 16):
    app = build(n)
    scan = per_call(app.focus.candidates)
    repair = per_call(lambda: app.focus.repair(force=True))
    dispatch = per_call(lambda: app.focus.dispatch(tab))
    print('focus n=%d scan=%d repair=%d dispatch_tab=%d' % (n, scan, repair, dispatch))
    assert scan == 0 and repair == 0, 'focus scan allocates'
    # Remaining dispatch bytes are damage rectangles for the two focus changes.
    assert dispatch <= 1024, 'focus dispatch allocation regressed'
    app.close()
print('UI_FOCUS_ALLOC_PASS')
