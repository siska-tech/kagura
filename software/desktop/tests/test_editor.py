# SPDX-License-Identifier: Apache-2.0
"""Tests of examples/desktop_editor.py (神楽メモ帳) on the unix port.

Files go to a fresh folder under /tmp. Covers the editor binding, the
Documents layer (names, round trips, CRLF/BOM, rejections, failed saves),
the unsaved-change flows, and a keyboard session from terminal bytes.

  MICROPYPATH=software/micropython micropython tests/test_editor.py
"""
import os
import sys

import kagura_desktop as kd

sys.path.append(sys.path[0] + '/../../micropython/examples')
import desktop_editor as de                                  # noqa: E402
from kagura.keyinput import StdinSource, TerminalKeys        # noqa: E402

failed = 0
run = 0
ROOT = '/tmp/kagura-editor-test'


def check(cond, what=''):
    if not cond:
        raise AssertionError(what)


def raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return True
    return False


def rmtree(path):
    try:
        names = os.listdir(path)
    except OSError:
        return
    for n in names:
        p = path + '/' + n
        if os.stat(p)[0] & 0x4000:
            rmtree(p)
        else:
            os.remove(p)
    os.rmdir(path)


def fresh(name):
    rmtree(ROOT + '/' + name)
    try:
        os.mkdir(ROOT)
    except OSError:
        pass
    return de.Documents(ROOT + '/' + name)


def app(docs):
    return de.Editor(de.HostDesktop(de.MENUS), docs)


def test_editor_binding():
    d = kd.Desktop()
    w = d.create_window('E', 0, 11, 320, 189)
    e = w.editor(2, 2, 300, 104, 'a\r\nb')
    check(w.get_text(e) == 'a\nb' and w.caret(e) == (0, 0) and w.length(e) == 3)
    v = w.version(e)
    d.key(kd.KEY_END, 0, kd.MOD_CTRL)
    check(w.caret(e) == (1, 1) and w.version(e) == v)      # motions do not change the version
    d.key(kd.KEY_ENTER)
    d.text('神楽')
    check(w.get_text(e) == 'a\nb\n神楽' and w.caret(e) == (2, 2) and w.version(e) != v)
    d.key(kd.KEY_PGUP)
    check(w.caret(e)[0] == 0)
    check(raises(MemoryError, w.editor, 0, 0, 100, 40))     # one editor per desktop
    check(raises(ValueError, w.set_text, e, 'x' * (kd.DOC_BYTES + 1)))
    w.set_text(e, 'x' * kd.DOC_BYTES)
    check(w.length(e) == kd.DOC_BYTES and d.text('y') is False)
    w.close()
    check(raises(ValueError, w.caret, e))
    w2 = d.create_window('F', 0, 11, 320, 189)
    w2.editor(2, 2, 300, 104)                                # the slot came back
    d.close()


def test_names():
    docs = fresh('names')
    for bad in ('', '.hidden', 'a/b', '../x', 'x.tmp', 'a:b', 'tab\tname', 'あ' * 14):
        check(raises(de.DocError, docs.path, bad), bad)
    check(docs.path('メモ.txt') == ROOT + '/names/メモ.txt')
    check(raises(ValueError, de.Documents, '/'))


def test_round_trips():
    docs = fresh('trips')
    check(docs.names() == [])
    text = '一行目\n二行目 ascii\n\n😀 end'
    docs.save('lf.txt', text)
    check(docs.load('lf.txt') == (text, False, False))
    docs.save('crlf.txt', text, crlf=True, bom=True)
    with open(ROOT + '/trips/crlf.txt', 'rb') as f:
        raw = f.read()
    check(raw.startswith(b'\xef\xbb\xbf') and raw.count(b'\r\n') == 3, raw)
    check(docs.load('crlf.txt') == (text, True, True))
    check(docs.names() == ['crlf.txt', 'lf.txt'])
    docs.save('lf.txt', 'replaced')                          # over an existing file
    check(docs.load('lf.txt')[0] == 'replaced')
    check(not any(n.endswith('.tmp') for n in os.listdir(ROOT + '/trips')))


