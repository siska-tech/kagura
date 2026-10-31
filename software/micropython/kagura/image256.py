# SPDX-License-Identifier: Apache-2.0
"""Pseudo-256-colour pictures on the TileFramebuffer: .kimg files and PSRAM slots.

16 palettes of 16 RGB444 colours, one palette per 8x8 cell
(TileFramebuffer.set_cell_palettes). software/pico/send_image.py --save
converts any picture into a .kimg: "KIMG", 256 palette words, 1200 cell
palettes, 38400 tile-native pixel bytes and the CRC-32 of those three, the
bytes the Pico C `imgdemo recv` takes. Every palette's colour 0 is the same,
because pixel value 0 is transparent and shows BACKDROP (palette 0 colour 0),
so the framebuffer must use palette 0.

With PSRAM (CAPS PSRAM), Slots keeps pictures in the FPGA and switches them
by COPY alone, in the same layout as the C `imgdemo save`/`slide`.
"""
import binascii
from . import regs as R

MAGIC = b'KIMG'
PALETTE, CELLS, PIXELS = 512, 1200, 38400
SLOT_BASE, SLOT_SIZE, SLOTS = 0x600000, 0x10000, 16
SLOT_MAP, SLOT_FADE = 0x9600, 0xA500   # slot offsets of the map rows and the 17 palettes
_CHUNK = 1024


def check(path):
    """Read the file once and verify it; returns (palette bytes, cells). No device I/O."""
    with open(path, 'rb') as f:
        if f.read(4) != MAGIC:
            raise ValueError('not a .kimg file')
        palette, cells = f.read(PALETTE), f.read(CELLS)
        if len(palette) != PALETTE or len(cells) != CELLS:
            raise ValueError('truncated .kimg file')
        crc = binascii.crc32(cells, binascii.crc32(palette))
        chunk = memoryview(bytearray(_CHUNK))
        left = PIXELS
        while left:
            n = f.readinto(chunk[:min(_CHUNK, left)])
            if not n:
                raise ValueError('truncated .kimg file')
            crc = binascii.crc32(chunk[:n], crc)
            left -= n
        tail = f.read(5)
    if len(tail) != 4:
        raise ValueError('truncated .kimg file' if len(tail) < 4 else 'data after the CRC')
    if crc & 0xffffffff != int.from_bytes(tail, 'little'):
        raise ValueError('.kimg CRC mismatch')
    if any(palette[i] > 15 for i in range(1, PALETTE, 2)):
        raise ValueError('palette word above 0xfff')
    if any(c > 15 for c in cells):
        raise ValueError('cell palette above 15')
    return palette, cells


def _skip_header(f, chunk):
    """Read past magic, palette and cells into chunk (no 1.7 KB allocation)."""
    left = 4 + PALETTE + CELLS
    while left:
        n = f.readinto(chunk[:min(len(chunk), left)])
        if not n:
            raise OSError('.kimg changed while loading')
        left -= n


