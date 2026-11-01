# SPDX-License-Identifier: Apache-2.0
import time
from .events import EventQueue, TerminalInput, now_us, elapsed
from .render import Renderer, FramebufferBackend, intersect, nonempty
from .theme import Theme


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


class FocusManager:
    def __init__(self, app):
        self.app, self.current = app, None
        self.dirty = True
        # Reused scan result: found[:count] in tree order. No generator or clip tuples.
        self.found, self.count = [], 0

    def _collect(self, widget, left, top, right, bottom):
        if not widget.visible or not widget.enabled:
            return
        # Comparisons instead of max/min builtins: this runs once per visible widget.
        b = widget.bounds
        if b[0] > left:
            left = b[0]
        if b[1] > top:
            top = b[1]
        if b[2] < right:
            right = b[2]
        if b[3] < bottom:
            bottom = b[3]
        if left >= right or top >= bottom:
            return
        if widget.focusable:
            found, count = self.found, self.count
            if count < len(found):
                found[count] = widget
            else:
                found.append(widget)
            self.count = count + 1
        children = widget.children
        index = 0
        while index < len(children):
            self._collect(children[index], left, top, right, bottom)
            index += 1

    def candidates(self):
        """Rescan; return the number of focus candidates stored in found[:count]."""
        found, previous = self.found, self.count
        self.count = 0
        if self.app.root is not None:
            self._collect(self.app.root, 0, 0, self.app.renderer.width, self.app.renderer.height)
        # Drop stale references so removed widgets are not kept alive.
        for index in range(self.count, previous):
            found[index] = None
        return self.count

    def _index(self, widget):
        found = self.found
        for index in range(self.count):
            if found[index] is widget:
                return index
        return -1

    def set(self, widget):
        if widget is self.current:
            return
        if self.current is not None:
            self.current.focused = False
            if hasattr(self.current, 'pressed'):
                self.current.pressed = False
            self.current.invalidate()
        self.current = widget
        if widget is not None:
            widget.focused = True
            widget.invalidate()

    def repair(self, force=False):
        if not force and not self.dirty:
            return
        # Clear dirty before the scan: a set() side effect must not hide later changes.
        self.dirty = False
        count = self.candidates()
        if self._index(self.current) < 0:
            self.set(self.found[0] if count else None)

    def move(self, backwards=False):
        # Reuse the scan from repair() unless the tree/layout changed since then.
        count = self.candidates() if self.dirty else self.count
        self.dirty = False
        if count:
            index = self._index(self.current)
            if index < 0:
                index = -1 if not backwards else 0
            self.set(self.found[(index + (-1 if backwards else 1)) % count])

    def dispatch(self, event):
        self.repair(force=True)
        if event.kind == 'release':
            return self.current.handle(event) if self.current is not None else False
        if event.key == 'tab':
            self.move(event.shift)
            return True
        if self.current is not None and self.current.handle(event):
            return True
        if event.key in ('up', 'left', 'down', 'right'):
            self.move(event.key in ('up', 'left'))
            return True
        if event.key == 'escape':
            self.app.stop()
            return True
        return False


