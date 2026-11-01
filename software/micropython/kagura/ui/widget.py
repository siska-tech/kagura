# SPDX-License-Identifier: Apache-2.0
from .render import intersect, nonempty


class Widget:
    focusable = False
    # True only if paint() always fills the whole of self.bounds.
    opaque = False

    def __init__(self, x=0, y=0, width=None, height=None, visible=True, enabled=True):
        if width is not None and width < 0 or height is not None and height < 0:
            raise ValueError('negative widget size')
        self.x, self.y = x, y
        self.width, self.height = width, height
        self.visible, self.enabled = visible, enabled
        self.parent, self.app = None, None
        self.children = []
        self.bounds = (0, 0, 0, 0)
        self.focused = False

    def _attach(self, app):
        self.app = app
        for child in self.children:
            child._attach(app)

    def add(self, child):
        p = self
        while p is not None:
            if p is child:
                raise ValueError('widget cycle')
            p = p.parent
        if child.parent is not None or child.app is not None:
            raise ValueError('widget already attached')
        self.children.append(child)
        child.parent = self
        child._attach(self.app)
        self.relayout()
        return child

    def remove(self, child):
        self.children.remove(child)
        child.invalidate()
        child.parent = None
        child._attach(None)
        self.relayout()

    def relayout(self):
        if self.app is not None:
            self.app.request_layout()

    def invalidate(self):
        if self.app is not None:
            self.app.damage(self.bounds)

    def set_visible(self, value):
        value = bool(value)
        if value != self.visible:
            self.invalidate()
            self.visible = value
            self.relayout()

    def set_enabled(self, value):
        value = bool(value)
        if self.enabled != value:
            self.enabled = value
            self.invalidate()
            if self.app is not None:
                self.app.focus.dirty = True

    def set_bounds(self, x, y, width=None, height=None):
        if width is not None and width < 0 or height is not None and height < 0:
            raise ValueError('negative widget size')
        self.x, self.y = x, y
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height
        self.relayout()

    def measure(self, font):
        return self.width or 0, self.height or 0

    def arrange(self, x, y, width, height, font):
        new = (x, y, x + width, y + height)
        if self.bounds != new:
            self.invalidate()
            self.bounds = new
            self.invalidate()
        for child in self.children:
            if child.visible:
                w, h = child.measure(font)
                child.arrange(x + child.x, y + child.y, w, h, font)

    def paint(self, renderer, theme):
        pass

    def _draw(self, renderer, theme):
        if not self.visible:
            return
        previous = renderer.clip
        clip = intersect(previous, self.bounds)
        if not nonempty(clip):
            return
        renderer.clip = clip
        try:
            self.paint(renderer, theme)
            for child in self.children:
                child._draw(renderer, theme)
        finally:
            renderer.clip = previous

    def handle(self, event):
        return False


class Panel(Widget):
    opaque = True

    def __init__(self, color=None, **kwargs):
        super().__init__(**kwargs)
        self.color = color

    def paint(self, renderer, theme):
        x, y, right, bottom = self.bounds
        renderer.fill_rect(x, y, right - x, bottom - y,
                           theme.panel if self.color is None else self.color)


class Screen(Panel):
    """Reusable root container; children use coordinates relative to this panel."""
    pass