def scaled(palette, level, out):
    """The 512 palette bytes at brightness level/16 (0..16) into out."""
    for i in range(0, PALETTE, 2):
        v = palette[i] | palette[i + 1] << 8
        v = ((v >> 8 & 15) * level // 16) << 8 | ((v >> 4 & 15) * level // 16) << 4 | (v & 15) * level // 16
        out[i], out[i + 1] = v & 255, v >> 8
    return out


def map_row(cells, y, out):
    """Map row y (64 entries, 128 bytes) as set_cell_palettes leaves it, into out."""
    for x in range(40):
        tile = y * 40 + x
        word = (tile & 1023) | cells[tile] << 10
        out[x * 2], out[x * 2 + 1] = word & 255, word >> 8
    for i in range(80, 128):
        out[i] = 0
    return out


def _need_palette0(fb):
    if fb.palette:
        raise ValueError('pictures need TileFramebuffer(palette=0)')


def show(fb, path, fade_frames=24):
    """Verify path, then load it into fb with dark palettes and fade it in.

    Nothing changes unless the whole file is good. Returns (palette, cells).
    """
    _need_palette0(fb)
    palette, cells = check(path)
    d, level = fb.device, bytearray(PALETTE)
    d.write_memory(0x9400, level)  # all black while patterns and map change
    d.commit()
    with open(path, 'rb') as f:
        _skip_header(f, memoryview(level))
        if f.readinto(fb.buffer) != PIXELS:
            raise OSError('.kimg changed while loading')
    fb.mark_dirty()
    fb.flush()
    fb.set_cell_palettes(cells)
    for frame in range(1, fade_frames + 1):
        d.write_memory(0x9400, scaled(palette, frame * 16 // fade_frames, level))
        d.commit()   # applied at VBlank
    return palette, cells


class Slots:
    """Pictures kept in PSRAM and switched by COPY, like the C imgdemo save/slide.

    Slot n at base + n * 64 KiB: patterns (38400 B), the 30 map rows at
    +0x9600, the palettes at brightness 0..16 (512 B each) at +0xA500. The
    default base 0x600000 is clear of the PCM samples at 0x400000.
    show() changes patterns and map while every palette is black, so the
    switch itself is never seen. After it the framebuffer's buffer no longer
    matches the screen: it is marked dirty, and a flush() would restore it.
    """

    def __init__(self, fb, base=SLOT_BASE, count=SLOTS):
        _need_palette0(fb)
        fb.device.require(R.CAPS_PSRAM)
        if not (0x400000 <= base and base + count * SLOT_SIZE <= 0x800000):
            raise ValueError('slots must lie in PSRAM 0x400000..0x7FFFFF')
        self.fb, self.base, self.count = fb, base, count
        self.saved = set()
        self.current = None   # slot on screen

    def _slot(self, slot):
        if not 0 <= slot < self.count:
            raise ValueError('slot 0..%d' % (self.count - 1))
        return self.base + slot * SLOT_SIZE

    def _store_tables(self, base, palette, cells):
        d, level, row = self.fb.device, bytearray(PALETTE), bytearray(128)
        for y in range(30):   # a row at a time: no 3.8 KB block on a fragmented heap
            d.write_memory(base + SLOT_MAP + y * 128, map_row(cells, y, row))
        for n in range(17):
            d.write_memory(base + SLOT_FADE + n * PALETTE, scaled(palette, n, level))

    def save(self, slot, palette, cells):
        """Store fb.buffer (the picture just shown) with its palettes and cells."""
        base = self._slot(slot)
        d = self.fb.device
        d.write_memory(base, self.fb.buffer)
        self._store_tables(base, palette, cells)
        d.fence()   # later COPYs read what was written
        self.saved.add(slot)

    def save_file(self, slot, path):
        """Check a .kimg and stream it into a slot; screen and framebuffer stay as they are."""
        base = self._slot(slot)
        palette, cells = check(path)
        d = self.fb.device
        chunk = memoryview(bytearray(_CHUNK))
        with open(path, 'rb') as f:
            _skip_header(f, chunk)
            for offset in range(0, PIXELS, _CHUNK):
                n = f.readinto(chunk[:min(_CHUNK, PIXELS - offset)])
                d.write_memory(base + offset, chunk[:n])
        self._store_tables(base, palette, cells)
        d.fence()
        self.saved.add(slot)

    def _palette(self, slot, level):
        self.fb.device.copy(self._slot(slot) + SLOT_FADE + level * PALETTE, 0x9400, PALETTE)
        self.fb.device.commit()   # applied at VBlank

    def show(self, slot, fade_frames=16):
        """Fade the slot on screen out, COPY patterns and map of `slot`, fade it in."""
        if slot not in self.saved:
            raise ValueError('slot %d holds no picture' % slot)
        fb, d, base = self.fb, self.fb.device, self._slot(slot)
        if not fb.initialized:
            raise RuntimeError('call fb.initialize() first')
        steps = max(1, min(16, fade_frames))
        if self.current is not None:
            for n in range(steps - 1, -1, -1):
                self._palette(self.current, n * 16 // steps)
        else:
            d.write_memory(0x9400, bytes(PALETTE))
            d.commit()
        d.copy(base, 0x0000, 32768)                     # tiles 0..1023
        d.copy(base + 32768, 0xB000, PIXELS - 32768)    # tiles 1024..1199
        d.copy(base + SLOT_MAP, 0x8000, 30 * 128)
        d.fence()
        self.current = slot
        fb.dirty[:] = b'\x01' * 1200
        for n in range(1, steps + 1):
            self._palette(slot, n * 16 // steps)
