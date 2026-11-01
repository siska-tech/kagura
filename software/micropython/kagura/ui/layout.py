# SPDX-License-Identifier: Apache-2.0
from .widget import Widget


class _Box(Widget):
    vertical = True

    def __init__(self, spacing=0, padding=0, **kwargs):
        if spacing < 0 or padding < 0:
            raise ValueError('negative spacing/padding')
        super().__init__(**kwargs)
        self.spacing, self.padding = spacing, padding

    def measure(self, font):
        major = cross = count = 0
        for child in self.children:
            if child.visible:
                w, h = child.measure(font)
                major += h if self.vertical else w
                cross = max(cross, w if self.vertical else h)
                count += 1
        major += max(0, count - 1) * self.spacing + 2 * self.padding
        cross += 2 * self.padding
        w, h = (cross, major) if self.vertical else (major, cross)
        return (w if self.width is None else self.width,
                h if self.height is None else self.height)

    def arrange(self, x, y, width, height, font):
        # Children retain requested sizes; overflowing content is clipped, never shrunk.
        new = (x, y, x + width, y + height)
        if self.bounds != new:
            self.invalidate()
            self.bounds = new
            self.invalidate()
        cursor = self.padding
        for child in self.children:
            if child.visible:
                w, h = child.measure(font)
                cx, cy = (self.padding, cursor) if self.vertical else (cursor, self.padding)
                child.arrange(x + cx, y + cy, w, h, font)
                cursor += (h if self.vertical else w) + self.spacing


class VBox(_Box):
    pass


class HBox(_Box):
    vertical = False
