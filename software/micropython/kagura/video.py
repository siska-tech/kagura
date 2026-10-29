# SPDX-License-Identifier: Apache-2.0
from . import regs as R
from .device import _range, _le


class Video:
    def __init__(self, device):
        self.device = device

    def palette(self, index, rgb444):
        _range(index, 0, 255, "palette index")
        _range(rgb444, 0, 4095, "RGB444")
        self.device.write_memory(0x9400 + index * 2, _le(rgb444, 2))

    def tile(self, index, pixels):
        if len(pixels) != 32:
            raise ValueError("4bpp tile must be 32 bytes")
        self.tiles(index, pixels)

    def tiles(self, index, pixels):
        """Upload whole 4bpp tiles, splitting the 1023/1024 address boundary."""
        _range(index, 0, 1199, "tile index")
        data = memoryview(pixels)
        if len(data) % 32 or index + len(data) // 32 > 1200:
            raise ValueError("tile upload range")
        split = min(len(data), max(0, 1024 - index) * 32)
        d = self.device
        d.busy += 1
        try:
            if split:
                d.write_memory(index * 32, data[:split])
            if split < len(data):
                first = max(index, 1024)
                d.write_memory(0xB000 + (first - 1024) * 32, data[split:])
        finally:
            d.busy -= 1

    def map_words(self, index, data, high_bits=None):
        """Write packed legacy map words plus one tile bit10 per entry.

        high_bits contains bytes 0/1; None clears bit10 for every word.
        The two VRAM writes are separate: update with display stopped or
        during a safe blanking interval. Concurrent map writers must serialize.
        """
        _range(index, 0, 2047, "map index")
        data = memoryview(data)
        count = len(data) // 2
        if len(data) % 2 or index + count > 2048:
            raise ValueError("map word range")
        if high_bits is not None and (len(high_bits) != count or
                                      any(bit not in (0, 1) for bit in high_bits)):
            raise ValueError("map high bits")
        if not count:
            return
        start = index // 8
        bits = bytearray((index + count - 1) // 8 - start + 1)
        d = self.device
        d.busy += 1
        try:
            d.read_memory_into(0x9000 + start, bits)
            for n in range(count):
                offset = index + n - start * 8
                mask = 1 << (offset % 8)
                byte = offset // 8
                bits[byte] = ((bits[byte] | mask) if high_bits is not None and high_bits[n]
                              else (bits[byte] & ~mask))
            d.write_memory(0x8000 + index * 2, data)
            d.write_memory(0x9000 + start, bits)
        finally:
            d.busy -= 1

    def map_entry(self, col, row, tile, palette=0, hflip=False, vflip=False):
        _range(col, 0, 63, "column")
        _range(row, 0, 31, "row")
        _range(tile, 0, 1199, "tile")
        _range(palette, 0, 15, "palette")
        word = (tile & 1023) | palette << 10 | bool(hflip) << 14 | bool(vflip) << 15
        self.map_words(row * 64 + col, _le(word, 2), bytes((tile >> 10,)))

    def sprite(self, index, x=0, y=0, tile=0, palette=0, enable=True,
               size16=False, hflip=False, vflip=False, behind=False):
        _range(index, 0, 255, "sprite")
        _range(x, -512, 511, "sprite x")
        _range(y, -512, 511, "sprite y")
        _range(tile, 0, 1199, "tile")
        _range(palette, 0, 15, "palette")
        flags = (bool(enable) << 2 | bool(size16) << 3 | bool(hflip) << 4
                 | bool(vflip) << 5 | bool(behind) << 6)
        record = bytes((x & 255, (x >> 8) & 3, y & 255, ((y >> 8) & 3) | flags,
                        tile & 255, ((tile >> 8) & 3) | palette << 2 | ((tile >> 10) << 6), 0, 0))
        self.device.write_memory(0xA000 + index * 8, record)

    def scroll(self, x, y):
        _range(x, 0, 511, "scroll x")
        _range(y, 0, 255, "scroll y")
        self.device.busy += 1
        try:
            self.device.ext_write(R.EXT_SCROLL_X_L, x & 255)
            self.device.ext_write(R.EXT_SCROLL_X_H, x >> 8)
            self.device.ext_write(R.EXT_SCROLL_Y, y)
        finally:
            self.device.busy -= 1

    def raster_scroll(self, entries):
        entries = tuple(entries)
        self.device.require(R.CAPS_RSCROLL)
        if len(entries) > 8:
            raise ValueError("at most 8 raster entries")
        previous = -1
        for line, x, y in entries:
            _range(line, previous + 1, self.device.height - 1, "raster line")
            _range(x, 0, 511, "raster x")
            _range(y, 0, 255, "raster y")
            previous = line
        self.device.busy += 1
        try:
            self.device.wait_status(R.STATUS_COMMIT_BUSY, 0)
            self.device.ext_write(R.EXT_RS_INDEX, 0)
            for line, x, y in entries:
                for reg, value in ((R.EXT_RS_LINE, line), (R.EXT_RS_X_L, x & 255),
                                   (R.EXT_RS_X_H, x >> 8), (R.EXT_RS_Y, y)):
                    self.device.ext_write(reg, value)
            self.device.ext_write(R.EXT_RS_COUNT, len(entries))
        finally:
            self.device.busy -= 1
