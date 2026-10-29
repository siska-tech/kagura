# SPDX-License-Identifier: Apache-2.0
"""40-column tile terminal, with the CSI operations used by readline.

Text state is independent of hardware for host-side tests. UTF-8 is decoded
and every character takes one 8x8 cell. BMP characters above ASCII use the
optional Japanese font; malformed UTF-8 and characters without a glyph show
as '?'. SGR colours are ignored in this first console.
"""
from array import array

_QUESTION = 63
_GLYPH_BASE = 128  # tiles 0..127: ASCII and the cursor
_GLYPH_TILES = 1200 - _GLYPH_BASE
_ALIAS_LIMIT = 64
_GLYPH_BUCKETS = 1024
_NO_SLOT = 0xFFFF


class Terminal:
    def __init__(self, rows, columns=40):
        if rows not in (22, 30) or columns != 40:
            raise ValueError("terminal geometry")
        self.rows, self.columns = rows, columns
        self.cells = array("H", [32] * (rows * columns))  # BMP code per cell
        self.dirty = bytearray([1] * rows)
        self.scrolled = 0  # lines scrolled since the screen last caught up
        self.x = self.y = 0
        self.saved = (0, 0)
        self.escape = None
        self._utf8 = 0  # continuation bytes still expected
        self._code = 0
        self._minimum = 0

    def clear(self):
        self._erase(0, len(self.cells))
        self.x = self.y = 0
        self.escape = None
        self._utf8 = 0

    def _erase(self, start, end):
        for i in range(start, end):
            self.cells[i] = 32
            self.dirty[i // self.columns] = 1

    def _down(self):
        if self.y < self.rows - 1:
            self.y += 1
        else:
            # Rows move with their dirty flags; the screen scrolls in hardware
            # and only redraws the new bottom row.
            width = self.columns
            self.cells[:-width] = self.cells[width:]
            self.dirty[:-1] = self.dirty[1:]
            self._erase(len(self.cells) - width, len(self.cells))
            self.scrolled += 1

    def _csi(self, sequence, final):
        if sequence.startswith("?"):
            return  # private terminal modes (e.g. bracketed paste)
        try:
            args = [int(s) if s else 0 for s in sequence.split(";")]
        except ValueError:
            return
        if any(value < 0 for value in args):
            return
        n = args[0] or 1
        if final == "A":
            self.y = max(0, self.y - n)
        elif final == "B":
            self.y = min(self.rows - 1, self.y + n)
        elif final == "C":
            self.x = min(self.columns - 1, self.x + n)
        elif final == "D":
            self.x = max(0, self.x - n)
        elif final in ("H", "f"):
            self.y = min(self.rows - 1, n - 1)
            self.x = min(self.columns - 1, ((args[1] or 1) if len(args) > 1 else 1) - 1)
        elif final == "G":
            self.x = min(self.columns - 1, n - 1)
        elif final == "d":
            self.y = min(self.rows - 1, n - 1)
        elif final in ("J", "K"):
            pos = self.y * self.columns + min(self.x, self.columns - 1)
            start = 0 if final == "J" else self.y * self.columns
            end = len(self.cells) if final == "J" else (self.y + 1) * self.columns
            if args[0] == 0:
                self._erase(pos, end)
            elif args[0] == 1:
                self._erase(start, pos + 1)
            elif args[0] == 2:
                self._erase(start, end)
        elif final == "s":
            self.saved = (self.x, self.y)
        elif final == "u":
            self.x, self.y = self.saved

    def feed(self, data):
        for c in data:
            if self.escape is not None:
                if self.escape == "":
                    if c == 91:
                        self.escape = "["
                    else:
                        self.escape = None
                    continue
                if 64 <= c <= 126:
                    self._csi(self.escape[1:], chr(c))
                    self.escape = None
                elif len(self.escape) < 32 and 32 <= c <= 63:
                    self.escape += chr(c)
                else:
                    self.escape = None
                continue
            if self._utf8:
                if 128 <= c < 192:
                    self._code = self._code << 6 | (c & 63)
                    self._utf8 -= 1
                    if not self._utf8:
                        code = self._code
                        # Overlong forms, surrogates and non-BMP show as '?'.
                        ok = self._minimum <= code <= 0xFFFF and not 0xD800 <= code < 0xE000
                        self._put(code if ok and code >= 0xA0 else _QUESTION)
                    continue
                self._utf8 = 0
                self._put(_QUESTION)  # truncated sequence; c is processed below
            if c == 27:
                self.escape = ""
            elif c == 13:
                self.x = 0
            elif c == 10:
                self.x = 0
                self._down()
            elif c in (8, 127):
                self.x = max(0, self.x - 1)
            elif c == 9:
                spaces = 8 - (self.x % 8)
                self.feed(b" " * spaces)
            elif 194 <= c < 245:
                self._utf8 = 1 if c < 224 else (2 if c < 240 else 3)
                self._code = c & (31, 15, 7)[self._utf8 - 1]
                self._minimum = (0x80, 0x800, 0x10000)[self._utf8 - 1]
            elif c >= 128:
                self._put(_QUESTION)  # stray continuation or invalid lead
            elif c >= 32:
                self._put(c)

    def _put(self, code):
        if self.x == self.columns:
            self.x = 0
            self._down()
        self.cells[self.y * self.columns + self.x] = code
        self.dirty[self.y] = 1
        self.x += 1


class TileScreen:
    """Logical row r is map row (top + r) % 32; SCROLL_Y = top * 8.

    A newline scrolls in hardware, so only the new bottom row is written.
    Non-ASCII glyphs share tiles 128..1199. A glyph tile is reused only when
    no map cell shows it (reference count zero), so the in-order VRAM queue
    never redraws a visible character.
    """

    def __init__(self, device, font=None):
        from .video import Video
        self.device = device
        self.font = font  # kagura_ja.Font or None
        self.video = Video(device)
        self.terminal = Terminal(device.height // 8)
        self._row = bytearray(80)
        self._row_high = bytearray(self.terminal.columns)
        self._row_bits = bytearray(self.terminal.columns // 8)
        # The console owns 40 aligned cells (five complete upper-bit bytes)
        # per map row. Cache those bytes to avoid reads/extra writes for ASCII.
        self._map_bits = bytearray(32 * len(self._row_bits))
        self._cursor = None
        self._top = 0
        self._scroll = False  # SCROLL_Y not yet committed
        self._stale = []  # map rows that scrolled out, released after commit
        n = 32 * self.terminal.columns
        self._shown = array("H", [0] * n)  # tile in each map cell, by map row
        self._refs = array("H", [0] * _GLYPH_TILES)
        self._owner = array("H", [0] * _GLYPH_TILES)  # code held by a tile
        self._buckets = array("H", [_NO_SLOT]) * _GLYPH_BUCKETS
        self._next = array("H", [_NO_SLOT]) * _GLYPH_TILES  # code -> glyph tile offset
        self._alias = {}  # code -> '?' or blank tile, for codes without a glyph
        self._hand = 0
        self.glyph_overflow = 0  # characters shown as '?' for lack of tiles

    def _reset_glyphs(self):
        for i in range(_GLYPH_TILES):
            self._refs[i] = 0
        for i in range(len(self._shown)):
            self._shown[i] = 0  # initialize() fills the map with tile 0
        self._map_bits[:] = bytes(len(self._map_bits))
        for i in range(_GLYPH_BUCKETS):
            self._buckets[i] = _NO_SLOT
        for i in range(_GLYPH_TILES):
            self._next[i] = _NO_SLOT
        self._alias = {}
        self._hand = 0

    def _find_slot(self, code):
        slot = self._buckets[code & (_GLYPH_BUCKETS - 1)]
        while slot != _NO_SLOT:
            if self._owner[slot] == code:
                return slot
            slot = self._next[slot]
        return _NO_SLOT

    def _unlink_slot(self, slot):
        bucket = self._owner[slot] & (_GLYPH_BUCKETS - 1)
        current, previous = self._buckets[bucket], _NO_SLOT
        while current != _NO_SLOT:
            if current == slot:
                if previous == _NO_SLOT:
                    self._buckets[bucket] = self._next[current]
                else:
                    self._next[previous] = self._next[current]
                return
            previous, current = current, self._next[current]

    def _acquire(self, code):
        if code < 128:
            return code
        slot = self._find_slot(code)
        if slot != _NO_SLOT:
            self._refs[slot] += 1
            return _GLYPH_BASE + slot
        tile = self._alias.get(code)
        if tile is not None:
            return tile
        rows = self.font.glyph(code) if self.font is not None else None
        if rows is None or not any(rows):
            if len(self._alias) >= _ALIAS_LIMIT:
                self._alias = {}
            tile = _QUESTION if rows is None else 32
            self._alias[code] = tile
            return tile
        for _ in range(_GLYPH_TILES):  # clock scan for a tile nobody shows
            slot = self._hand
            self._hand = (slot + 1) % _GLYPH_TILES
            if not self._refs[slot]:
                break
        else:
            self.glyph_overflow += 1
            return _QUESTION
        from kagura_ja import _tile
        self.video.tile(_GLYPH_BASE + slot, _tile(rows))
        # Fixed 16-bit bucket/chain arrays avoid growing a dict on the Pico
        # heap while uploading many distinct glyphs. Unlink only after upload.
        self._unlink_slot(slot)
        bucket = code & (_GLYPH_BUCKETS - 1)
        self._next[slot] = self._buckets[bucket]
        self._buckets[bucket] = slot
        self._owner[slot] = code
        self._refs[slot] = 1
        return _GLYPH_BASE + slot

    def initialize(self):
        import framebuf
        from . import regs as R
        d = self.device
        d.busy += 1
        try:
            d.wait_status(R.STATUS_COMMIT_BUSY, 0)
            d.write_reg(R.REG_DISPLAY_CTRL, 0)
            d.commit()
            d.fill(0x8000, 4096)
            d.fill(0x9000, 256)  # row writes set tile bit10 when needed
            d.fill(0xA000, 2048)
            self.video.scroll(0, 0)
            d.ext_write(R.EXT_BACKDROP, 0)
            if d.caps & R.CAPS_RSCROLL:
                d.ext_write(R.EXT_RS_COUNT, 0)
            self.video.palette(0, 0)
            self.video.palette(1, 0xFFF)
            self.video.tile(0, bytes(32))  # also clears the 720p bottom 4px
            # Reuse the font built into MicroPython; no external font asset.
            bitmap = framebuf.FrameBuffer(bytearray(8), 8, 8, framebuf.MONO_HLSB)
            tile = bytearray(32)
            for code in range(32, 127):
                bitmap.fill(0)
                bitmap.text(chr(code), 0, 0, 1)
                for y in range(8):
                    for x in range(4):
                        tile[y * 4 + x] = bitmap.pixel(x * 2, y) << 4 | bitmap.pixel(x * 2 + 1, y)
                self.video.tile(code, tile)
            self.video.tile(127, bytes(28) + b"\x11" * 4)
            self._reset_glyphs()  # an application may have used tiles 128+
            self.terminal.clear()
            self.terminal.scrolled = 0
            self._top = 0
            self._scroll = False
            self._stale = []
            self._cursor = None
            self.flush()
            d.write_reg(R.REG_DISPLAY_CTRL, R.DISPLAY_CTRL_DISPLAY_ENABLE
                        | R.DISPLAY_CTRL_BG_ENABLE | R.DISPLAY_CTRL_SPR_ENABLE)
            d.commit()
        finally:
            d.busy -= 1

    def feed(self, data):
        self.terminal.feed(data)

    def _write_row(self, map_row, base):
        # Acquire before releasing: a glyph that stays visible cannot be reused.
        cells, columns, out = self.terminal.cells, self.terminal.columns, self._row
        high, bits = self._row_high, self._row_bits
        bits[:] = bytes(len(bits))
        acquired = 0
        bit_offset = map_row * len(bits)
        try:
            for col in range(columns):
                code = 0 if base is None else cells[base + col]
                tile = code if code < 128 else self._acquire(code)
                out[col * 2] = tile & 255
                out[col * 2 + 1] = (tile >> 8) & 3
                high[col] = tile >> 10
                if high[col]:
                    bits[col // 8] |= 1 << (col % 8)
                acquired = col + 1
            self.device.write_memory(0x8000 + map_row * 128, out)
            if bits != self._map_bits[bit_offset:bit_offset + len(bits)]:
                # No RMW needed: all bits of these five bytes belong to us.
                self.device.write_memory(0x9000 + map_row * 8, bits)
        except BaseException:
            for col in range(acquired):
                tile = out[col * 2] | out[col * 2 + 1] << 8 | high[col] << 10
                if tile >= _GLYPH_BASE:
                    self._refs[tile - _GLYPH_BASE] -= 1
            raise
        self._map_bits[bit_offset:bit_offset + len(bits)] = bits
        shown = map_row * columns
        for col in range(columns):
            old = self._shown[shown + col]
            if old >= _GLYPH_BASE:
                self._refs[old - _GLYPH_BASE] -= 1
            self._shown[shown + col] = out[col * 2] | out[col * 2 + 1] << 8 | high[col] << 10

    def _release_row(self, map_row):
        # A row scrolled out of the window is never seen again before it is
        # rewritten, so its glyph tiles may be reused without touching VRAM.
        shown = map_row * self.terminal.columns
        for col in range(self.terminal.columns):
            old = self._shown[shown + col]
            if old >= _GLYPH_BASE:
                self._refs[old - _GLYPH_BASE] -= 1
            self._shown[shown + col] = 0

    def flush(self):
        from . import regs as R
        t = self.terminal
        d = self.device
        d.busy += 1
        try:
            if t.scrolled:
                # Taken once, so a failed flush cannot scroll twice.
                for k in range(min(t.scrolled, t.rows)):
                    self._stale.append((self._top + k) % 32)
                self._top = (self._top + t.scrolled) % 32
                t.scrolled = 0
                self._scroll = True
            if self._scroll and d.height % 8:
                # 720p shows the top 4px of the map row below the last.
                self._write_row((self._top + t.rows) % 32, None)
            for row in range(t.rows):
                if t.dirty[row]:
                    self._write_row((self._top + row) % 32, row * t.columns)
                    t.dirty[row] = 0
            cursor = (min(t.x, t.columns - 1), t.y)
            if self._scroll:
                d.ext_write(R.EXT_SCROLL_Y, self._top * 8)
            if self._scroll or cursor != self._cursor:
                if cursor != self._cursor:
                    self.video.sprite(0, cursor[0] * 8, cursor[1] * 8, tile=127)
                    self._cursor = cursor
                # Scroll and cursor appear together; no wait for the frame.
                d.commit(wait=False)
            self._scroll = False
            # Rows that left the window are still shown until the commit
            # applies, at the next frame; their tiles are reused from the
            # next flush on (20ms later). Rows back in the window were redrawn.
            for map_row in self._stale:
                if (map_row - self._top) % 32 >= t.rows:
                    self._release_row(map_row)
            self._stale = []
        finally:
            d.busy -= 1
