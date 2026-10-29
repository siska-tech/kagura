# SPDX-License-Identifier: Apache-2.0
"""320x240 tile-native 4bpp framebuffer for ABI 0.6 (one exclusive owner)."""
from time import ticks_us, ticks_diff
from array import array
import sys

_viper = None
if sys.implementation.name == "micropython":
    try:
        from . import framebuffer_viper as _viper
    except (ImportError, RuntimeError, NotImplementedError, SyntaxError, TypeError):
        _viper = None
from . import regs as R
from .device import _range
from .video import Video


def _ints(*values):
    if any(not isinstance(v, int) for v in values):
        raise TypeError('coordinates must be integers')


class TileFramebuffer:
    width, height, columns, rows, tile_count = 320, 240, 40, 30, 1200

    def __init__(self, device, palette=0):
        _range(palette, 0, 15, 'palette')
        if device.abi != (0, 6) or device.height != 240:
            raise ValueError('TileFramebuffer requires ABI 0.6 and 320x240')
        # Allocate everything before any device I/O; MemoryError changes no FPGA state.
        self.buffer = bytearray(38400)
        self.dirty = bytearray(b'\x01' * 1200)
        self._view = memoryview(self.buffer)
        self._map_row = bytearray(128)
        self._map_high = bytearray(256)
        self.device, self.video, self.palette = device, Video(device), palette
        self.initialized = False
        self.last_flush = self._stats()
        self._params = array("i", [0] * 6)
        self._kernel_counts = bytearray(20)
        self.set_viper()

    def set_viper(self, enabled=None):
        """None=auto, False=Python, True=Viper or RuntimeError if unavailable."""
        if enabled is not None and type(enabled) is not bool:
            raise TypeError('enabled must be None or bool')
        if enabled is True and _viper is None:
            raise RuntimeError('Viper raster kernels unavailable')
        self._kernels = _viper if enabled is not False else None
        self._put = self._native_put if self._kernels is not None else self._python_put

    @property
    def viper_enabled(self):
        return self._kernels is not None

    @property
    def kernel_counts(self):
        # Counters increment inside the native kernels, not in dispatch wrappers.
        return tuple(array('I', self._kernel_counts))

    def _native_rect(self, x, y, width, height, color):
        right, bottom = min(320, x + width), min(240, y + height)
        x, y = max(0, x), max(0, y)
        if width <= 0 or height <= 0 or x >= right or y >= bottom:
            return
        p = self._params
        p[0], p[1], p[2], p[3], p[4] = x, y, right, bottom, color
        self._kernels.fill_rect(self.buffer, self.dirty, p, self._kernel_counts)

    @staticmethod
    def _stats():
        return dict(tiles=0, bytes=0, runs=0, writes=0, fences=0,
                    transfer_us=0, wait_us=0, total_us=0)

    def initialize(self, show=True):
        """Destructive ownership of all patterns/map; retry explicitly after failure.

        Palette RGB values are owned by the caller. Sprites and raster scroll are
        disabled. Unused map cells reference tile 0 with no upper bit or flips.
        """
        self.initialized = False
        d = self.device
        d.busy += 1
        try:
            count = d.ext_read(R.EXT_PATTERN_COUNT_L) | d.ext_read(R.EXT_PATTERN_COUNT_H) << 8
            if count != 1200:
                raise ValueError('PATTERN_COUNT must be 1200')
            d.write_reg(R.REG_DISPLAY_CTRL, 0)
            d.commit()
            self.dirty[:] = b'\x01' * 1200
            self._map_high[:] = bytes(256)
            row = self._map_row
            for y in range(32):
                row[:] = bytes(128)
                if y < 30:
                    for x in range(40):
                        tile = y * 40 + x
                        word = (tile & 1023) | self.palette << 10
                        row[x * 2] = word & 255
                        row[x * 2 + 1] = word >> 8
                        if tile >= 1024:
                            index = y * 64 + x
                            self._map_high[index // 8] |= 1 << (index % 8)
                d.write_memory(0x8000 + y * 128, row)
            d.write_memory(0x9000, self._map_high)
            self.video.scroll(0, 0)
            self.video.raster_scroll(())
            d.ext_write(R.EXT_BACKDROP, self.palette * 16)
            d.fence()
            self._flush()
            # COMMIT applies display/scroll/palette shadows, not pattern RAM.
            d.write_reg(R.REG_DISPLAY_CTRL, 3 if show else 0)
            d.commit()
            d.check_errors()
            self.initialized = True
        except BaseException:
            self.dirty[:] = b'\x01' * 1200
            # Best effort only; never replay a failed command or hide its exception.
            try:
                d.write_reg(R.REG_DISPLAY_CTRL, 0)
                d.commit()
            except BaseException:
                pass
            raise
        finally:
            d.busy -= 1

    def _native_put(self, x, y, color):
        if 0 <= x < 320 and 0 <= y < 240:
            p = self._params
            p[0], p[1], p[2] = x, y, color
            self._kernels.pixel(self.buffer, self.dirty, p, self._kernel_counts)

    def _python_put(self, x, y, color):
        # Internal primitives validate once, then share this clipped nibble store.
        if not (0 <= x < 320 and 0 <= y < 240):
            return
        tile = (y >> 3) * 40 + (x >> 3)
        offset = tile * 32 + (y & 7) * 4 + ((x & 7) >> 1)
        shift = 0 if x & 1 else 4
        old = self.buffer[offset]
        value = (old & ~(15 << shift)) | color << shift
        if value != old:
            self.buffer[offset] = value
            self.dirty[tile] = 1

    def pixel(self, x, y, color=None):
        _ints(x, y)
        if color is not None:
            _range(color, 0, 15, 'color')
            self._put(x, y, color)
        elif 0 <= x < 320 and 0 <= y < 240:
            tile = (y >> 3) * 40 + (x >> 3)
            offset = tile * 32 + (y & 7) * 4 + ((x & 7) >> 1)
            return (self.buffer[offset] >> (0 if x & 1 else 4)) & 15
        return None

    def fill(self, color):
        _range(color, 0, 15, 'color')
        if self._kernels is not None:
            self._native_rect(0, 0, 320, 240, color)
            return
        value = color * 17
        for tile in range(1200):
            start = tile * 32
            changed = False
            for i in range(start, start + 32):
                if self.buffer[i] != value:
                    self.buffer[i] = value
                    changed = True
            if changed:
                self.dirty[tile] = 1

    def _span(self, x, y, width, color):
        if self._kernels is not None:
            self._native_rect(x, y, width, 1, color)
            return
        end = min(320, x + width)
        x = max(0, x)
        if not (0 <= y < 240) or x >= end:
            return
        while x < end:
            tile = (y >> 3) * 40 + (x >> 3)
            offset = tile * 32 + (y & 7) * 4 + ((x & 7) >> 1)
            old = self.buffer[offset]
            if not x & 1 and x + 1 < end:
                new, step = color * 17, 2
            elif x & 1:
                new, step = (old & 240) | color, 1
            else:
                new, step = (old & 15) | color << 4, 1
            if old != new:
                self.buffer[offset] = new
                self.dirty[tile] = 1
            x += step

    def hline(self, x, y, width, color):
        _ints(x, y, width)
        _range(color, 0, 15, 'color')
        if width > 0:
            self._span(x, y, width, color)

    def vline(self, x, y, height, color):
        _ints(x, y, height)
        _range(color, 0, 15, 'color')
        if self._kernels is not None:
            self._native_rect(x, y, 1, height, color)
            return
        if height > 0 and 0 <= x < 320:
            for yy in range(max(0, y), min(240, y + height)):
                self._put(x, yy, color)

    def fill_rect(self, x, y, width, height, color):
        _ints(x, y, width, height)
        _range(color, 0, 15, 'color')
        if self._kernels is not None:
            self._native_rect(x, y, width, height, color)
            return
        if width > 0 and height > 0:
            for yy in range(max(0, y), min(240, y + height)):
                self._span(x, yy, width, color)

    def rect(self, x, y, width, height, color):
        _ints(x, y, width, height)
        _range(color, 0, 15, 'color')
        if width <= 0 or height <= 0:
            return
        self.hline(x, y, width, color)
        self.hline(x, y + height - 1, width, color)
        self.vline(x, y, height, color)
        self.vline(x + width - 1, y, height, color)

    def line(self, x0, y0, x1, y1, color):
        _ints(x0, y0, x1, y1)
        _range(color, 0, 15, 'color')
        if max(x0, x1) < 0 or min(x0, x1) >= 320 or max(y0, y1) < 0 or min(y0, y1) >= 240:
            return
        # Preserve Bresenham phase: don't clip endpoints. Large integers use
        # Python, while native differences/twice-error stay below 2**18.
        if self._kernels is not None and all(-32767 <= v <= 32767 for v in (x0, y0, x1, y1)):
            p = self._params
            p[0], p[1], p[2], p[3], p[4] = x0, y0, x1, y1, color
            self._kernels.line(self.buffer, self.dirty, p, self._kernel_counts)
            return
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = 1 if x0 < x1 else -1, 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            self._python_put(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            twice = error * 2
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    def circle(self, x, y, radius, color):
        _ints(x, y, radius)
        _range(radius, 0, 0x7FFFFFFF, 'radius')
        _range(color, 0, 15, 'color')
        if x + radius < 0 or x - radius >= 320 or y + radius < 0 or y - radius >= 240:
            return
        if self._kernels is not None and radius <= 32767 and -32767 <= x <= 32767 and -32767 <= y <= 32767:
            p = self._params
            p[0], p[1], p[2], p[3] = x, y, radius, color
            self._kernels.circle(self.buffer, self.dirty, p, self._kernel_counts)
            return
        a, b, decision = radius, 0, 1 - radius
        while b <= a:
            for xx, yy in ((a, b), (b, a), (-b, a), (-a, b), (-a, -b), (-b, -a), (b, -a), (a, -b)):
                self._python_put(x + xx, y + yy, color)
            b += 1
            if decision < 0:
                decision += b * 2 + 1
            else:
                a -= 1
                decision += (b - a) * 2 + 1

    def text(self, value, x, y, color):
        """Transparent 8x8 ASCII using MicroPython's built-in font."""
        _ints(x, y)
        _range(color, 0, 15, 'color')
        if not isinstance(value, str) or any(not 32 <= ord(c) <= 126 for c in value):
            raise ValueError('text requires printable ASCII')
        import framebuf
        bits = bytearray(8)
        bitmap = framebuf.FrameBuffer(bits, 8, 8, framebuf.MONO_HLSB)
        for ch in value:
            bitmap.fill(0)
            bitmap.text(ch, 0, 0, 1)
            if self._kernels is not None:
                if x < 320 and x + 8 > 0 and y < 240 and y + 8 > 0:
                    p = self._params
                    p[0], p[1], p[2] = x, y, color
                    self._kernels.glyph(self.buffer, self.dirty, p, self._kernel_counts, bits)
            else:
                for yy in range(8):
                    for xx in range(8):
                        if bitmap.pixel(xx, yy):
                            self._python_put(x + xx, y + yy, color)
            x += 8

    def mark_dirty(self, x=0, y=0, width=320, height=240):
        """Required after editing buffer directly; coordinates are pixels."""
        _ints(x, y, width, height)
        right, bottom = min(320, x + width), min(240, y + height)
        x, y = max(0, x), max(0, y)
        if width <= 0 or height <= 0 or x >= right or y >= bottom:
            return
        for row in range(y // 8, (bottom - 1) // 8 + 1):
            for col in range(x // 8, (right - 1) // 8 + 1):
                self.dirty[row * 40 + col] = 1

    def flush(self):
        """No I/O if clean; failure keeps the entire unconfirmed run dirty.

        Counters count requested pattern writes/bytes, not individual SPI
        register transactions. transfer_us includes write_memory error checks;
        wait_us includes FENCE and its checks, not a pure FPGA execution time.
        """
        if not self.initialized:
            raise RuntimeError('call initialize() successfully before flush()')
        return self._flush()

    def _flush(self):
        stats = self._stats()
        self.last_flush = stats
        start = ticks_us()
        d = self.device
        d.busy += 1
        try:
            tile = 0
            while tile < 1200:
                first = self.dirty.find(b'\x01', tile)
                if first < 0:
                    break
                tile = self.dirty.find(b'\x00', first)
                if tile < 0:
                    tile = 1200
                count = tile - first
                stats['runs'] += 1
                stats['bytes'] += count * 32
                stats['writes'] += 1 + int(first < 1024 < tile)
                begin = ticks_us()
                try:
                    self.video.tiles(first, self._view[first * 32:tile * 32])
                finally:
                    stats['transfer_us'] += ticks_diff(ticks_us(), begin)
                begin = ticks_us()
                stats['fences'] += 1
                try:
                    d.fence()
                    d.check_errors()
                finally:
                    stats['wait_us'] += ticks_diff(ticks_us(), begin)
                # No callback may draw while busy; only a confirmed run is clean.
                self.dirty[first:tile] = bytes(count)
                stats['tiles'] += count
        finally:
            d.busy -= 1
            stats['total_us'] = ticks_diff(ticks_us(), start)
        return stats
