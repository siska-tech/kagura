# SPDX-License-Identifier: Apache-2.0
"""Font protocol: height, advance(character), glyph(character), measure(text).

glyph returns MSB-first rows for BitmapFont8. Larger/variable glyph formats can
provide draw(renderer, text, x, y, color) using the same public drawing surface.
"""


class BitmapFont8:
    height = 8

    def __init__(self, source=None, cache=64):
        # source: existing kagura_ja.Font, caller owns its file lifetime.
        if type(cache) is not int or cache < 0 or cache & (cache - 1):
            raise ValueError('cache must be 0 or a power of two')
        self.source = source
        self._bits = bytearray(8)
        self._bitmap = None
        # Direct-mapped cache of file-backed glyph rows: fixed slots, a colliding code
        # replaces the slot. A hit avoids the KJ8F binary search and allocates nothing.
        self._mask = cache - 1
        self._keys = [-1] * cache if source is not None and cache else None
        self._rows = [None] * cache if self._keys is not None else None

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
        """Return 8 MSB-first rows. Treat the result as read-only (it may be cached)."""
        source = self.source
        if source is not None:
            code = ord(ch)
            keys = self._keys
            if keys is not None:
                # Cached rows must not hide use after the caller closed the font.
                if getattr(source, '_file', 0) is None:
                    raise ValueError('font is closed')
                slot = code & self._mask
                if keys[slot] == code:
                    return self._rows[slot]
            rows = source.glyph(code)
            if rows is None:
                rows = source.glyph(63)
            if rows is None:
                raise ValueError('font has no fallback glyph')
            if keys is not None:
                keys[slot] = code
                self._rows[slot] = rows
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
        # Other glyphs go through renderer.glyph8 (masked when partly clipped); the
        # clipped runs below serve backends without glyph8.
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
                if renderer.glyph8(rows, x, y, color):
                    x += self.advance(ch)
                    continue
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