def test_rejected_files():
    docs = fresh('bad')
    os.mkdir(ROOT + '/bad')
    for name, data in (('bin.dat', b'ab\x00cd'), ('latin1.txt', b'caf\xe9'),
                       ('big.txt', b'x' * (kd.DOC_BYTES + 1))):
        with open(ROOT + '/bad/' + name, 'wb') as f:
            f.write(data)
        check(raises(de.DocError, docs.load, name), name)
    check(raises(de.DocError, docs.load, 'missing.txt'))
    # CRLF that only fits once normalized is accepted.
    with open(ROOT + '/bad/crlf.txt', 'wb') as f:
        f.write(b'a\r\n' * (kd.DOC_BYTES // 2))
    check(len(docs.load('crlf.txt')[0]) == kd.DOC_BYTES // 2 * 2)


def test_failed_save_keeps_document():
    docs = fresh('fail')
    with open(ROOT + '/fail', 'w') as f:                     # the folder is a file: nothing can be written
        f.write('x')
    a = app(docs)
    a.desk.text('大事な文章')
    a.handle()
    a.save()                                                 # untitled: Save As
    a.handle()
    a.desk.key(kd.KEY_ENTER)                                 # 保存 with the default name
    a.handle()
    check(a.dialog is not None and a.dialog.win.is_open())  # the error message
    check(a.win.get_text(a.ed) == '大事な文章' and a.modified() and a.name is None)
    a.desk.key(kd.KEY_ENTER)                                 # OK
    a.handle()
    check(a.dialog is None)
    os.remove(ROOT + '/fail')
    a.desk.close()


def keys_for(a, *steps):
    for s in steps:
        if isinstance(s, str):
            for c in s:
                if ord(c) < 128:
                    a.desk.key(kd.KEY_CHAR, c)
                else:
                    a.desk.text(c)
        else:
            a.desk.key(*s)
        a.handle()


def test_unsaved_changes():
    docs = fresh('unsaved')
    docs.save('old.txt', 'old')
    a = app(docs)
    keys_for(a, 'changed')
    check(a.modified())
    keys_for(a, (kd.KEY_CHAR, 'n', kd.MOD_CTRL))             # New: asks
    check(a.dialog is not None)
    keys_for(a, (kd.KEY_ESCAPE,))                            # 取消: nothing lost
    check(a.dialog is None and a.win.get_text(a.ed) == 'changed')
    keys_for(a, (kd.KEY_CHAR, 'o', kd.MOD_CTRL), (kd.KEY_TAB,), (kd.KEY_ENTER,))   # 破棄, then 開く
    check(a.dialog is not None and a.win.get_text(a.ed) == 'changed')
    keys_for(a, 'old.txt', (kd.KEY_ENTER,))
    check(a.win.get_text(a.ed) == 'old' and a.name == 'old.txt' and not a.modified())
    keys_for(a, (kd.KEY_END, 0, kd.MOD_CTRL), ' and new')
    a.request_quit()                                         # 保存, then quit
    a.handle()
    keys_for(a, (kd.KEY_ENTER,))
    check(a.quit and docs.load('old.txt')[0] == 'old and new')
    a.desk.close()


def test_overwrite_question():
    docs = fresh('over')
    docs.save('a.txt', 'A')
    a = app(docs)
    keys_for(a, 'B', (kd.KEY_CHAR, 's', kd.MOD_CTRL))       # Save As
    keys_for(a, 'a.txt', (kd.KEY_ENTER,))                    # exists: asks
    check(a.dialog is not None and docs.load('a.txt')[0] == 'A')
    keys_for(a, (kd.KEY_TAB,), (kd.KEY_ENTER,))              # 取消
    check(a.dialog is None and a.modified())
    keys_for(a, (kd.KEY_CHAR, 's', kd.MOD_CTRL), 'a.txt', (kd.KEY_ENTER,), (kd.KEY_ENTER,))   # 上書き
    check(docs.load('a.txt')[0] == 'B' and not a.modified())
    a.desk.close()


class Bytes:
    def __init__(self, data):
        self.data, self.pos = data, 0

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


def test_keyboard_session():
    docs = fresh('session')
    a = app(docs)
    data = b''.join([
        '日本語の文章\r'.encode(), b'second line\r',
        b'\x1b[A\x1b[A\x1b[F',                               # Up, Up, End (of the first line)
        b'\x1b[1;2D\x1b[1;2D',                               # Shift+Left x2: select 文章
        b'\x1b[2;5~',                                        # Ctrl+Insert: copy
        b'\x1b[1;5F\r\x1b[2;2~',                            # Ctrl+End, Enter, Shift+Insert
        b'\x13',                                             # Ctrl+S: Save As
        b'\x7f' * 8, 'セッション.txt'.encode(), b'\r',
        b'\x1b[21~\x1b[B\x1b[B\x1b[B\x1b[B\r',              # F10 > 終了 (saved: no question)
    ])
    b = Bytes(data)
    de.keyboard(a, StdinSource(stream=b, poller=b), idle_ms=0)
    want = '日本語の文章\nsecond line\n\n文章'   # the text ended in a line break; Enter added one
    check(a.quit and a.win.get_text(a.ed) == want, a.win.get_text(a.ed))
    check(docs.load('セッション.txt') == (want, False, False))
    a.desk.close()


def test_tour_reopens_identically():
    docs = fresh('tour')
    lines = []
    de.main(script=True, desk=de.HostDesktop(de.MENUS), docs=docs, out=lines.append)
    crc = {ln.split()[2]: ln.split()[3] for ln in lines}
    check(crc['saved'] == crc['reopened'] and crc['new'] == crc['empty'], lines)
    check(docs.names() == ['demo.txt'])


def test_skk_in_the_editor():
    import desktop_skk as ds
    lines = []
    text = ds.main(desk=de.HostDesktop(de.MENUS), out=lines.append)
    check(text == ds.FINAL_TEXT, text)
    check(lines[-1].startswith('TEXT ok'), lines[-1])
    scenes = {l.split()[2]: l.split()[3] for l in lines if l.startswith('SCENE')}
    check(len(scenes) == 22, lines)
    check(scenes['closed'] == scenes['final'])           # the popup and the corner window leave no trace
    # Same script, same frames: the input path is deterministic.
    again = []
    ds.main(desk=de.HostDesktop(de.MENUS), out=again.append)
    check(again == lines)


def test_skk_dialog_and_menus():
    from kagura import skk
    from kagura.keyinput import TerminalKeys
    docs = fresh('skkdlg')
    a = de.Editor(de.HostDesktop(de.MENUS), docs, ime=skk.SkkEngine(skk.test_dictionary(), style=skk.MODERN))
    keys = de.input_chain(a)
    def feed(data):
        for b in data:
            keys.feed(bytes((b,)))
            a.handle()
    feed(b'\nKanji ')                                # かな mode, ▼漢字
    feed(b'\x13')                                    # Ctrl+S commits, then Save As opens
    check(a.dialog is not None and a.win.get_text(a.ed) == '漢字', a.win.get_text(a.ed))
    feed(b'\x7f' * 8 + b'Memo \r')                   # the dialog's field gets SKK too: ▼メモ, Enter
    check(a.dialog.win.get_text(a.dialog.field) == 'メモ', a.dialog.win.get_text(a.dialog.field))
    feed(b'l.txt\r')                                 # l: ASCII; Enter: 保存
    check(a.dialog is None and docs.load('メモ.txt')[0] == '漢字', docs.names())
    feed(b'\x1b[21~')                                # F10: menus take the arrows, not SKK
    feed(b'\x1b[C\x1b[B\r')                          # 編集 > コピー (nothing selected)
    check(a.win.get_text(a.ed) == '漢字')
    a.desk.close()


def main():
    global failed, run
    only = sys.argv[1] if len(sys.argv) > 1 else None
    tests = sorted((k, v) for k, v in globals().items() if k.startswith("test_") and (not only or only in k))
    for name, fn in tests:
        run += 1
        try:
            fn()
            print('ok   ' + name[5:])
        except Exception as e:  # noqa: BLE001
            failed += 1
            print('FAIL %s: %r' % (name[5:], e))
            sys.print_exception(e)
    rmtree(ROOT)
    print('%d tests, %d failed' % (run, failed))
    sys.exit(1 if failed else 0)


main()
