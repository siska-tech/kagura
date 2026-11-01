# SPDX-License-Identifier: Apache-2.0
"""Bounded samples, no performance promises. run(app, samples=128).

Reports SDK pattern payload bytes (not SPI framing), synthetic event latency,
GC-visible heap and percentile timings. Does not infer VM allocation/GC counts.
Call after building a Gallery, or use make(console=...) for a dedicated workload.
"""
import gc
from array import array
from kagura.ui import App, Screen, Label, Button, Panel, ListView, Event, Theme, BitmapFont8
from kagura.ui.events import now_us, elapsed


def _percentiles(values):
    ordered = sorted(values)
    return [ordered[(len(ordered)-1)*p//100] for p in (50,95,99)]


def make(device, font, console=None, exclusive=False):
    app = App(device,console=console,exclusive=exclusive,theme=Theme(BitmapFont8(font)))
    app.input = None  # deterministic synthetic input; physical input tested separately
    root = Screen(color=0)
    label = root.add(Label('0',x=8,y=8,width=64,height=8))
    panel = root.add(Panel(x=100,y=40,width=32,height=32,color=4))
    listing = root.add(ListView(['A','B','C','D','E','F'],x=200,y=40,width=64,height=24))
    other = Screen(color=2)
    clicked = [0]
    def click():
        clicked[0] += 1
        label.set_text(str(clicked[0]))
    button = root.add(Button('GO',x=8,y=40,on_click=click))
    app.set_root(root)
    return app, (root,label,panel,listing,other,button)


def run(app, widgets, samples=128, cycles=1):
    if not 2 <= samples <= 512 or cycles < 1:
        raise ValueError('samples 2..512, cycles >=1')
    import json
    root,label,panel,listing,other,button = widgets
    times = array('I',[0]*samples)
    flushes = array('I',[0]*samples)
    latencies = array('I',[0]*samples)
    gc.collect()
    heap_start = gc.mem_free() if hasattr(gc,'mem_free') else None
    app.step()
    for cycle in range(cycles):
        for workload in ('idle','label','button','focus','move','scroll','screen'):
            total_tiles = total_bytes = 0
            latency_n = 0
            if app.root is not root:
                app.set_root(root); app.step()
            for n in range(samples):
                begin = now_us()
                if workload == 'label': label.set_text(str(n))
                elif workload == 'button':
                    app.focus.set(button); app.events.post(Event('enter'))
                elif workload == 'focus': app.events.post(Event('tab'))
                elif workload == 'move': panel.set_bounds(100+(n%2)*4,40)
                elif workload == 'scroll':
                    app.focus.set(listing)
                    app.events.post(Event('down' if n%10<5 else 'up'))
                elif workload == 'screen': app.set_root(root if n%2 else other)
                changed = app.step()
                times[n] = elapsed(now_us(),begin)
                stats = app.last_flush if changed else None
                flushes[n] = stats.get('total_us',0) if stats else 0
                if workload in ('button','focus','scroll') and app.last_invalidate_us is not None:
                    latencies[latency_n] = app.last_invalidate_us
                    latency_n += 1
                total_tiles += stats.get('tiles',0) if stats else 0
                total_bytes += stats.get('bytes',0) if stats else 0
            result = dict(cycle=cycle,workload=workload,samples=samples,
                          frame_us_p50_p95_p99=_percentiles(times),
                          flush_us_p50_p95_p99=_percentiles(flushes),
                          synthetic_invalidate_us_p50_p95_p99=_percentiles(latencies[:latency_n]) if latency_n else None,
                          latency_samples=latency_n,
                          tiles=total_tiles,pattern_payload_bytes=total_bytes)
            print('UI_BENCH '+json.dumps(result))
            del result
        gc.collect()
        print('UI_HEAP '+json.dumps(dict(cycle=cycle,free=gc.mem_free() if hasattr(gc,'mem_free') else None,
                                        gc_count=None,allocation_count=None)))
    gc.collect()
    print('UI_FINISH '+json.dumps(dict(heap_start=heap_start,
                                      heap_end=gc.mem_free() if hasattr(gc,'mem_free') else None)))


def baseline(app, samples=128):
    """Same label area/font/flush, drawing directly without widget traversal."""
    import json
    times = array('I',[0]*samples)
    flushes = array('I',[0]*samples)
    app.start()
    renderer = app.renderer
    renderer.clip = (0,0,renderer.width,renderer.height)
    total_tiles = total_bytes = 0
    for n in range(samples):
        start = now_us()
        renderer.fill_rect(8,8,64,8,0)
        app.theme.font.draw(renderer,str(n),8,8,1)
        stats = app.backend.flush()
        times[n] = elapsed(now_us(),start)
        flushes[n] = stats.get('total_us',0)
        total_tiles += stats.get('tiles',0)
        total_bytes += stats.get('bytes',0)
    print('UI_BASELINE '+json.dumps(dict(samples=samples,frame_us_p50_p95_p99=_percentiles(times),
                                       flush_us_p50_p95_p99=_percentiles(flushes),
                                       tiles=total_tiles,pattern_payload_bytes=total_bytes)))
    app.damage((0,0,renderer.width,renderer.height))
