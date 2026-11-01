# SPDX-License-Identifier: Apache-2.0
"""Measured values only; unsupported heap/GC counters show n/a."""
import gc
from kagura.ui import VBox, Label, Button
from kagura.ui.events import now_us, elapsed


def build(app):
    root = VBox(padding=8, spacing=8)
    root.add(Label('KAGURA-UI System Monitor'))
    device = getattr(app.backend, 'device', None)
    root.add(Label('ABI %s / CAPS %s' % (getattr(device, 'abi', 'n/a'),
                                       hex(device.caps) if device is not None else 'n/a')))
    timing = root.add(Label('', width=304))
    heap = root.add(Label('', width=304))
    transfer = root.add(Label('', width=304))
    root.add(Label('GC count: n/a (VM has no counter)'))
    root.add(Button('EXIT', on_click=app.stop))
    app.set_root(root)
    sample = [now_us(), app.frames]
    def update():
        now = now_us()
        duration = elapsed(now, sample[0])
        if duration < 1000000:
            return
        timing.set_text('updates/s %d / last %dus' %
                        ((app.frames - sample[1]) * 1000000 // duration, app.last_frame_us))
        heap.set_text('heap used: %s' % (gc.mem_alloc() if hasattr(gc, 'mem_alloc') else 'n/a'))
        stats = app.last_flush or {}
        transfer.set_text('tiles %s / payload B %s' % (stats.get('tiles','n/a'),stats.get('bytes','n/a')))
        sample[0], sample[1] = now, app.frames
    return update


def run(**kwargs):
    from ui_demo_common import launch
    launch(build, **kwargs)
