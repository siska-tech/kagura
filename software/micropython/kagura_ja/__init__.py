# SPDX-License-Identifier: Apache-2.0
"""8x8 Japanese text on the KAGURA background map (Misaki Gothic font file).

Glyphs are read from the KJ8F file on demand (binary search, never the whole
font) and registered as 4bpp tiles. Every character takes one 8x8 cell.
The application owns the tile range and map rectangle; see README.
"""
from kagura.device import _range

_MAGIC = b"KJ8F"
_FORMAT = 1
_RECORD = 10
_QUESTION = 0x3F
# Two pixels of one glyph row -> one 4bpp byte, left pixel in the high nibble.
_PAIR = (0x00, 0x01, 0x10, 0x11)


class Font:
    def __init__(self, path):
        f = open(path, "rb")
        try:
            header = f.read(8)
            if len(header) != 8 or header[:4] != _MAGIC:
                raise ValueError("not a KJ8F font")
            if header[4] | header[5] << 8 != _FORMAT:
                raise ValueError("unsupported KJ8F format")
            count = header[6] | header[7] << 8
            if count == 0 or f.seek(0, 2) != 8 + count * _RECORD:
                raise ValueError("KJ8F size does not match glyph count")
        except BaseException:
            f.close()
            raise
        self._file = f
        self.count = count
        self._record = bytearray(_RECORD)

    def glyph(self, code):
        """Return the 8 rows for a BMP code, or None if the font lacks it."""
        if self._file is None:
            raise ValueError("font is closed")
        if not 0 <= code <= 0xFFFF:
            return None
        f, record = self._file, self._record
        lo, hi = 0, self.count - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            f.seek(8 + mid * _RECORD)
            if f.readinto(record) != _RECORD:
                raise ValueError("KJ8F record truncated")
            found = record[0] | record[1] << 8
            if found == code:
                return bytes(record[2:])
            if found < code:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _tile(rows):
    tile = bytearray(32)
    i = 0
    for row in rows:
        for shift in (6, 4, 2, 0):
            tile[i] = _PAIR[(row >> shift) & 3]
            i += 1
    return tile


