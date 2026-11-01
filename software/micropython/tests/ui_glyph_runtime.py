# SPDX-License-Identifier: Apache-2.0
"""Draw-only glyph8 edge cases on CPython, official Unix VM and RP2040.

No FPGA I/O: the minimal device is used only to construct a RAM framebuffer.
PC unit tests separately compare glyph8 against an independent linear image.
"""
import sys
if sys.implementation.name != 'micropython':
    sys.dont_write_bytecode = True
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import test_driver
import binascii
from kagura.framebuffer import TileFramebuffer


class Device:
    abi = (0,6)
    height = 240


def exercise(fb):
    rows = bytes((0x81,0x42,0x24,0x18,0xff,0,0x55,0xaa))
    fb.fill(4)
    fb.dirty[:] = bytes(1200)
    rolling = 0
    operations = 0
    for color in range(16):
        for x,y in ((-7,-7),(0,0),(7,7),(184,200),(192,200),(319,239),
                    (320,240),(1<<70,0),(-(1<<70),0)):
            fb.glyph8(rows,x,y,color)
            rolling = binascii.crc32(fb.buffer,rolling)
            rolling = binascii.crc32(fb.dirty,rolling)
            fb.dirty[:] = bytes(1200)
            fb.glyph8(rows,x,y,color)
            assert sum(fb.dirty) == 0
            operations += 2
    return operations,rolling&0xffffffff,binascii.crc32(fb.buffer)&0xffffffff


fb = TileFramebuffer(Device())
fb.set_viper(False)
expected = exercise(fb)
fb.set_viper()
if fb.viper_enabled:
    assert exercise(fb) == expected
    assert fb.kernel_counts[4] > 0
print('glyph8',expected)
print('GLYPH_RUNTIME_PASS')
del fb