class App:
    """Single-thread, single graphics owner. step() separates input and paint.

    Callbacks run synchronously; keep them short and use application work slices.
    No uasyncio dependency. An external loop can call step() at its own cadence.
    """
    def __init__(self, device=None, backend=None, console=None, exclusive=False,
                 theme=None, input_adapter=None, queue_capacity=32, damage_limit=1):
        if type(damage_limit) is not int or damage_limit < 1:
            raise ValueError('damage_limit must be a positive integer')
        if backend is None:
            if device is None:
                raise ValueError('device or backend required')
            backend = FramebufferBackend(device, console, exclusive)
        elif device is not None or console is not None:
            raise ValueError('custom backend owns its own device/session')
        self.backend, self.renderer = backend, Renderer(backend)
        self.theme = theme if theme is not None else Theme()
        self.input = TerminalInput(console.uart) if input_adapter is None and console is not None else input_adapter
        self.events = EventQueue(queue_capacity)
        self.focus = FocusManager(self)
        self.root = None
        # Up to damage_limit disjoint rectangles. Default 1 (one bounding rectangle): on
        # RP2040 each extra rectangle costs a fixed repaint pass (docs/kagura-ui-damage.md).
        self.damage_limit = damage_limit
        self._damage, self._painting = [], []
        self._layout = False
        self.started = self.running = False
        self.last_frame_us = self.last_input_us = 0
        self.last_invalidate_us = None
        self._event_timestamp = None
        self.frames = 0
        self.last_flush = None

    def damage(self, rect):
        rect = intersect(rect, (0, 0, self.renderer.width, self.renderer.height))
        if nonempty(rect):
            if self._event_timestamp is not None and self.last_invalidate_us is None:
                self.last_invalidate_us = elapsed(now_us(), self._event_timestamp)
            self._add_damage(rect)

    def _add_damage(self, rect):
        rects = self._damage
        while True:
            # Absorb overlapping or edge-sharing rectangles (not corner-only contact);
            # restart as rect grows.
            index = 0
            while index < len(rects):
                r = rects[index]
                ox = min(r[2], rect[2]) - max(r[0], rect[0])
                oy = min(r[3], rect[3]) - max(r[1], rect[1])
                if ox >= 0 and oy >= 0 and (ox or oy):
                    rect = _union(rects.pop(index), rect)
                    index = 0
                else:
                    index += 1
            if len(rects) < self.damage_limit:
                rects.append(rect)
                return
            # Overflow: merge into the rectangle that grows least, then recheck overlaps.
            best = growth = None
            for index in range(len(rects)):
                r = rects[index]
                u = _union(r, rect)
                g = _area(u) - _area(r)
                if growth is None or g < growth:
                    best, growth = index, g
            rect = _union(rects.pop(best), rect)

    def request_layout(self):
        self._layout = True
        self.focus.dirty = True

    def set_root(self, root):
        if root is self.root:
            return
        if root is not None and (root.parent is not None or root.app is not None):
            raise ValueError('root already attached')
        self.focus.set(None)
        if self.root is not None:
            self.root._attach(None)
        self.root = root
        if root is not None:
            root._attach(self)
        self.request_layout()
        self.damage((0, 0, self.renderer.width, self.renderer.height))

    def _arrange(self):
        if self._layout:
            if self.root is not None:
                w = self.renderer.width if self.root.width is None else self.root.width
                h = self.renderer.height if self.root.height is None else self.root.height
                self.root.arrange(self.root.x, self.root.y, w, h, self.theme.font)
            self._layout = False

    def start(self):
        if not self.started:
            self.backend.start(self.theme)
            self.started = True
            self.damage((0, 0, self.renderer.width, self.renderer.height))

    def step(self):
        self.start()
        begin = now_us()
        self._arrange()
        self.focus.repair()
        # Terminal presses auto-release on the following step; never await key-up.
        current = self.focus.current
        if current is not None and getattr(current, 'pressed', False):
            current.pressed = False
            current.invalidate()
        if self.input is not None:
            self.input.poll(self.events)
        # Bound callback work even if a callback enqueues more events.
        remaining = self.events._count
        while remaining:
            event = self.events.pop()
            self._event_timestamp = event.timestamp
            self.last_invalidate_us = None
            try:
                self.focus.dispatch(event)
                self.last_input_us = elapsed(now_us(), event.timestamp)
                self._arrange()
            finally:
                self._event_timestamp = None
            remaining -= 1
        self.focus.repair()
        rects = self._damage
        if not rects:
            self.last_frame_us = elapsed(now_us(), begin)
            return False
        # Swap the two fixed lists; invalidations raised while painting go to the next frame.
        self._damage, self._painting = self._painting, rects
        # Preserve damage through both paint and flush exceptions. One flush covers all rects.
        root = self.root
        # An opaque root (Screen/Panel) repaints every pixel it covers; skip the
        # duplicate background fill, a fixed-cost SDK call per rectangle.
        cover = root.bounds if root is not None and root.visible and root.opaque else None
        try:
            for rect in rects:
                self.renderer.clip = rect
                if (cover is None or rect[0] < cover[0] or rect[1] < cover[1] or
                        rect[2] > cover[2] or rect[3] > cover[3]):
                    self.renderer.fill_rect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1],
                                            self.theme.background)
                if root is not None:
                    root._draw(self.renderer, self.theme)
            self.last_flush = self.backend.flush()
        except BaseException:
            for rect in rects:
                self._add_damage(rect)
            raise
        finally:
            while rects:
                rects.pop()
        self.frames += 1
        self.last_frame_us = elapsed(now_us(), begin)
        return True

    def stop(self):
        self.running = False

    def run(self, idle_ms=10):
        self.running = True
        try:
            while self.running:
                self.step()
                if hasattr(time, 'sleep_ms'):
                    time.sleep_ms(idle_ms)
                else:
                    time.sleep(idle_ms / 1000)
        finally:
            self.close()

    def close(self):
        self.running = False
        self.backend.close()
        self.started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()
