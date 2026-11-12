# SPDX-License-Identifier: Apache-2.0
"""The BG plane as a grid of unique 4bpp patterns, for one owner (ABI 0.6).

For renderers that keep their own TILE4 image, such as a native C module
(kagura-desktop): the plane maps cell (col, row) of a cols x rows grid to
pattern row * cols + col, so drawing is only a matter of sending pattern runs.

    plane = TilePlane(device, 40, 25, colors=PALETTE)
    plane.open()                 # display off; map, palette, scroll, backdrop
    plane.write(0, first_frame)  # whole patterns, each run fenced
    plane.show()                 # display + BG on, ERROR_CODE checked
    with plane:                  # a frame: device callbacks are held off
        plane.write(first, run)
        plane.check()            # raises kagura.DeviceError on ERROR_CODE

Placement: the grid sits at (left, top) of the 320x240 output, centred by
default. Every other cell shows the blank pattern (number cols * rows, all
colour 0), which shows BACKDROP: entry 0 of the palette bank. The grid stays
below pattern 1024, so a run is one VRAM write and the map has no high bits.

Ownership: open() takes all patterns below 1024, the BG map, scroll, raster
scroll, BACKDROP and the 16 colours of the bank, like TileFramebuffer.
Sprites stay off. Nothing is restored: the previous owner (for example the
HDMI console, kagura.console.active()) reclaims the screen itself.
"""
from . import regs as R
from .device import _range
from .video import Video

MAP_COLUMNS, MAP_ROWS = 64, 32


class TilePlane:
    def __init__(self, device, cols, rows, palette=0, colors=None, left=None, top=None):
        if device.abi != (0, 6) or device.height != 240:
            raise ValueError('TilePlane requires ABI 0.6 and 320x240')
        _range(cols, 1, 40, 'cols')
        _range(rows, 1, 30, 'rows')
        if cols * rows > 1023:
            raise ValueError('the grid and its blank pattern must stay below pattern 1024')
        _range(palette, 0, 15, 'palette')
        if left is None:
            left = (320 - cols * 8) // 2
        if top is None:
            top = (240 - rows * 8) // 2
        _range(left, 0, 320 - cols * 8, 'left')
        _range(top, 0, 240 - rows * 8, 'top')
        if colors is not None:
            colors = tuple(colors)
            if len(colors) != 16:
                raise ValueError('colors: 16 RGB444 values')
            for rgb in colors:
                _range(rgb, 0, 4095, 'RGB444')
        self.device, self.video = device, Video(device)
        self.cols, self.rows, self.count = cols, rows, cols * rows
        self.blank = self.count
        self.palette, self.colors, self.left, self.top = palette, colors, left, top
        self._row = bytearray(MAP_COLUMNS * 2)
        # The accelerated link's calls, bound once (transport.accelerate() at connect()).
        link = device._link()
        self._lwrite = link.write_memory if link is not None else None
        self._lfence = link.fence if link is not None else None

    def open(self):
        """Display off, then the map, blank pattern, palette, scroll and BACKDROP.

        Patterns of the grid are left as they are: write the first frame, then
        show(). A failure leaves the display off.
        """
        d, v = self.device, self.video
        d.busy += 1
        try:
            if d.ext_read(R.EXT_PATTERN_COUNT_L) | d.ext_read(R.EXT_PATTERN_COUNT_H) << 8 != 1200:
                raise ValueError('PATTERN_COUNT must be 1200')
            d.write_reg(R.REG_DISPLAY_CTRL, 0)
            d.commit()
            # SCROLL wraps the 64x32 map; scrolling by -left/-top puts map
            # cell (0, 0) at (left, top) and every cell outside the grid on screen
            # comes from map columns >= cols or rows >= rows.
            bank = self.palette << 10
            row = self._row
            for y in range(MAP_ROWS):
                for x in range(MAP_COLUMNS):
                    tile = y * self.cols + x if y < self.rows and x < self.cols else self.blank
                    word = tile | bank
                    row[x * 2] = word & 255
                    row[x * 2 + 1] = word >> 8
                d.write_memory(0x8000 + y * MAP_COLUMNS * 2, row)
            d.write_memory(0x9000, bytes(MAP_COLUMNS * MAP_ROWS // 8))   # no high bits
            v.tiles(self.blank, bytes(32))
            if self.colors is not None:
                for i, rgb in enumerate(self.colors):
                    v.palette(self.palette * 16 + i, rgb)
            v.scroll(-self.left % 512, -self.top % 256)
            v.raster_scroll(())
            d.ext_write(R.EXT_BACKDROP, self.palette * 16)
            d.fence()
        finally:
            d.busy -= 1

    def show(self):
        """Display and BG on (sprites off), committed; checks ERROR_CODE."""
        d = self.device
        d.busy += 1
        try:
            d.write_reg(R.REG_DISPLAY_CTRL, R.DISPLAY_CTRL_DISPLAY_ENABLE | R.DISPLAY_CTRL_BG_ENABLE)
            d.commit()
            d.check_errors()
        finally:
            d.busy -= 1

    def hide(self):
        """Display off, committed."""
        d = self.device
        d.busy += 1
        try:
            d.write_reg(R.REG_DISPLAY_CTRL, 0)
            d.commit()
        finally:
            d.busy -= 1

    def write(self, first, data):
        """Whole patterns first, first + 1, ... of the grid, then FENCE.

        ERROR_CODE is not read here: check() once per frame.
        """
        n = len(data)
        if first < 0 or n & 31 or first + (n >> 5) > self.count:
            raise ValueError('pattern run outside the grid')
        if self._lwrite is not None:
            t = self.device.timeout_us
            self._lwrite(first * 32, data, t)
            self._lfence(t)
        else:
            d = self.device
            d.write_memory(first * 32, data)
            d.fence()

    def read(self, first, buffer):
        """Reads patterns of the grid back into buffer (whole or partial patterns)."""
        if first < 0 or first * 32 + len(buffer) > self.count * 32:
            raise ValueError('pattern read outside the grid')
        self.device.read_memory_into(first * 32, buffer)

    def check(self):
        """Raises kagura.DeviceError if ERROR_CODE is set."""
        self.device.check_errors()

    def error_code(self):
        return self.device.read_reg(R.REG_ERROR_CODE)

    def __enter__(self):
        self.device.busy += 1
        return self

    def __exit__(self, *exc):
        self.device.busy -= 1