class TextLayer:
    """Fixed 8x8 cells in a background-map rectangle.

    Tile tile_base is the blank cell; the remaining tile_count - 1 tiles hold
    glyphs, registered on first use and kept until clear(). Pixel value 1
    uses the palette's colour 1; value 0 is the transparent background.
    """

    def __init__(self, device, font, tile_base=128, tile_count=256,
                 map_x=0, map_y=0, width=40, height=None, palette=0):
        if height is None:
            height = device.height // 8 - map_y
        _range(tile_count, 2, 1024, "tile_count")
        _range(tile_base, 0, 1024 - tile_count, "tile_base")
        _range(width, 1, 64, "width")
        _range(height, 1, 32, "height")
        _range(map_x, 0, 64 - width, "map_x")
        _range(map_y, 0, 32 - height, "map_y")
        _range(palette, 0, 15, "palette")
        self.device, self.font = device, font
        self.tile_base, self.capacity = tile_base, tile_count - 1
        self.map_x, self.map_y = map_x, map_y
        self.width, self.height = width, height
        self._attr = palette << 10
        blank = tile_base | self._attr
        self._blank = bytes((blank & 255, blank >> 8))
        self._map = bytearray(self._blank * (width * height))
        self._tiles = None  # code -> tile; None until the first clear()
        self._next = 0

    @property
    def glyphs(self):
        """Glyph tiles in use since the last clear()."""
        return self._next - self.tile_base - 1 if self._tiles is not None else 0

    def _map_address(self, row):
        return 0x8000 + ((self.map_y + row) * 64 + self.map_x) * 2

    def clear(self):
        """Blank the rectangle; glyph tiles become free after the FENCE."""
        d = self.device
        self._tiles = None  # unusable until this clear has completed
        d.busy += 1
        try:
            d.write_memory(self.tile_base * 32, bytes(32))
            self._map[:] = self._blank * (self.width * self.height)
            row_bytes = self.width * 2
            for row in range(self.height):
                d.write_memory(self._map_address(row),
                               memoryview(self._map)[row * row_bytes:(row + 1) * row_bytes])
            d.fence()
        finally:
            d.busy -= 1
        # Only now can no queued map entry still point at an old glyph tile.
        self._tiles = {0x20: self.tile_base, 0x3000: self.tile_base}
        self._next = self.tile_base + 1

    def text(self, s, col=0, row=0):
        """Draw s from (col, row); return the cursor (col, row) after it.

        '\\n' starts the next row at column 0, '\\r' returns to column 0, and a
        character past the right edge wraps. Cells outside the rectangle are
        clipped. Characters missing from the font show as '?'. If the text
        needs more new glyph tiles than are free, MemoryError is raised
        before anything is written. After a transfer error, clear() again.
        """
        if not isinstance(s, str):
            raise TypeError("text must be str")
        if self._tiles is None:
            raise RuntimeError("call clear() before text()")
        _range(col, -0x8000, 0x7FFF, "col")
        _range(row, -0x8000, 0x7FFF, "row")
        width, height = self.width, self.height
        # One small int per visible cell: BMP code << 11 | cell index (< 2048).
        cells = []
        for ch in s:
            if ch == "\n":
                col, row = 0, row + 1
                continue
            if ch == "\r":
                col = 0
                continue
            if col >= width:
                col, row = 0, row + 1
            if 0 <= col and 0 <= row < height:
                cells.append(min(ord(ch), 0xFFFF) << 11 | (row * width + col))
            col += 1

        # Resolve every new glyph before touching the device.
        tiles = self._tiles
        new = {}  # code -> tile, for this call only
        data = bytearray()
        next_tile = self._next
        for cell in cells:
            code = cell >> 11
            if code in tiles or code in new:
                continue
            rows = self.font.glyph(code) if code >= 0x20 else None
            if rows is None:
                if _QUESTION not in tiles and _QUESTION not in new:
                    rows = self.font.glyph(_QUESTION) or bytes(8)
                    if any(rows):
                        new[_QUESTION] = next_tile
                        next_tile += 1
                        data += _tile(rows)
                    else:
                        new[_QUESTION] = self.tile_base
                new[code] = new.get(_QUESTION, tiles.get(_QUESTION))
            elif any(rows):
                new[code] = next_tile
                next_tile += 1
                data += _tile(rows)
            else:
                new[code] = self.tile_base
        used = next_tile - self.tile_base - 1
        if used > self.capacity:
            raise MemoryError("kagura_ja needs %d glyph tiles, %d available"
                              % (used, self.capacity))

        dirty = {}  # row -> (first, last) cell index written in it
        for cell in cells:
            code, i = cell >> 11, cell & 0x7FF
            tile = tiles.get(code)
            if tile is None:
                tile = new[code]
            entry = tile | self._attr
            self._map[i * 2] = entry & 255
            self._map[i * 2 + 1] = entry >> 8
            r = i // width
            span = dirty.get(r)
            dirty[r] = (i, i) if span is None else (min(span[0], i), max(span[1], i))

        d = self.device
        d.busy += 1
        try:
            if data:
                d.write_memory(self._next * 32, data)
            tiles.update(new)
            self._next = next_tile
            for r in sorted(dirty):
                first, last = dirty[r]
                d.write_memory(self._map_address(r) + (first - r * width) * 2,
                               memoryview(self._map)[first * 2:(last + 1) * 2])
        except BaseException:
            # The RAM map and glyph table may no longer match VRAM.
            self._tiles = None
            raise
        finally:
            d.busy -= 1
        return col, row

    def flush(self):
        """Wait until queued tile and map writes have reached VRAM."""
        self.device.fence()
