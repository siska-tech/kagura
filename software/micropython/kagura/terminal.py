# SPDX-License-Identifier: Apache-2.0
"""ASCII 40-column tile terminal, with the CSI operations used by readline.

Text state is independent of hardware for host-side tests. Unsupported UTF-8
codepoints render as one '?'. SGR colours are ignored in this first console.
"""


class Terminal:
    def __init__(self, rows, columns=40):
        if rows not in (22, 30) or columns != 40:
            raise ValueError("terminal geometry")
        self.rows, self.columns = rows, columns
        self.cells = bytearray(b" " * (rows * columns))
        self.dirty = bytearray([1] * rows)
        self.scrolled = 0  # lines scrolled since the screen last caught up
        self.x = self.y = 0
        self.saved = (0, 0)
        self.escape = None
        self._utf8 = 0

    def clear(self):
        self.cells[:] = b" " * len(self.cells)
        self.dirty[:] = b"\x01" * self.rows
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
            self.cells[-width:] = b" " * width
            self.dirty[:-1] = self.dirty[1:]
            self.dirty[-1] = 1
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
                    self._utf8 -= 1
                    continue
                self._utf8 = 0
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
            elif c >= 32:
                if c >= 128:
                    self._utf8 = 1 if 192 <= c < 224 else (2 if c < 240 else 3)
                    c = 63
                if self.x == self.columns:
                    self.x = 0
                    self._down()
                self.cells[self.y * self.columns + self.x] = c
                self.dirty[self.y] = 1
                self.x += 1


class TileScreen:
    """Logical row r is map row (top + r) % 32; SCROLL_Y = top * 8.

    A newline scrolls in hardware, so only the new bottom row is written.
    """

    def __init__(self, device):
        from .video import Video
        self.device = device
        self.video = Video(device)
        self.terminal = Terminal(device.height // 8)
        self._row = bytearray(80)
        self._cursor = None
        self._top = 0
        self._scroll = False  # SCROLL_Y not yet committed

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
            self.terminal.clear()
            self.terminal.scrolled = 0
            self._top = 0
            self._scroll = False
            self._cursor = None
            self.flush()
            d.write_reg(R.REG_DISPLAY_CTRL, R.DISPLAY_CTRL_DISPLAY_ENABLE
                        | R.DISPLAY_CTRL_BG_ENABLE | R.DISPLAY_CTRL_SPR_ENABLE)
            d.commit()
        finally:
            d.busy -= 1

    def feed(self, data):
        self.terminal.feed(data)

    def flush(self):
        from . import regs as R
        t = self.terminal
        d = self.device
        d.busy += 1
        try:
            if t.scrolled:
                # Taken once, so a failed flush cannot scroll twice.
                self._top = (self._top + t.scrolled) % 32
                t.scrolled = 0
                self._scroll = True
            if self._scroll and d.height % 8:
                # 720p shows the top 4px of the map row below the last.
                d.write_memory(0x8000 + (self._top + t.rows) % 32 * 128, bytes(80))
            for row in range(t.rows):
                if t.dirty[row]:
                    for col in range(t.columns):
                        self._row[col * 2] = t.cells[row * t.columns + col]
                        self._row[col * 2 + 1] = 0
                    d.write_memory(0x8000 + (self._top + row) % 32 * 128, self._row)
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
        finally:
            d.busy -= 1
