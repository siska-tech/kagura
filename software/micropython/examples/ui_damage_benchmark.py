# SPDX-License-Identifier: Apache-2.0
"""damage_limit A/B on one App, one Framebuffer and one widget tree.

The caller passes the App class (frozen, or a RAM copy of the branch source) so
both limits run the same bytecode. Each (round, limit, workload) starts from the
same reset state; rounds alternate limit order (ABBA) to spread drift.
Per sample: frame us around App.step, SDK flush total_us, frame minus flush
("cpu": input, layout, paint), tiles/payload, and GC-visible heap deltas.
A heap increase across a step is counted as a GC observation. VM allocation and
GC counts are not available; the delta excludes steps that observed a GC.
"""
import gc
import json
import binascii
from array import array
from kagura.ui import Screen, Label, Button, Panel, ListView, Event, Theme, BitmapFont8
from kagura.ui.events import now_us, elapsed

WORKLOADS = ('idle', 'label', 'button', 'focus', 'labels', 'glyphcut')
_TEXT = ('日本語の文字列をKAGURA', '一二三四五六七八九十ABC', 'あいうえおかきくけこ0123', 'ダメージ矩形の境界テスト')


def _percentiles(values):
    ordered = sorted(values)
    return [ordered[(len(ordered) - 1) * p // 100] for p in (50, 95, 99)]


def _free():
    return gc.mem_free() if hasattr(gc, 'mem_free') else None


def _stdout_report(tag, value):
    print(tag + ' ' + json.dumps(value))


class Scene:
    """Fixed tree; reset() restores every mutable widget state."""
    def __init__(self, app):
        self.app = app
        root = self.root = Screen(color=0)
        self.label = root.add(Label('0', x=8, y=8, width=64, height=8))
        self.button = root.add(Button('GO', x=8, y=40, on_click=self._click))
        root.add(Panel(x=100, y=40, width=32, height=32, color=4))
        self.listing = root.add(ListView(['A', 'B', 'C', 'D', 'E', 'F'], x=200, y=40, width=64, height=24))
        # Text-heavy: two Japanese labels at opposite corners (disjoint rectangles).
        self.corner_a = root.add(Label('左上', x=8, y=200, width=96, height=16))
        self.corner_b = root.add(Label('右下', x=216, y=216, width=96, height=16))
        # Glyph-cut: badges overlap a Japanese block off the 8 px glyph grid, so
        # each badge rectangle cuts glyphs that the bounding rectangle would contain.
        self.block = root.add(Label('\n'.join(_TEXT), x=20, y=100, width=200, height=32))
        self.badge_a = root.add(Panel(x=36, y=103, width=13, height=19, color=5))
        self.badge_b = root.add(Panel(x=170, y=110, width=13, height=19, color=5))
        self.clicks = 0

    def _click(self):
        self.clicks += 1
        self.label.set_text(str(self.clicks))

    def reset(self):
        app = self.app
        if app.root is not self.root:
            app.set_root(self.root)
        self.clicks = 0
        self.label.set_text('0')
        self.corner_a.set_text('左上')
        self.corner_b.set_text('右下')
        for badge in (self.badge_a, self.badge_b):
            badge.color = 5
        self.listing.selected, self.listing.top = 0, 0
        while app.events.pop() is not None:
            pass
        app.focus.set(self.button)
        app.damage((0, 0, app.renderer.width, app.renderer.height))
        app.step()

    def apply(self, workload, n):
        app = self.app
        if workload == 'label':
            self.label.set_text(str(n))
        elif workload == 'button':
            app.focus.set(self.button)
            app.events.post(Event('enter'))
        elif workload == 'focus':
            # Tab alternates Button(x=8) and ListView(x=200); Panel lies between.
            app.events.post(Event('tab'))
        elif workload == 'labels':
            self.corner_a.set_text('左上%d' % n)
            self.corner_b.set_text('右下%d' % (n * 7))
        elif workload == 'glyphcut':
            color = 6 if n & 1 else 5
            for badge in (self.badge_a, self.badge_b):
                badge.color = color
                badge.invalidate()


def run(app, scene, limits=(1, 4), samples=32, rounds=2, report=None):
    """Report UI_DAMAGE per (round, limit, workload) and UI_DAMAGE_DONE.

    Raises AssertionError if incremental and full-repaint buffers differ, or if
    the two limits produce different buffers for the same round and workload.
    """
    if type(samples) is not int or not 2 <= samples <= 512 or type(rounds) is not int or rounds < 1:
        raise ValueError('samples 2..512, rounds >= 1')
    if report is None:
        report = _stdout_report
    app.start()
    backend = app.backend
    # SDK tile buffer on hardware/register model; linear surface on MockBackend.
    pixels = (lambda: backend.fb.buffer) if hasattr(backend, 'fb') else (lambda: backend.pixels)
    frame = array('I', [0] * samples)
    flush = array('I', [0] * samples)
    cpu = array('I', [0] * samples)
    alloc = array('i', [0] * samples)
    full = (0, 0, app.renderer.width, app.renderer.height)
    reference = {}
    gc_seen_total = 0
    for rnd in range(rounds):
        order = limits if rnd % 2 == 0 else tuple(reversed(limits))
        for limit in order:
            app.damage_limit = limit
            for workload in WORKLOADS:
                scene.reset()
                gc.collect()
                free_start = _free()
                tiles = payload = gc_seen = alloc_n = 0
                for n in range(samples):
                    scene.apply(workload, n)
                    before = _free()
                    begin = now_us()
                    changed = app.step()
                    frame[n] = elapsed(now_us(), begin)
                    after = _free()
                    stats = app.last_flush if changed else None
                    flush[n] = stats.get('total_us', 0) if stats else 0
                    cpu[n] = frame[n] - flush[n] if frame[n] > flush[n] else 0
                    tiles += stats.get('tiles', 0) if stats else 0
                    payload += stats.get('bytes', 0) if stats else 0
                    if before is not None:
                        if after > before:
                            gc_seen += 1
                        else:
                            alloc[alloc_n] = before - after
                            alloc_n += 1
                # Settle deferred state (e.g. the auto-released Button) before comparing.
                for _ in range(4):
                    if not app.step():
                        break
                else:
                    raise AssertionError('UI did not settle (%s, limit %d)' % (workload, limit))
                crc = binascii.crc32(pixels()) & 0xffffffff
                app.damage(full)
                app.step()
                full_crc = binascii.crc32(pixels()) & 0xffffffff
                if full_crc != crc:
                    raise AssertionError('incremental %d != full repaint %d (%s, limit %d)' % (crc, full_crc, workload, limit))
                key = (rnd, workload)
                if key not in reference:
                    reference[key] = crc
                elif reference[key] != crc:
                    raise AssertionError('limit %d differs on %s round %d' % (limit, workload, rnd))
                gc_seen_total += gc_seen
                result = dict(round=rnd, limit=limit, workload=workload, samples=samples,
                              frame_us_p50_p95_p99=_percentiles(frame),
                              cpu_us_p50_p95_p99=_percentiles(cpu),
                              flush_us_p50_p95_p99=_percentiles(flush),
                              tiles=tiles, pattern_payload_bytes=payload,
                              heap_step_delta_p50_max=[_percentiles(alloc[:alloc_n])[0], max(alloc[:alloc_n])] if alloc_n else None,
                              gc_observed_steps=gc_seen if before is not None else None,
                              free_start=free_start, free_end=_free(), crc32=crc)
                report('UI_DAMAGE', result)
                del result
    gc.collect()
    report('UI_DAMAGE_DONE', dict(rounds=rounds, limits=list(limits), samples=samples,
                                  workloads=list(WORKLOADS), free=_free(),
                                  gc_observed_steps=gc_seen_total if _free() is not None else None))


def make(app_class, device, font, console=None, exclusive=False, font_class=BitmapFont8):
    app = app_class(device, console=console, exclusive=exclusive, theme=Theme(font_class(font)))
    app.input = None  # deterministic synthetic input
    scene = Scene(app)
    app.set_root(scene.root)
    return app, scene
