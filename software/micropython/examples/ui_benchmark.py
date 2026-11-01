# SPDX-License-Identifier: Apache-2.0
"""Bounded samples, no performance promises. run(app, samples=128).

Reports SDK pattern payload bytes (not SPI framing), synthetic event latency,
GC-visible heap and percentile timings. Does not infer VM allocation/GC counts.
Call after building a Gallery, or use make(console=...) for a dedicated workload.
"""
import gc
import time
import json
from array import array
from kagura.ui import App, Screen, Label, Button, Panel, ListView, Event, Theme, BitmapFont8
from kagura.ui.events import now_us, elapsed

_WORKLOADS = ('idle','label','button','focus','move','scroll','screen')


def _percentiles(values):
    ordered = sorted(values)
    return [ordered[(len(ordered)-1)*p//100] for p in (50,95,99)]


def _now_ms():
    return time.ticks_ms() if hasattr(time,'ticks_ms') else time.monotonic_ns()//1000000


def _stdout_report(tag, value):
    print(tag+' '+json.dumps(value))


class Summary:
    """Bounded device-side telemetry for a run without a USB log reader."""
    def __init__(self):
        self.workloads = {}
        self.heap = dict(groups=0,first_free=None,last_free=None,min_free=None,
                         max_free=None,last_cycle=None,elapsed_ms=0)
        self.finish = None

    def report(self, tag, value):
        if tag == 'UI_BENCH':
            name = value['workload']
            if name not in _WORKLOADS:
                raise ValueError('unknown benchmark workload')
            if name not in self.workloads:
                self.workloads[name] = dict(groups=0,samples=0,latency_samples=0,
                    tiles=0,pattern_payload_bytes=0,frame_us_percentile_ranges=None,
                    flush_us_percentile_ranges=None,synthetic_invalidate_us_percentile_ranges=None)
            work = self.workloads[name]
            work['groups'] += 1
            for key in ('samples','latency_samples','tiles','pattern_payload_bytes'):
                work[key] += value[key]
            for source,target in (('frame_us_p50_p95_p99','frame_us_percentile_ranges'),
                    ('flush_us_p50_p95_p99','flush_us_percentile_ranges'),
                    ('synthetic_invalidate_us_p50_p95_p99','synthetic_invalidate_us_percentile_ranges')):
                values = value[source]
                if values is None:
                    continue
                bounds = work[target]
                if bounds is None:
                    work[target] = [[v,v] for v in values]
                else:
                    for index in range(3):
                        bounds[index][0] = min(bounds[index][0],values[index])
                        bounds[index][1] = max(bounds[index][1],values[index])
        elif tag == 'UI_HEAP':
            heap = self.heap
            free = value['free']
            if heap['groups'] == 0:
                heap['first_free'] = heap['min_free'] = heap['max_free'] = free
            heap['groups'] += 1
            heap['last_free'] = free
            if free is not None:
                heap['min_free'] = min(heap['min_free'],free)
                heap['max_free'] = max(heap['max_free'],free)
            heap['last_cycle'],heap['elapsed_ms'] = value['cycle'],value['elapsed_ms']
        elif tag == 'UI_FINISH':
            self.finish = value
        else:
            raise ValueError('unknown benchmark record')


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


def run(app, widgets, samples=128, cycles=1, seconds=0, profile=None, report=None):
    """Run at least cycles and seconds, with a fixed-size sample workspace.

    Millisecond ticks keep hour-long runs below ticks_diff's half-period.
    seconds is bounded to one day; automatic GC/allocation counts are unknown.
    """
    if (type(samples) is not int or type(cycles) is not int or type(seconds) is not int or
            not 2 <= samples <= 512 or cycles < 1 or not 0 <= seconds <= 86400):
        raise ValueError('samples 2..512, cycles >=1, seconds integer 0..86400')
    if report is None:
        report = _stdout_report
    root,label,panel,listing,other,button = widgets
    times = array('I',[0]*samples)
    flushes = array('I',[0]*samples)
    latencies = array('I',[0]*samples)
    app.step()
    gc.collect()
    heap_start = gc.mem_free() if hasattr(gc,'mem_free') else None
    started = _now_ms()
    cycle = 0
    while cycle < cycles or elapsed(_now_ms(),started) < seconds*1000:
        for workload in _WORKLOADS:
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
            result = dict(cycle=cycle,workload=workload,samples=samples,profile=profile,
                          frame_us_p50_p95_p99=_percentiles(times),
                          flush_us_p50_p95_p99=_percentiles(flushes),
                          synthetic_invalidate_us_p50_p95_p99=_percentiles(latencies[:latency_n]) if latency_n else None,
                          latency_samples=latency_n,
                          tiles=total_tiles,pattern_payload_bytes=total_bytes)
            report('UI_BENCH',result)
            del result
        gc.collect()
        report('UI_HEAP',dict(cycle=cycle,elapsed_ms=elapsed(_now_ms(),started),free=gc.mem_free() if hasattr(gc,'mem_free') else None,
                             gc_count=None,allocation_count=None))
        cycle += 1
    gc.collect()
    report('UI_FINISH',dict(heap_start=heap_start,elapsed_ms=elapsed(_now_ms(),started),cycles=cycle,
                            heap_end=gc.mem_free() if hasattr(gc,'mem_free') else None))


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
