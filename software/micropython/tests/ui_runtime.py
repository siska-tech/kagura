# SPDX-License-Identifier: Apache-2.0
"""Run unchanged on CPython and MicroPython v1.26 unix (font path argument)."""
import sys
if sys.implementation.name != 'micropython':
    sys.dont_write_bytecode = True
    import test_driver
import binascii
from kagura.ui import App, Screen, Label, Button, Event, TerminalInput, EventQueue, Theme, BitmapFont8
from kagura.ui.mock import MockBackend
from kagura_ja import Font

font = Font(sys.argv[1])
backend = MockBackend(80, 48)
app = App(backend=backend,theme=Theme(BitmapFont8(font)))
root = Screen(color=0)
label = root.add(Label('日本語\nKAGURA', x=-2, y=2, width=48, height=14))
count = [0]
def clicked():
    count[0] += 1
    label.set_text('変更%d' % count[0])
root.add(Button('OK', x=4,y=24,width=32,height=16,on_click=clicked))
app.set_root(root)
app.step()
print('initial', binascii.crc32(backend.pixels) & 0xffffffff)
assert not app.step()
q = EventQueue(2)
adapter = TerminalInput(clock=lambda: 100000)
adapter.feed('日'.encode('utf-8'), q)
assert q.pop().text == '日'
adapter.feed(b'\x1b[Z\r',app.events)
app.step()
assert count[0] == 1
print('updated', binascii.crc32(backend.pixels) & 0xffffffff)
backend.fail_flush = True
label.set_text('再試行')
try:
    app.step()
    assert False
except OSError:
    assert app._damage
backend.fail_flush = False
app.step()
print('retry', binascii.crc32(backend.pixels) & 0xffffffff)
app.close()
font.close()
print('UI_RUNTIME_PASS')
