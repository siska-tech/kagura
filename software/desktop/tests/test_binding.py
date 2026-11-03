# SPDX-License-Identifier: Apache-2.0
"""Tests of the kagura_desktop binding in MicroPython (unix port).

Covers the API, handle lifetimes (closed windows, freed sprites, replaced
desktops, reused slots), GC safety (no references from C into the heap),
atomic failures when native pools are full, the present() sinks, events,
and allocation-free operation under micropython.heap_lock().

  micropython tests/test_binding.py
"""
import binascii
import gc
import micropython
import sys
from array import array

import kagura_desktop as kd

HEART = ('0000000000111000016661001666661016626661162666661666666616666666'
         '0000000000111000016661001666661066666610666666106666661066666610'
         '0166666600166666000166660000166600000166000000160000000100000000'
         '6666610066661000666100006610000061000000100000000000000000000000')

failed = 0
run = 0


def raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print('    expected %s, got %r' % (exc.__name__, e))
        return False
    print('    expected %s, nothing raised' % exc.__name__)
    return False


def check(cond, what=''):
    if not cond:
        raise AssertionError(what)


def drain(d):
    out = []
    while True:
        e = d.poll()
        if e is None:
            return out
        out.append(e)


def test_api_basics():
    check(raises(ValueError, kd.Desktop, 320, 240))
    d = kd.Desktop(320, 200)
    w = d.create_window('Hello', 20, 30, 180, 100)
    check(isinstance(w, kd.Window))
    i = w.fill_rect(8, 8, 80, 24, 3)
    check(isinstance(i, int) and i >= 0)
    w.text(12, 14, 'Hello', 15)
    check(d.present() == 1000)          # the first present sends the whole plane
    check(d.present() == 0)             # nothing damaged
    check(w.is_open() and w.is_active() and d.top() == w)
    check(w.work() == (21, 42, 178, 87))
    check(d.windows() == (w,))
    check(raises(ValueError, d.create_window, 'tiny', 0, 20, 10, 10))


def test_closed_window_handle():
    d = kd.Desktop()
    w = d.create_window('A', 10, 20, 100, 80)
    item = w.text(4, 4, 'abc')
    w.close()
    check(not w.is_open())
    check(raises(ValueError, w.fill_rect, 0, 0, 4, 4, 1))
    check(raises(ValueError, w.set_text, item, 'x'))
    check(raises(ValueError, w.work))
    w.close()                           # closing twice is harmless
    check('closed' in repr(w))
    check(drain(d) == [(kd.FOCUS, w, 0, 0, 0, 0, 0, 0)])   # no CLOSE for a scripted close


def test_reused_slot():
    d = kd.Desktop()
    a = d.create_window('A', 10, 20, 100, 80)
    a.close()
    b = d.create_window('B', 10, 20, 100, 80)   # same slot, new serial
    check(a != b and b.is_open() and not a.is_open())
    check(raises(ValueError, a.text, 0, 0, 'x'))
    b.text(0, 0, 'x')


def test_desktop_replaced():
    d1 = kd.Desktop()
    w = d1.create_window('A', 10, 20, 100, 80)
    s = d1.sprite()
    d2 = kd.Desktop()                    # one native desktop: d1 and its handles die
    check(not d1.is_open() and d2.is_open())
    check(raises(ValueError, w.fill_rect, 0, 0, 1, 1, 1))
    check(raises(ValueError, s.set, 0, 0, 1))
    check(raises(ValueError, d1.present))
    check(not w.is_open() and not s.is_alive())
    d1.close()                           # a dead desktop's close is harmless
    check(d2.is_open())
    d2.close()
    check(raises(ValueError, d2.create_window, 'x', 0, 20, 50, 50))


def scene(d, title, label):
    w = d.create_window(title, 10, 20, 200, 120)
    w.text(4, 4, label, 1)
    w.button(4, 20, 60, 14, label[:4])
    return w


