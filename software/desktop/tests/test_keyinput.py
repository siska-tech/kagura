# SPDX-License-Identifier: Apache-2.0
"""Tests of kagura.keyinput (terminal bytes -> desktop keys) on the unix port.

Unit tests against a recording sink, an allocation check, and the keyboard
loop of examples/desktop_keys.py driven end to end by terminal bytes.

  MICROPYPATH=software/micropython micropython tests/test_keyinput.py
"""
import gc
import micropython
import sys

import kagura_desktop as kd
from kagura.keyinput import StdinSource, TerminalKeys

failed = 0
run = 0


def check(cond, what=''):
    if not cond:
        raise AssertionError(what)


class Sink:
    def __init__(self):
        self.out = []

    def key(self, k, ch=0, mods=0):
        self.out.append(('key', k, ch, mods))

    def text(self, buf):
        self.out.append(('text', bytes(buf).decode()))


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


def decode(data, esc_wait=True):
    s, c = Sink(), Clock()
    k = TerminalKeys(s, clock=c)
    k.feed(data)
    if esc_wait:
        c.t += 100
        k.expire()
    return s.out, k


K = kd.KEY_CHAR


def test_printable_and_controls():
    out, _ = decode(b'aZ ~\r\n\r\t\x7f\x08\n')
    check(out == [('key', K, 97, 0), ('key', K, 90, 0), ('key', K, 32, 0), ('key', K, 126, 0),
                  ('key', kd.KEY_ENTER, 0, 0), ('key', kd.KEY_ENTER, 0, 0),   # CRLF once, then CR
                  ('key', kd.KEY_TAB, 0, 0), ('key', kd.KEY_BACKSPACE, 0, 0),
                  ('key', kd.KEY_BACKSPACE, 0, 0), ('key', kd.KEY_ENTER, 0, 0)], out)
    out, _ = decode(b'\x01\x17\x1a')
    check(out == [('key', K, ord('a'), kd.MOD_CTRL), ('key', K, ord('w'), kd.MOD_CTRL),
                  ('key', K, ord('z'), kd.MOD_CTRL)], out)


def test_utf8():
    out, k = decode('神楽é😀x'.encode())
    check(out == [('text', '神'), ('text', '楽'), ('text', 'é'), ('text', '😀'), ('key', K, ord('x'), 0)], out)
    out, k = decode(b'\xe7\xa5x\x80\xff\xe7\xa5\x9e')   # cut short, stray, invalid, then 神
    check(out == [('key', K, ord('x'), 0), ('text', '神')], out)
    check(k.invalid == 3, k.invalid)


def test_escape_sequences():
    seqs = [
        (b'\x1b[A', kd.KEY_UP, 0), (b'\x1b[B', kd.KEY_DOWN, 0), (b'\x1b[C', kd.KEY_RIGHT, 0),
        (b'\x1b[D', kd.KEY_LEFT, 0), (b'\x1b[H', kd.KEY_HOME, 0), (b'\x1b[F', kd.KEY_END, 0),
        (b'\x1bOA', kd.KEY_UP, 0), (b'\x1bOH', kd.KEY_HOME, 0), (b'\x1bOF', kd.KEY_END, 0),
        (b'\x1b[1~', kd.KEY_HOME, 0), (b'\x1b[7~', kd.KEY_HOME, 0), (b'\x1b[4~', kd.KEY_END, 0),
        (b'\x1b[8~', kd.KEY_END, 0), (b'\x1b[2~', kd.KEY_INSERT, 0), (b'\x1b[3~', kd.KEY_DELETE, 0),
        (b'\x1b[17~', kd.KEY_F6, 0), (b'\x1b[21~', kd.KEY_F10, 0), (b'\x1b[Z', kd.KEY_TAB, kd.MOD_SHIFT),
        (b'\x1b[1;2D', kd.KEY_LEFT, kd.MOD_SHIFT), (b'\x1b[1;2H', kd.KEY_HOME, kd.MOD_SHIFT),
        (b'\x1b[1;5C', kd.KEY_RIGHT, kd.MOD_CTRL), (b'\x1b[1;3A', kd.KEY_UP, kd.MOD_ALT),
        (b'\x1b[1;6D', kd.KEY_LEFT, kd.MOD_SHIFT | kd.MOD_CTRL),
        (b'\x1b[2;5~', kd.KEY_INSERT, kd.MOD_CTRL), (b'\x1b[2;2~', kd.KEY_INSERT, kd.MOD_SHIFT),
        (b'\x1b[3;2~', kd.KEY_DELETE, kd.MOD_SHIFT), (b'\x1b[21;2~', kd.KEY_F10, kd.MOD_SHIFT),
    ]
    for data, key, mods in seqs:
        out, _ = decode(data)
        check(out == [('key', key, 0, mods)], (data, out))


