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
        _range(index, 0, 1023, "tile index")
        if len(pixels) != 32:
            raise ValueError("4bpp tile must be 32 bytes")
        self.device.write_memory(index * 32, pixels)

    def map_entry(self, col, row, tile, palette=0, hflip=False, vflip=False):
        _range(col, 0, 63, "column")
        _range(row, 0, 31, "row")
        _range(tile, 0, 1023, "tile")
        _range(palette, 0, 15, "palette")
        word = tile | palette << 10 | bool(hflip) << 14 | bool(vflip) << 15
        self.device.write_memory(0x8000 + (row * 64 + col) * 2, _le(word, 2))

    def sprite(self, index, x=0, y=0, tile=0, palette=0, enable=True,
               size16=False, hflip=False, vflip=False, behind=False):
        _range(index, 0, 255, "sprite")
        _range(x, -512, 511, "sprite x")
        _range(y, -512, 511, "sprite y")
        _range(tile, 0, 1023, "tile")
        _range(palette, 0, 15, "palette")
        flags = (bool(enable) << 2 | bool(size16) << 3 | bool(hflip) << 4
                 | bool(vflip) << 5 | bool(behind) << 6)
        record = bytes((x & 255, (x >> 8) & 3, y & 255, ((y >> 8) & 3) | flags,
                        tile & 255, (tile >> 8) | palette << 2, 0, 0))
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
