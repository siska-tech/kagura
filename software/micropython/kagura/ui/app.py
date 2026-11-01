# SPDX-License-Identifier: Apache-2.0
import time
from .events import EventQueue, TerminalInput, now_us, elapsed
from .render import Renderer, FramebufferBackend, intersect, nonempty
from .theme import Theme


class FocusManager:
    def __init__(self, app):
        self.app, self.current = app, None
        self.dirty = True

    def _walk(self, widget, clip):
        if widget is None or not widget.visible or not widget.enabled:
            return
        clip = intersect(clip, widget.bounds)
        if not nonempty(clip):
            return
        if widget.focusable:
            yield widget
        for child in widget.children:
            yield from self._walk(child, clip)

    def candidates(self):
        return self._walk(self.app.root, (0, 0, self.app.renderer.width, self.app.renderer.height))

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
        first = None
        found = False
        for widget in self.candidates():
            if first is None:
                first = widget
            if widget is self.current:
                found = True
        if not found:
            self.set(first)
        self.dirty = False

    def move(self, backwards=False):
        # Navigation is infrequent; this bounded-by-tree list is not a frame buffer.
        widgets = list(self.candidates())
        if widgets:
            index = widgets.index(self.current) if self.current in widgets else (-1 if not backwards else 0)
            self.set(widgets[(index + (-1 if backwards else 1)) % len(widgets)])

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
                 theme=None, input_adapter=None, queue_capacity=32):
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
        self._damage = None
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
            old = self._damage
            self._damage = rect if old is None else (min(old[0], rect[0]), min(old[1], rect[1]),
                                                     max(old[2], rect[2]), max(old[3], rect[3]))

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
        rect = self._damage
        if rect is None:
            self.last_frame_us = elapsed(now_us(), begin)
            return False
        self._damage = None
        self.renderer.clip = rect
        # Preserve damage through both paint and flush exceptions.
        try:
            self.renderer.fill_rect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1],
                                    self.theme.background)
            if self.root is not None:
                self.root._draw(self.renderer, self.theme)
            self.last_flush = self.backend.flush()
        except BaseException:
            self.damage(rect)
            raise
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
