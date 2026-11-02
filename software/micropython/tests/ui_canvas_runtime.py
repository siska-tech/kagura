# SPDX-License-Identifier: Apache-2.0
"""Canvas/SpriteCanvas/Sprite4 run unchanged on CPython and MicroPython v1.26 unix.

Output (CRCs and counts) must be identical; PC unit tests check the pixels.
"""
import sys
if sys.implementation.name != 'micropython':
    sys.dont_write_bytecode = True
    import test_driver
import binascii
from kagura.ui import App, Screen, Event, Theme, SpriteCanvas, Sprite4
from kagura.ui.mock import MockBackend
from kagura.framebuffer import TileFramebuffer


class Device:
    abi = (0, 6)
    height = 240


backend = MockBackend(160, 120)
app = App(backend=backend, theme=Theme())
root = Screen(color=2)
changes = []
canvas = root.add(SpriteCanvas(x=8, y=-4, zoom=6, on_change=lambda x, y: changes.append((x, y))))
app.set_root(root)
app.step()
print('initial', binascii.crc32(backend.pixels) & 0xffffffff)
seed = 1
for n in range(200):
    seed = (seed * 1103515245 + 12345) & 0x7fffffff
    key = ('up', 'down', 'left', 'right', 'enter', 'delete', 'text')[seed % 7]
    app.events.post(Event(key, '0123456789abcdef'[(seed >> 8) & 15] if key == 'text' else ''))
    if n % 5 == 4:
        app.step()
app.step()
incremental = binascii.crc32(backend.pixels) & 0xffffffff
app.damage((0, 0, 160, 120))
app.step()
assert binascii.crc32(backend.pixels) & 0xffffffff == incremental
print('edited', incremental, 'changes', len(changes), 'cursor', canvas.cursor, 'color', canvas.color)
data = canvas.sprite.export()
print('sprite', len(data), binascii.crc32(data) & 0xffffffff)
copy = Sprite4(data=data)
assert copy.export() == data
fb = TileFramebuffer(Device())


def blits():
    fb.fill(7)
    for x, y in ((0, 0), (37, 21), (-5, 231), (311, 100)):
        fb.blit(copy.source(), x, y, key=0)
    return binascii.crc32(fb.buffer) & 0xffffffff, binascii.crc32(fb.dirty) & 0xffffffff


# Python raster is the reference everywhere. Native blit is required to match
# on RP2040 only: the unix x86-64 Viper blit faults on unaligned destinations.
fb.set_viper(False)
expected = blits()
if sys.implementation.name == 'micropython' and 'RP2040' in getattr(sys.implementation, '_machine', ''):
    fb.set_viper(True)
    assert blits() == expected
print('blit', expected)
for args in ((16, 0, 1), (0, 0, 16), (0, 0, True)):
    try:
        copy.set(*args)
        assert False
    except (IndexError, ValueError, TypeError) as e:
        print('rejected', type(e).__name__)
app.close()
print('UI_CANVAS_RUNTIME_PASS')
