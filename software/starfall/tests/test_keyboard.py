"""No hardware or pyserial required: exercise actual controller event callbacks."""
import pathlib
import runpy
import sys
import types


class Port:
    in_waiting = 0

    def __init__(self):
        self.packets = []

    def write(self, data):
        self.packets.append(data)

    def read(self, count):
        return b''

    def close(self):
        pass


port = Port()


class Root:
    def __init__(self):
        self.bindings = {}

    def title(self, _):
        pass

    def bind(self, name, callback):
        self.bindings[name] = callback

    def after(self, _, callback):
        self.send = callback

    def event(self, name, code, symbol):
        self.bindings[name](types.SimpleNamespace(keycode=code, keysym=symbol))

    def mainloop(self):
        self.event('<KeyPress>', 16, 'Shift_L')
        self.event('<KeyPress>', 87, 'W')
        self.event('<KeyPress>', 32, 'space')
        self.send()
        assert port.packets[-1] == bytes((64, 65 + 32 + 4 + 16))
        # Releasing Shift changes keysym case; physical keycode still releases W.
        self.event('<KeyRelease>', 16, 'Shift_L')
        self.event('<KeyRelease>', 87, 'w')
        self.send()
        assert port.packets[-1] == b'@Q'
        self.event('<FocusOut>', 0, '')
        self.send()
        assert port.packets[-1] == b'@A'
        # All six held bits, including the maximum packet byte 128.
        for code, key in enumerate(('a', 'd', 'w', 's', 'space', 'x')):
            self.event('<KeyPress>', code, key)
        self.send()
        assert port.packets[-1] == bytes((64, 128))


sys.modules['serial'] = types.SimpleNamespace(Serial=lambda *a, **kw: port)
sys.modules['tkinter'] = types.SimpleNamespace(
    Tk=Root, Label=lambda *a, **kw: types.SimpleNamespace(pack=lambda: None))
sys.argv = ['keyboard.py', 'TEST']
runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / 'keyboard.py'), run_name='__main__')
assert port.packets[-1] == b'@A'
print('PASS keyboard six-bit mask/Shift+W/key release/focus loss/zero-on-close')
