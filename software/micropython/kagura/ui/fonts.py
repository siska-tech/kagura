# SPDX-License-Identifier: Apache-2.0
"""Font protocol: height, advance(character), glyph(character), measure(text).

glyph returns MSB-first rows for BitmapFont8. Larger/variable glyph formats can
provide draw(renderer, text, x, y, color) using the same public drawing surface.
"""


class BitmapFont8:
    height = 8

    def __init__(self, source=None):
        # source: existing kagura_ja.Font, caller owns its file lifetime.
        self.source = source
        self._bits = bytearray(8)
        self._bitmap = None

    def advance(self, character):
        return 8

    def measure(self, text):
        width = current = 0
        height = self.height
        for ch in text:
            if ch == '\n':
                width = max(width, current)
                current = 0
                height += self.height
            else:
                current += self.advance(ch)
        return max(width, current), height

    def glyph(self, ch):
        if self.source is not None:
            rows = self.source.glyph(ord(ch))
            if rows is None:
                rows = self.source.glyph(63)
            if rows is None:
                raise ValueError('font has no fallback glyph')
            return rows
        if self._bitmap is None:
            import framebuf
            self._bitmap = framebuf.FrameBuffer(self._bits, 8, 8, framebuf.MONO_HLSB)
        self._bitmap.fill(0)
        self._bitmap.text(ch if 32 <= ord(ch) <= 126 else '?', 0, 0, 1)
        # framebuf native bit order is deliberately queried rather than assumed.
        for y in range(8):
            row = 0
            for x in range(8):
                row |= self._bitmap.pixel(x, y) << (7 - x)
            self._bits[y] = row
        return self._bits

    def draw(self, renderer, text, x, y, color):
        # Reuse SDK text/Viper glyphs for fully-contained built-in ASCII runs.
        # Custom fonts and partial clips require the clipped run surface below.
        clip = renderer.clip
        if (self.source is None and x >= clip[0] and y >= clip[1] and
                x + len(text) * 8 <= clip[2] and y + 8 <= clip[3] and
                all(32 <= ord(ch) <= 126 for ch in text) and
                renderer.text_ascii(text, x, y, color)):
            return
        left = x
        for ch in text:
            if ch == '\n':
                x, y = left, y + self.height
                continue
            if x < renderer.clip[2] and x + 8 > renderer.clip[0] and y < renderer.clip[3] and y + 8 > renderer.clip[1]:
                rows = self.glyph(ch)
                # Horizontal runs use the SDK's Viper fill_rect where available.
                for yy in range(8):
                    bits, xx = rows[yy], 0
                    while xx < 8:
                        if bits & (128 >> xx):
                            start = xx
                            xx += 1
                            while xx < 8 and bits & (128 >> xx):
                                xx += 1
                            renderer.fill_rect(x + start, y + yy, xx - start, 1, color)
                        else:
                            xx += 1
            x += self.advance(ch)