def test_gc_safety():
    d = kd.Desktop()
    scene(d, 'Expected', 'label 12345')
    d.present()
    want = d.crc()

    d = kd.Desktop()
    parts = ['label', ' ', '12345']
    title = ''.join(['Exp', 'ected'])
    w = scene(d, title, ''.join(parts))   # dynamic strings, dropped below
    del parts, title, w
    gc.collect()
    junk = [bytearray(range(256)) for _ in range(400)]   # reuse the freed heap
    del junk
    gc.collect()
    d.present()
    check(d.crc() == want, 'content survived the strings it was built from')
    w = d.windows()[0]                   # the handle is still reachable through the desktop
    check(w.is_open() and w.frame() == (10, 20, 200, 120))


def test_pool_full_is_atomic():
    d = kd.Desktop()
    w = d.create_window('W', 0, 12, 320, 188)
    n = 0
    try:
        while True:
            w.fill_rect(n % 300, n % 170, 4, 4, n % 16)
            n += 1
    except MemoryError:
        pass
    check(n == kd.sizes()['max_items'], n)
    d.present()
    crc, stats = d.crc(), d.stats()
    check(raises(MemoryError, w.text, 0, 0, 'x'))
    check(raises(MemoryError, w.fill_rects, array('h', [0, 0, 4, 4]), 1))
    check(d.present() == 0 and d.crc() == crc and d.stats()['items'] == stats['items'])
    w.clear()
    check(d.stats()['items'] == 0)
    check(raises(MemoryError, w.fill_rects, array('h', [0, 0, 4, 4] * (n + 1)), 1))   # all or none
    check(d.stats()['items'] == 0)


def test_text_and_slots_full():
    d = kd.Desktop()
    w = d.create_window('W', 0, 12, 320, 188)
    ids = []
    try:
        while True:
            ids.append(w.text(0, 0, 'a fairly long text label %d' % len(ids)))
    except MemoryError:
        pass
    check(raises(MemoryError, w.set_text, ids[0], 'x' * 60))
    d.present()
    crc = d.crc()
    w.set_text(ids[0], 'a fairly long text label 0')   # unchanged text: nothing to do
    check(d.present() == 0 and d.crc() == crc)
    for _ in range(7):
        d.create_window('more', 0, 20, 60, 40)
    check(raises(MemoryError, d.create_window, 'ninth', 0, 20, 60, 40))
    for _ in range(8):
        d.sprite()
    check(raises(MemoryError, d.sprite))


def test_invalid_arguments():
    d = kd.Desktop()
    w = d.create_window('W', 0, 12, 200, 150)
    d.present()
    for args in ((0, 0, 4, 4, 16), (0, 0, -1, 4, 1), (70000, 0, 4, 4, 1), (0, 0, 4, 4, -1)):
        check(raises(ValueError, w.fill_rect, *args), args)
    check(raises(TypeError, w.text, 0, 0, 42))
    check(raises(ValueError, w.text, 0, 0, 'x' * 64))
    check(raises(ValueError, w.text, 0, 0, 'x', 1, -1, 2))
    check(raises(TypeError, w.sprite, 0, 0, 'not a sprite'))
    check(raises(ValueError, w.fill_rects, array('i', [0, 0, 4, 4]), 1))
    check(raises(ValueError, w.icon, 0, 0, 'nope', 'x'))
    check(raises(ValueError, w.set_text, 12345678, 'x'))
    check(raises(ValueError, w.remove, -1))
    check(d.stats()['items'] == 0 and d.present() == 0)


def test_items():
    d = kd.Desktop()
    w = d.create_window('W', 0, 12, 200, 150)
    t = w.text(4, 4, 'Hello', 1, 2)
    b = w.button(4, 20, 60, 14, 'OK')
    f = w.fill_rect(80, 4, 20, 20, 5)
    w.icon(110, 4, 'folder', 'DOCS')
    d.present()
    w.set_text(t, 'Help!')
    check(0 < d.present() <= 6)            # two unaligned glyph cells: at most 3x2 tiles
    w.set_flags(b, kd.BTN_PRESSED)
    w.move_item(f, 84, 4)
    w.set_color(f, 6)
    check(d.present() > 0)
    w.remove(t)
    check(raises(ValueError, w.set_text, t, 'x'))
    check(raises(ValueError, w.set_color, b, 3))   # buttons have no colour
    d.present()
    d.invalidate(0, 0, 320, 200)
    check(d.present() == 0)                # incremental frame equals a full recomposition


