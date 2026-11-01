# SPDX-License-Identifier: Apache-2.0
"""PC reference surface. Not imported by kagura.ui on the microcontroller."""


class MockBackend:
    def __init__(self, width=320, height=240):
        self.width, self.height = width, height
        self.pixels = bytearray(width * height)
        self.transfers = self.flushes = 0
        self.changed = 0
        self.fail_flush = False

    def start(self, theme):
        pass

    def fill_rect(self, x, y, width, height, color):
        for yy in range(max(0, y), min(self.height, y + height)):
            for xx in range(max(0, x), min(self.width, x + width)):
                index = yy * self.width + xx
                if self.pixels[index] != color:
                    self.pixels[index] = color
                    self.changed += 1

    def flush(self):
        if self.fail_flush:
            raise OSError('mock transfer failure')
        self.flushes += 1
        self.transfers += self.changed
        result = dict(changed_pixels=self.changed)
        self.changed = 0
        return result

    def close(self):
        pass