def test_escape_alone_and_alt():
    s, c = Sink(), Clock()
    k = TerminalKeys(s, clock=c)
    k.feed(b'\x1b')
    k.expire()
    check(s.out == [])                     # not yet: a sequence may follow
    c.t += 49
    k.expire()
    check(s.out == [])
    c.t += 1
    k.expire()
    check(s.out == [('key', kd.KEY_ESCAPE, 0, 0)])
    out, _ = decode(b'\x1b\x1b[A')         # Escape, then Up
    check(out == [('key', kd.KEY_ESCAPE, 0, 0), ('key', kd.KEY_UP, 0, 0)], out)
    out, _ = decode(b'\x1bx')              # Alt+x
    check(out == [('key', K, ord('x'), kd.MOD_ALT)], out)
    out, _ = decode(b'\x1b\r')             # Escape, then Enter
    check(out == [('key', kd.KEY_ESCAPE, 0, 0), ('key', kd.KEY_ENTER, 0, 0)], out)


def test_ignored_sequences():
    # F1 (SS3 P), F5, bracketed paste around text, SGR mouse, an unknown final.
    out, k = decode(b'\x1bOP\x1b[15~\x1b[200~hi\x1b[201~\x1b[<0;1;2M\x1b[5q')
    check(out == [('key', K, ord('h'), 0), ('key', K, ord('i'), 0)], out)
    check(k.ignored == 6, k.ignored)
    # A cut-off CSI is dropped after a while, then input continues.
    s, c = Sink(), Clock()
    k = TerminalKeys(s, clock=c)
    k.feed(b'\x1b[1;')
    c.t += 1000
    k.expire()
    k.feed(b'a')
    check(s.out == [('key', K, ord('a'), 0)], s.out)
    out, _ = decode(b'\x1b[1;2\x07a')      # a control byte abandons the sequence
    check(out[-1] == ('key', K, ord('a'), 0), out)


class Null:
    def key(self, k, ch=0, mods=0):
        pass

    def text(self, buf):
        pass


def test_feed_allocates_nothing():
    k = TerminalKeys(Null(), clock=lambda: 0)
    data = bytearray('a\x1b[1;2D神\r\n\x1b[21~é\x01'.encode())
    k.feed(data)                           # warm up the dictionaries
    micropython.heap_lock()
    try:
        for _ in range(20):
            k.feed(data)
            k.expire()
        ok = True
    except MemoryError:
        ok = False
    micropython.heap_unlock()
    check(ok, 'feed() allocated')


class Bytes:
    """A stream and poller pair standing in for stdin."""
    def __init__(self, chunks):
        self.data = b''.join(chunks)
        self.pos = 0

    def register(self, stream, flags):
        pass

    def unregister(self, stream):
        pass

    def poll(self, timeout):
        return [1] if self.pos < len(self.data) else []

    def readinto(self, buf):
        buf[0] = self.data[self.pos]
        self.pos += 1
        return 1


def test_desktop_keys_end_to_end():
    sys.path.append(sys.path[0] + '/../../micropython/examples')
    import desktop_keys as dk
    desk = dk.HostDesktop(dk.MENUS)
    app = dk.App(desk, 'keyboard')
    script = [
        b'Hi \xe7\xa5\x9e\xe6\xa5\xbd',            # 'Hi 神楽' as a terminal sends it
        b'\x1b[1;2D\x1b[1;2D',                    # Shift+Left x2: select 神楽
        b'\x1b[2;5~',                             # Ctrl+Insert: copy
        b'\t\x1b[2;2~',                           # Tab, Shift+Insert: paste into 本文
        b'\x1b[17~',                              # F6: the dialog
        b'\x1b[1;2H',                             # Shift+Home: select the name
        'テスト.TXT'.encode(), b'\r',             # Enter: the default button 保存
        b'\x1b[21~\x1b[B\x1b[B\r',               # F10, Down, Down, Enter: 終了
    ]
    b = Bytes(script)
    src = StdinSource(stream=b, poller=b)
    scenes = []
    keys = dk.keyboard(app, lambda name: scenes.append(name), source=src, idle_ms=0)
    check(app.quit and scenes == ['keyboard'])
    check(app.memo.get_text(app.subject) == 'Hi 神楽', app.memo.get_text(app.subject))
    check(app.memo.get_text(app.body) == '神楽', app.memo.get_text(app.body))
    check(app.saved == 'テスト.TXT', app.saved)
    check(keys.invalid == 0 and keys.ignored == 0)
    desk.close()


def main():
    global failed, run
    tests = [(k, v) for k, v in globals().items() if k.startswith('test_')]
    tests.sort()
    for name, fn in tests:
        run += 1
        try:
            fn()
            print('ok   ' + name[5:])
        except Exception as e:  # noqa: BLE001
            failed += 1
            print('FAIL %s: %r' % (name[5:], e))
            sys.print_exception(e)
        gc.collect()
    print('%d tests, %d failed' % (run, failed))
    sys.exit(1 if failed else 0)


main()