def test_sprite():
    d = kd.Desktop()
    s = d.sprite(HEART)
    check(s.hex() == HEART and len(s.data()) == 128)
    check(s.get(3, 2) == 6 and s.get(5, 2) == 1)   # row 2 of the heart: 0 1 6 6 6 1 0 0
    w = d.create_window('S', 0, 12, 200, 150)
    w.sprite(4, 4, s, 6)
    w.sprite(110, 4, s, 1)
    d.present()
    check(s.set(0, 0, 9) is True and s.set(0, 0, 9) is False)
    check(1 <= d.present() <= 5)           # one 6x6 block (up to 4 tiles) and one pixel
    check(s.set_pixels(bytes([1, 1, 2, 2, 2, 3])) == 2)
    check(raises(ValueError, s.set_pixels, bytes([3, 3, 4, 16, 0, 1])))
    check(s.get(3, 3) != 4)                # nothing of a rejected batch is applied
    s.load(bytes(128))
    check(s.hex() == '0' * 256)
    check(raises(ValueError, s.load, 'xyz'))
    check(d.stats()['items'] == 2)
    s.free()
    check(d.stats()['items'] == 0 and not s.is_alive())
    check(raises(ValueError, s.set, 0, 0, 1))
    check(raises(ValueError, w.sprite, 0, 0, s))


def test_sinks():
    d = kd.Desktop()
    w = d.create_window('W', 0, 12, 200, 150)
    w.text(4, 4, 'sink')
    runs, writable = [], []

    def sink(first, mv):
        runs.append((first, len(mv)))
        try:
            mv[0] = 1
            writable.append(first)
        except TypeError:
            pass
    check(d.present(sink) == 1000)
    check(sum(n for _, n in runs) == 32000 and runs[0][0] == 0)
    check(not writable, 'the staging memoryview is read-only')

    w.fill_rect(0, 0, 200, 100, 6)
    calls = [0]

    def failing(first, mv):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError(5)
    check(raises(OSError, d.present, failing))
    left = d.present()
    check(left > 0, 'runs after the failure stayed dirty')

    def reentrant(first, mv):
        d.present()
    w.fill_rect(0, 0, 10, 10, 1)
    check(raises(RuntimeError, d.present, reentrant))
    check(raises(TypeError, d.present, 42))
    check(raises(ValueError, d.present, bytearray(100)))
    d = kd.Desktop()                       # a new desktop exports everything once
    w = d.create_window('W', 0, 12, 200, 150)
    mirror, full = bytearray(32000), bytearray(32000)
    d.present(mirror)
    d.tile4(full)
    check(mirror == full)
    w.fill_rect(20, 20, 10, 10, 3)
    d.invalidate(0, 0, 320, 200)
    d.present(mirror)                      # only changed tiles go out...
    d.tile4(full)
    check(mirror == full, 'mirror + exported runs == packed plane')   # ...and that is enough


