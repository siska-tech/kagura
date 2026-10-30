# SPDX-License-Identifier: Apache-2.0
"""Show a pseudo-256-colour picture on the TileFramebuffer.

16 palettes of 16 RGB444 colours, one palette per 8x8 cell
(TileFramebuffer.set_cell_palettes). Convert a picture on the PC with
software/pico/send_image.py --save photo.kimg photo.jpg; the .kimg file is
"KIMG", 256 palette words, 1200 cell palettes, 38400 tile-native pixel bytes
and the CRC-32 of those three (as the Pico C imgdemo receives them).
Every palette's colour 0 is the same, because pixel value 0 shows BACKDROP.

    import image256; image256.run('photo.kimg')
"""
import binascii
import kagura
from kagura.framebuffer import TileFramebuffer

MAGIC = b'KIMG'
PALETTE, CELLS, PIXELS = 512, 1200, 38400


def check(path):
    """Read the file once and verify it; returns (palette bytes, cells). No device I/O."""
    with open(path, 'rb') as f:
        if f.read(4) != MAGIC:
            raise ValueError('not a .kimg file')
        palette, cells = f.read(PALETTE), f.read(CELLS)
        if len(palette) != PALETTE or len(cells) != CELLS:
            raise ValueError('truncated .kimg file')
        crc = binascii.crc32(cells, binascii.crc32(palette))
        chunk = memoryview(bytearray(1024))
        left = PIXELS
        while left:
            n = f.readinto(chunk[:min(1024, left)])
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


def _scaled(palette, level, out):
    for i in range(0, PALETTE, 2):
        v = palette[i] | palette[i + 1] << 8
        v = ((v >> 8 & 15) * level // 16) << 8 | ((v >> 4 & 15) * level // 16) << 4 | (v & 15) * level // 16
        out[i], out[i + 1] = v & 255, v >> 8


def show(fb, path, fade_frames=24):
    """Verify path, then load it into fb with dark palettes and fade it in.

    fb must be initialized with palette 0, which makes BACKDROP palette 0
    colour 0, the colour shared by all palettes of the picture.
    """
    if fb.palette:
        raise ValueError('the picture needs TileFramebuffer(palette=0)')
    palette, cells = check(path)   # nothing changes unless the whole file is good
    d, level = fb.device, bytearray(PALETTE)
    d.write_memory(0x9400, level)  # all black while patterns and map change
    d.commit()
    with open(path, 'rb') as f:
        f.read(4 + PALETTE + CELLS)
        if f.readinto(fb.buffer) != PIXELS:
            raise OSError('.kimg changed while loading')
    fb.mark_dirty()
    fb.flush()
    fb.set_cell_palettes(cells)
    for frame in range(1, fade_frames + 1):
        _scaled(palette, frame * 16 // fade_frames, level)
        d.write_memory(0x9400, level)
        d.commit()   # applied at VBlank
    return fb


def run(path, fb=None):
    """Connect if no fb is given (QSPI 5 MHz), then show path; returns the fb."""
    if fb is None:
        d = kagura.connect(mode='qspi', baudrate=5_000_000)
        d.transport.accelerate()
        fb = TileFramebuffer(d)
        d.write_memory(0x9400, bytes(PALETTE))   # initialize()'s COMMIT applies it
        fb.initialize()
    return show(fb, path)
