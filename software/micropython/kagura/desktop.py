# SPDX-License-Identifier: Apache-2.0
"""Native GEM-style desktop on KAGURA-9 (C module kagura_desktop).

The desktop's 320x200 4bpp plane, windows, menus, compositor and Japanese
text live in C (software/desktop); this module connects it to the display
through the same SDK device the HDMI console uses, so there is one hardware
owner and one transport:

    from kagura.desktop import Desktop
    desk = Desktop(menus=(('ファイル', ('開く', '-', '終了')),))
    win = desk.create_window('神楽デスクトップ', 20, 30, 200, 100)
    win.text(8, 8, 'こんにちは', 1)
    desk.present()        # composes the damage, sends only changed tiles
    ...
    desk.close()          # the console takes the screen back

Ownership: while open, the desktop owns patterns 0..1000, the BG map,
scroll, raster scroll, BACKDROP and the 16 colours of its palette bank,
like KAGURA-UI's App(exclusive=True). The console is paused and resumed on
close(), which reclaims its tiles, map and palette. Sprites stay disabled.

Placement: patterns 0..999 are the desktop's 1,000 tiles (40x25). The plane
is centred in the 320x240 output: SCROLL_Y 236 shows map rows 0..24 on lines
20..219; every other map cell shows pattern 1000, all colour 0, which shows
BACKDROP (palette entry 0 of the bank, the desk colour).

Everything else (create_window, sprite, pointer, key, poll, ...) is the
kagura_desktop.Desktop API, see software/desktop/README.md.
"""
import kagura_desktop as _kd

from . import regs as R
from .video import Video

# software/desktop/core/kd_gfx.c kd_palette_rgb444
PALETTE = (0x0A5, 0x000, 0xFFF, 0xBBB, 0x666, 0x23C, 0xD22, 0xEC2,
           0x063, 0x2BC, 0xC4C, 0x842, 0x8AF, 0x8E8, 0xF82, 0xFFC)
BLANK = 1000
SCROLL_Y = 236
# Runs separated by at most this many clean tiles are sent as one: on the
# accelerated link a run costs about 1.1 ms and an extra tile about 24 us.
MAX_GAP = 32


def _console():
    try:
        import __main__
        return getattr(__main__, 'kagura_console', None)
    except ImportError:
        return None


class Desktop:
    def __init__(self, device=None, console=None, menus=None, cursor=True, palette=0, outline_drag=False):
        if console is None:
            console = _console()
        if device is None:
            screen = getattr(console, 'screen', None)
            if screen is None:
                raise RuntimeError('no KAGURA device (pass device=, or start the console)')
            device = screen.device
        if device.abi != (0, 6) or device.height != 240:
            raise ValueError('the desktop needs ABI 0.6 and the 320x240 mode')
        if not 0 <= palette <= 15:
            raise ValueError('palette bank 0..15')
        # Native state first: a failure here touches no hardware.
        self._kd = _kd.Desktop(320, 200, menus=menus, cursor=cursor, outline_drag=outline_drag)
        self.device, self.video, self.console, self.palette = device, Video(device), console, palette
        self._row = bytearray(128)
        self._open = False
        self._sink = self._write_run   # one bound method, not one per present()
        if console is not None:
            console.pause()
        try:
            self._initialize()
        except BaseException:
            self._release()
            raise
        self._open = True

    def _initialize(self):
        d, v = self.device, self.video
        if d.ext_read(R.EXT_PATTERN_COUNT_L) | d.ext_read(R.EXT_PATTERN_COUNT_H) << 8 != 1200:
            raise ValueError('PATTERN_COUNT must be 1200')
        d.busy += 1
        try:
            d.write_reg(R.REG_DISPLAY_CTRL, 0)
            d.commit()
            bank = self.palette << 10
            row = self._row
            for y in range(32):
                for x in range(64):
                    tile = y * 40 + x if y < 25 and x < 40 else BLANK
                    word = tile | bank
                    row[x * 2] = word & 255
                    row[x * 2 + 1] = word >> 8
                d.write_memory(0x8000 + y * 128, row)
            d.write_memory(0x9000, bytes(256))      # no map cell uses patterns >= 1024
            v.tiles(BLANK, bytes(32))
            for i, rgb in enumerate(PALETTE):
                v.palette(self.palette * 16 + i, rgb)
            v.scroll(0, SCROLL_Y)
            v.raster_scroll(())
            d.ext_write(R.EXT_BACKDROP, self.palette * 16)
            d.fence()
            self._kd.present(self._sink, MAX_GAP)       # every tile: the first frame
            d.write_reg(R.REG_DISPLAY_CTRL, 3)          # display + BG, no sprites
            d.commit()
            d.check_errors()
        finally:
            d.busy -= 1

    def _write_run(self, first, data):
        # One run of consecutive patterns (0..999, below the 1024 split), valid
        # during the call. FENCE per run, as TileFramebuffer; ERROR_CODE is
        # checked once per present().
        d = self.device
        link = d._link()
        if link is not None:
            link.write_memory(first * 32, data, d.timeout_us)
            link.fence(d.timeout_us)
        else:
            d.write_memory(first * 32, data)
            d.fence()

    def present(self):
        """Compose all damage and send the changed patterns. Returns the tile count."""
        d = self.device
        d.busy += 1
        try:
            tiles = self._kd.present(self._sink, MAX_GAP)
            if tiles:
                d.check_errors()
            return tiles
        finally:
            d.busy -= 1

    def _release(self):
        try:
            self._kd.close()
        finally:
            if self.console is not None:
                self.console.resume()

    def close(self):
        """Ends the desktop; the console (if any) reclaims the screen."""
        if self._open:
            self._open = False
            self._release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __getattr__(self, name):
        return getattr(self._kd, name)