def test_events():
    d = kd.Desktop(menus=(('Desk', ('One', 'Two')),))
    a = d.create_window('A', 10, 20, 120, 80)
    b = d.create_window('B', 150, 20, 120, 80)
    check([e[0] for e in drain(d)] == [kd.FOCUS, kd.BLUR, kd.FOCUS])
    x, y = b.work()[:2]
    d.pointer(kd.POINTER_DOWN, x + 5, y + 6, 1000)
    d.pointer(kd.POINTER_UP, x + 5, y + 6, 1100)
    d.key(kd.KEY_CHAR, 'q', 0, 1200)
    ev = drain(d)
    check(ev == [(kd.POINTER_DOWN, b, 5, 6, 0, 0, 0, 1), (kd.POINTER_UP, b, 5, 6, 0, 0, 0, 0),
                 (kd.KEY, b, 0, 0, kd.KEY_CHAR, ord('q'), 0, 0)], ev)
    d.pointer(kd.POINTER_DOWN, x + 5, y + 6, 1300)   # double click
    check(drain(d)[0][7] == 2)
    for i in range(40):
        d.key(kd.KEY_CHAR, 'a', 0, 2000 + i)
    check(len(drain(d)) == 32 and d.stats()['dropped'] == 8)
    d.pointer(kd.POINTER_DOWN, 12, 4, 3000)           # Desk menu
    d.pointer(kd.POINTER_MOVE, 12, 25, 3100)
    d.pointer(kd.POINTER_UP, 12, 25, 3200)
    check(drain(d) == [(kd.MENU, None, 0, 0, 0, 1, 0, 0)])
    fx, fy = a.frame()[:2]
    d.pointer(kd.POINTER_DOWN, fx + 4, fy + 4, 4000)  # raise A
    d.pointer(kd.POINTER_UP, fx + 4, fy + 4, 4100)
    d.pointer(kd.POINTER_DOWN, fx + 4, fy + 4, 4600)  # close box
    d.pointer(kd.POINTER_UP, fx + 4, fy + 4, 4700)
    ev = drain(d)
    check(ev[-1][0] == kd.CLOSE and ev[-1][1] == a and not a.is_open(), ev)
    lst = [None] * 8
    d.key(kd.KEY_ENTER, 0, 0, 5000)
    check(d.poll_into(lst) and lst[0] == kd.KEY and lst[1] == b and not d.poll_into(lst))


def test_event_for_reused_slot():
    d = kd.Desktop()
    a = d.create_window('A', 10, 20, 120, 80)
    drain(d)
    d.key(kd.KEY_CHAR, 'x', 0, 100)        # queued for A
    a.close()
    b = d.create_window('B', 10, 20, 120, 80)   # takes A's slot before the poll
    e = d.poll()
    check(e[1] == a and e[1] != b and not e[1].is_open(), e)


def test_heap_locked_frame():
    d = kd.Desktop()
    w = d.create_window('W', 10, 20, 200, 120)
    label = w.text(4, 4, '0000', 1, 2)
    s = d.sprite(HEART)
    w.sprite(4, 20, s, 4)
    mirror = bytearray(32000)
    lst = [None] * 8
    digits = ['%04d' % i for i in range(10)]
    d.present(mirror)
    drain(d)
    x, y = w.work()[:2]
    micropython.heap_lock()
    try:
        for i in range(10):                # a whole input/update/present loop
            d.pointer(kd.POINTER_MOVE, x + i, y + 30, 100 * i)
            d.key(kd.KEY_CHAR, 65, 0, 100 * i + 50)
            while d.poll_into(lst):
                pass
            w.set_text(label, digits[i])
            s.set(i, i, i)
            d.present(mirror)
        ok = True
    except MemoryError:
        ok = False
    micropython.heap_unlock()
    check(ok, 'no heap allocation in the frame loop')
    d.key(kd.KEY_CHAR, 66, 0, 9999)
    micropython.heap_lock()
    try:
        d.poll()                           # a tuple needs the heap
        lost = False
    except MemoryError:
        lost = None
    micropython.heap_unlock()
    check(lost is None and d.poll()[5] == 66, 'the event survived the failed poll')


