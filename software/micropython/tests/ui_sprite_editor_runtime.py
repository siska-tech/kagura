# SPDX-License-Identifier: Apache-2.0
"""Sprite editor example on CPython and MicroPython v1.26 unix (font path argument).

MicroPython needs examples/ on MICROPYPATH. Output must be identical.
"""
import sys
if sys.implementation.name != 'micropython':
    sys.dont_write_bytecode = True
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
    import test_driver
import binascii
from kagura.ui import App, Event, Theme, BitmapFont8
from kagura.ui.mock import MockBackend
from kagura_ja import Font
import ui_sprite_editor

font = Font(sys.argv[1])
backend = MockBackend()
app = App(backend=backend, theme=Theme(BitmapFont8(font)))
ui_sprite_editor.build(app)
editor = ui_sprite_editor.editor
app.step()
print('initial', binascii.crc32(backend.pixels) & 0xffffffff)
keys = ('up', 'down', 'left', 'right', 'enter', 'delete', 'text', 'text', 'tab')
seed = 3
for n in range(300):
    seed = (seed * 1103515245 + 12345) & 0x7fffffff
    key = keys[seed % len(keys)]
    text = '0123456789abcdefu'[(seed >> 8) % 17] if key == 'text' else ''
    app.events.post(Event(key, text))
    if n % 3 == 2:
        app.step()
app.step()
incremental = binascii.crc32(backend.pixels) & 0xffffffff
app.damage((0, 0, 320, 240))
app.step()
assert binascii.crc32(backend.pixels) & 0xffffffff == incremental
text = editor.export_hex()
print('edited', incremental, 'cursor', editor.grid.cursor, 'color', editor.grid.color)
print('sprite', binascii.crc32(editor.sprite.export()) & 0xffffffff, text[:32])
editor.import_hex(text[2:] + text[:2])
app.step()
editor.undo()
app.step()
assert editor.export_hex() == text
print('final', binascii.crc32(backend.pixels) & 0xffffffff)
app.close()
font.close()
print('UI_SPRITE_EDITOR_RUNTIME_PASS')