def glyph_rows(scalar):
    # The KJ8F file the firmware embeds: header 8 B, then (code, 8 rows) x count.
    path = __file__.rsplit('/', 3)[0] + '/micropython/fonts/misaki8.kfnt'
    with open(path, 'rb') as f:
        data = f.read()
    for k in range((len(data) - 8) // 10):
        if data[8 + k * 10] | data[9 + k * 10] << 8 == scalar:
            return data[10 + k * 10:18 + k * 10]
    raise KeyError(scalar)


def pixel(buf, x, y):
    b = buf[y * 160 + x // 2]
    return b >> 4 if x % 2 == 0 else b & 15


def test_japanese_text():
    menus = (('ファイル', ('開く', '-', '閉じる')), ('編集', ('コピー',)), ('表示', ('一覧',)), ('設定', ('色',)))
    d = kd.Desktop(menus=menus)
    w = d.create_window('神楽デスクトップ', 10, 20, 200, 100)
    t = w.text(4, 4, '神楽', 1, 2)
    d.present()
    buf = bytearray(32000)
    d.snapshot(buf)
    wx, wy = w.work()[:2]
    for k, ch in enumerate((0x795E, 0x697D)):   # 神 楽: 8 px apart
        rows = glyph_rows(ch)
        for r in range(8):
            for c in range(8):
                want = 1 if rows[r] & (0x80 >> c) else 2
                check(pixel(buf, wx + 4 + k * 8 + c, wy + 4 + r) == want, (ch, r, c))
    w.set_text(t, '神楽デスクトップ表示')
    w.set_text(t, 'ﾃｽﾄ')                         # shorter: freed cells are redrawn
    w.text(4, 20, 'ファイル名.TXT', 1, -1, 1)     # small font: ASCII 4 px, kana 8 px
    w.set_title('あ' * 20)                        # 60 bytes: cut to 15 whole characters
    d.pointer(kd.POINTER_DOWN, 12, 4, 100)        # ファイル menu
    d.present()
    d.invalidate(0, 0, 320, 200)
    check(d.present() == 0, 'incremental frame equals a full recomposition')
    d.pointer(kd.POINTER_MOVE, 14, 15, 200)
    d.pointer(kd.POINTER_UP, 14, 15, 300)         # 開く
    check(drain(d)[-1] == (kd.MENU, None, 0, 0, 0, 0, 0, 0))


def test_crc_matches_snapshot():
    d = kd.Desktop()
    d.create_window('W', 10, 20, 200, 120).text(4, 4, 'crc')
    d.present()
    buf = bytearray(32000)
    d.snapshot(buf)
    check(binascii.crc32(buf) == d.crc())


def kinds(events, kind):
    return [e for e in events if e[0] == kind]


def test_field_api():
    d = kd.Desktop()
    w = d.create_window('入力', 10, 20, 220, 120)
    f = w.field(8, 8, 150, '神楽')
    check(w.focused() == f and w.get_text(f) == '神楽')
    check(w.selection(f) == (2, 2))             # characters, not bytes
    d.present()
    drain(d)
    for c in 'ab':
        d.key(kd.KEY_CHAR, c)
    check(d.text('デスク') is True)
    check(w.get_text(f) == '神楽abデスク')
    ch = kinds(drain(d), kd.CHANGE)
    check(len(ch) == 3 and all(e[1] == w and e[2] == f for e in ch))
    d.key(kd.KEY_HOME, 0, kd.MOD_SHIFT)
    check(w.selection(f) == (7, 0))
    w.select(f, 1, 3)
    check(w.selection(f) == (1, 3))
    check(w.edit(f, kd.EDIT_CUT) and d.clipboard() == '楽a')
    check(w.get_text(f) == '神bデスク')
    check(w.edit(f, kd.EDIT_PASTE) and w.get_text(f) == '神楽abデスク')
    d.set_clipboard('x\r\ny')
    check(d.clipboard() == 'x\ny')
    check(not w.edit(f, kd.EDIT_PASTE))          # a line break does not fit a field
    check(raises(ValueError, w.select, f, 99))
    check(raises(ValueError, w.select, f, -1))
    check(raises(ValueError, d.text, 'a\nb'))
    check(raises(ValueError, d.text, b'\xe7\xa5'))
    check(d.text(b'\xe7\xa5\x9e') is True)       # bytes are accepted when valid
    w.set_text(f, '')
    check(d.text('x' * (kd.FIELD_BYTES + 1)) is False)  # too long: nothing changes
    check(w.get_text(f) == '')
    check(raises(ValueError, w.set_text, f, 'x' * (kd.FIELD_BYTES + 1)))
    check(raises(ValueError, w.field, 0, 0, 100, 'a\nb'))
    t = w.text(0, 40, 'label')
    check(w.get_text(t) == 'label')
    check(raises(ValueError, w.selection, t))    # not a field
    check(raises(ValueError, w.focus, t))
    check(raises(ValueError, w.focus, 0x1FFFFFF))
    w.focus(None)
    check(w.focused() is None and d.text('z') is False)
    w.focus(f)
    check(d.text('z') is True)


def test_field_buttons_and_tab():
    d = kd.Desktop()
    w = d.create_window('Save As', 10, 20, 220, 120)
    name = w.field(8, 8, 150, 'memo.txt')
    ok = w.button(8, 40, 50, 16, 'OK', kd.BTN_DEFAULT, True)
    cancel = w.button(70, 40, 60, 16, 'Cancel', 0, True)
    plain = w.button(140, 40, 50, 16, 'Info')
    drain(d)
    d.key(kd.KEY_ENTER)                          # Enter in the field: default button
    ev = kinds(drain(d), kd.ACTIVATE)
    check(len(ev) == 1 and ev[0][2] == ok)
    d.key(kd.KEY_TAB)
    d.key(kd.KEY_TAB)
    check(w.focused() == cancel)
    d.key(kd.KEY_CHAR, ' ')
    check([e[2] for e in kinds(drain(d), kd.ACTIVATE)] == [cancel])
    d.key(kd.KEY_TAB, 0, kd.MOD_SHIFT)
    d.key(kd.KEY_TAB, 0, kd.MOD_SHIFT)
    check(w.focused() == name)
    d.key(kd.KEY_ESCAPE)                         # left to the application
    e = drain(d)
    check(len(e) == 1 and e[0][0] == kd.KEY and e[0][4] == kd.KEY_ESCAPE)
    check(plain != w.focused())
    d.present()
    check(d.crc() == d.crc())


def test_field_lifetimes():
    d = kd.Desktop()
    w = d.create_window('A', 10, 20, 200, 100)
    f = w.field(4, 4, 100, 'one')
    w.close()
    check(raises(ValueError, w.get_text, f))
    check(raises(ValueError, w.field, 0, 0, 50))
    check(d.text('x') is False)                  # no window: nothing focused
    # Field slots come back when windows close, over many rounds.
    for r in range(20):
        v = d.create_window('B', 10, 20, 200, 160)
        ids = [v.field(0, i * 14, 80, 'f%d' % i) for i in range(8)]   # KDM_FIELDS
        check(raises(MemoryError, v.field, 0, 0, 80))
        check(v.get_text(ids[-1]) == 'f7')
        v.close()
    v = d.create_window('C', 10, 20, 200, 100)
    g = v.field(0, 0, 80, 'gc')
    gc.collect()
    for i in range(50):
        v.set_text(g, ''.join(['%d' % i, '漢']))
        gc.collect()
    check(v.get_text(g) == '49漢')
    d2 = kd.Desktop()                            # replaces the native state
    check(raises(ValueError, v.get_text, g))
    check(raises(ValueError, d.text, 'x'))
    w2 = d2.create_window('D', 10, 20, 200, 100)
    h = w2.field(0, 0, 80)
    check(w2.get_text(h) == '' and d2.clipboard() == '')


def test_field_heap_locked_typing():
    d = kd.Desktop()
    w = d.create_window('W', 10, 20, 220, 100)
    f = w.field(4, 4, 200)
    mirror = bytearray(32000)
    lst = [None] * 8
    words = ['神', 'a', '楽']
    d.present(mirror)
    drain(d)
    micropython.heap_lock()
    try:
        for i in range(12):
            d.key(kd.KEY_CHAR, 65 + i, 0, 10 * i)
            d.text(words[i % 3])
            if i % 4 == 3:
                d.key(kd.KEY_BACKSPACE, 0, 0, 10 * i + 5)
                d.key(kd.KEY_LEFT, 0, kd.MOD_SHIFT, 10 * i + 6)
            while d.poll_into(lst):
                pass
            d.present(mirror)
        ok = True
    except MemoryError:
        ok = False
    micropython.heap_unlock()
    check(ok, 'typing allocates nothing')
    # 24 typed, 3 backspaces, 2 selections replaced by the next key
    check(len(w.get_text(f)) == 19)


def main():
    global failed, run
    tests = [(k, v) for k, v in globals().items() if k.startswith('test_')]
    tests.sort()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for name, fn in tests:
        if only and only not in name:
            continue
        run += 1
        try:
            fn()
            print('ok   ' + name[5:])
        except Exception as e:  # noqa: BLE001
            failed += 1
            print('FAIL %s: %r' % (name[5:], e))
            sys.print_exception(e)
    print('%d tests, %d failed' % (run, failed))
    sys.exit(1 if failed else 0)


main()
