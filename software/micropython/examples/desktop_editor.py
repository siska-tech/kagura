# SPDX-License-Identifier: Apache-2.0
"""神楽メモ帳: a small UTF-8 text editor on the native desktop.

One document, one window. The text, caret, selection and view live in the
native editor (kagura_desktop, at most DOC_BYTES = 8,191 bytes of UTF-8);
this file is the application: menus, dialogs, files and the status line.

On KAGURA-9 (the HDMI console running, firmware with the editor):
    import desktop_editor; desktop_editor.main()               # your keyboard
    desktop_editor.main(docs=desktop_editor.ram_docs())        # files in RAM only
    desktop_editor.main(script=True, docs=desktop_editor.ram_docs())   # scripted tour
On a PC (unix port with kagura_desktop):
    micropython desktop_editor.py --host DIR [--dump D]        # tour, files in DIR

Keys: arrows, Home/End, PgUp/PgDn, Ctrl+Home/End, Shift selects, Enter,
Backspace/Delete, Ctrl+A, Ctrl+Insert / Shift+Insert / Shift+Delete (copy,
paste, cut), Ctrl+S save, Ctrl+O open, Ctrl+N new; F10 menus, Tab between
dialog controls, Enter for the default button, Esc cancels a dialog.
Ctrl+C stays MicroPython's interrupt: the editor closes, the console returns.

Files: only plain names in one documents folder (default /docs), never a
path, so boot scripts, fonts and other system files cannot be touched.
Saving writes NAME.tmp, closes it, checks its size, then renames it over
NAME. On littlefs (the board's filesystem) a rename replaces the old file in
one metadata commit, so an interrupted save leaves the old file or the new
one; on other filesystems the old file is removed first (documented, not
atomic). A failed save keeps the document in memory and says why. Line
endings (LF or CRLF) and a UTF-8 BOM are kept as the file had them.
"""
import os
import time

import kagura_desktop as kd

MENUS = (('ファイル', ('新規', '開く…', '保存', '名前を付けて保存…', '-', '終了')),
         ('編集', ('切り取り', 'コピー', '貼り付け', '-', 'すべて選択')))
F_NEW, F_OPEN, F_SAVE, F_SAVE_AS, F_QUIT = 0, 1, 2, 3, 5
EDIT = {0: kd.EDIT_CUT, 1: kd.EDIT_COPY, 2: kd.EDIT_PASTE, 4: kd.EDIT_SELECT_ALL}
DOC_DIR = '/docs'
NAME_MAX = 40          # bytes of UTF-8
FREE_MARGIN = 4096     # bytes left free on the filesystem after a save
UNTITLED = '無題'


class DocError(Exception):
    pass


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


class Documents:
    """Plain text files in one folder. Every name is checked: no paths."""
    def __init__(self, folder=DOC_DIR):
        self.folder = folder.rstrip('/') or '/'
        if self.folder == '/':
            raise ValueError('documents need their own folder')

    @staticmethod
    def check_name(name):
        if not name or len(name.encode()) > NAME_MAX:
            raise DocError('名前は1〜%dバイト' % NAME_MAX)
        if name[0] == '.' or name.endswith('.tmp'):
            raise DocError('その名前は使えません')
        for c in name:
            if c in '/\\:*?"<>|' or ord(c) < 32 or ord(c) == 127:
                raise DocError('使えない文字: %r' % c)
        return name

    def path(self, name):
        return self.folder + '/' + self.check_name(name)

    def names(self):
        try:
            items = os.listdir(self.folder)
        except OSError:
            return []
        out = []
        for n in items:
            if n[0] != '.' and not n.endswith('.tmp'):
                try:
                    if os.stat(self.folder + '/' + n)[0] & 0x8000:   # regular file
                        out.append(n)
                except OSError:
                    pass
        out.sort()
        return out

    def exists(self, name):
        return _exists(self.path(name))

    def load(self, name):
        """Returns (text, crlf, bom). The text has LF line ends."""
        path = self.path(name)
        try:
            size = os.stat(path)[6]
        except OSError:
            raise DocError('見つかりません: ' + name)
        if size > 2 * kd.DOC_BYTES + 3:
            raise DocError('大きすぎます (%d B)' % size)
        with open(path, 'rb') as f:
            data = f.read()
        bom = data[:3] == b'\xef\xbb\xbf'
        if bom:
            data = data[3:]
        if b'\x00' in data:
            raise DocError('テキストではありません')
        try:
            text = data.decode('utf-8')
        except UnicodeError:
            raise DocError('UTF-8ではありません')
        crlf = '\r\n' in text
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        if len(text.encode()) > kd.DOC_BYTES:
            raise DocError('%dバイトを超えています' % kd.DOC_BYTES)
        return text, crlf, bom

    def save(self, name, text, crlf=False, bom=False):
        path = self.path(name)
        if crlf:
            text = text.replace('\n', '\r\n')
        data = text.encode()
        if bom:
            data = b'\xef\xbb\xbf' + data
        try:
            os.mkdir(self.folder)
        except OSError:
            pass                                   # it exists (or cannot be made: open fails)
        if hasattr(os, 'statvfs'):
            st = os.statvfs(self.folder)
            free = st[0] * st[4]                   # f_bsize * f_bavail
            if len(data) + FREE_MARGIN > free:
                raise DocError('空き容量が足りません (%d B)' % free)
        tmp = path + '.tmp'
        try:
            with open(tmp, 'wb') as f:
                if f.write(data) != len(data):
                    raise DocError('書き込みが途中で終わりました')
            if os.stat(tmp)[6] != len(data):
                raise DocError('書いた大きさが違います')
            try:
                os.rename(tmp, path)               # littlefs: replaces atomically
            except OSError:
                if not _exists(path):
                    raise
                os.remove(path)                    # filesystems that refuse to replace
                os.rename(tmp, path)
        except DocError:
            self._drop(tmp)
            raise
        except OSError as e:
            self._drop(tmp)
            raise DocError('保存できません (OSError %s)' % (e.args[0] if e.args else '?'))
        return len(data)

    @staticmethod
    def _drop(path):
        try:
            os.remove(path)
        except OSError:
            pass


def ram_docs(mount='/ramdocs', blocks=64, block_size=512):
    """Documents on a littlefs in RAM (32 KB by default): saves never touch
    flash, and everything is gone at reset. For demos and tests on the board."""
    import vfs

    class RAMBlocks:
        def __init__(self):
            self.data = bytearray(blocks * block_size)

        def readblocks(self, n, buf, off=0):
            a = n * block_size + off
            buf[:] = self.data[a:a + len(buf)]

        def writeblocks(self, n, buf, off=None):
            a = n * block_size + (off or 0)
            self.data[a:a + len(buf)] = buf

        def ioctl(self, op, arg):
            if op == 4:
                return blocks
            if op == 5:
                return block_size
            if op == 6:
                return 0
            return None

    try:                      # an earlier RAM disk: free it before making the next
        vfs.umount(mount)
    except OSError:
        pass
    import gc
    gc.collect()
    dev = RAMBlocks()
    vfs.VfsLfs2.mkfs(dev)
    vfs.mount(vfs.VfsLfs2(dev), mount)
    return Documents(mount + '/docs')


class Dialog:
    """A small modal window: fields, buttons, and what each button does."""
    def __init__(self, app, title, w, h):
        self.app = app
        self.win = app.desk.create_window(title, (320 - w) // 2, 40, w, h, closable=False, movable=False)
        self.actions = {}
        self.cancel = None
        self.field = None

    def text(self, x, y, s, color=1):
        return self.win.text(x, y, s, color)

    def button(self, x, y, w, label, action, default=False):
        i = self.win.button(x, y, w, 16, label, kd.BTN_DEFAULT if default else 0, True)
        self.actions[i] = action
        return i

    def close(self):
        if self.win.is_open():
            self.win.close()


class Editor:
    def __init__(self, desk, docs, source='キーボード', frame=(0, 11, 320, 189)):
        self.desk, self.docs = desk, docs
        self.quit = False
        self.name = None
        self.crlf = self.bom = False
        self.dialog = None
        self.status_was = None
        w = self.win = desk.create_window(UNTITLED, *frame, closable=False, movable=False)
        ww, wh = w.work()[2:]
        rows = (wh - 20) // kd.LINE_H                # whole rows, then a status line
        self.ed = w.editor(2, 2, ww - 4, rows * kd.LINE_H + 4)
        # Status: fixed fields, the numbers as ASCII records so that a keystroke
        # redraws only the digit cells that changed, not the whole line.
        sy = rows * kd.LINE_H + 10
        self.n_line = w.text(4, sy, '   1', 1, 2)
        w.text(36, sy, '行', 1, 2)
        self.n_col = w.text(48, sy, '  1', 1, 2)
        w.text(72, sy, '列', 1, 2)
        self.n_size = w.text(88, sy, '   0', 1, 2)
        w.text(120, sy, '/%dB' % kd.DOC_BYTES, 1, 2)
        self.flag = w.text(176, sy, ' ', 6, 2)
        self.source = w.text(ww - 68, rows * kd.LINE_H + 10, source, 5, 2)
        self.saved_version = w.version(self.ed)
        self.refresh()

    # ---- state ----

    def modified(self):
        return self.win.version(self.ed) != self.saved_version

    def refresh(self):
        line, col = self.win.caret(self.ed)
        mod = self.modified()
        state = (line, col, self.win.length(self.ed), mod, self.name)
        if state == self.status_was:
            return
        was = self.status_was or (None, None, None, None, None)
        w = self.win
        if was[3:] != state[3:]:
            w.set_title(('* ' if mod else '') + (self.name or UNTITLED) + ' - 神楽メモ帳')
            w.set_text(self.flag, '変更あり' if mod else ' ')
        if was[0] != line:
            w.set_text(self.n_line, '%4d' % (line + 1))
        if was[1] != col:
            w.set_text(self.n_col, '%3d' % (col + 1))
        if was[2] != state[2]:
            w.set_text(self.n_size, '%4d' % state[2])
        self.status_was = state

    def load_text(self, text, name, crlf=False, bom=False):
        self.win.set_text(self.ed, text)
        self.name, self.crlf, self.bom = name, crlf, bom
        self.saved_version = self.win.version(self.ed)
        self.win.focus(self.ed)

    # ---- dialogs ----

    def open_dialog(self, d):
        if self.dialog is not None:      # replaced by the next step (no flicker to the editor)
            self.dialog.close()
        self.dialog = d
        d.win.activate()

    def close_dialog(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None
        self.win.activate()

    def message(self, text, then=None):
        d = Dialog(self, 'お知らせ', 240, 64)
        d.text(8, 8, text[:28])
        ok = lambda: (self.close_dialog(), then and then())   # noqa: E731
        d.button(92, 28, 56, 'OK', ok, True)
        d.cancel = ok
        self.open_dialog(d)

    def ask_name(self, title, label, initial, action, listing=False):
        n = self.docs.names() if listing else []
        h = 72 + 10 * min(len(n), 5)
        d = Dialog(self, title, 260, h)
        d.text(8, 6, label)
        d.field = d.win.field(8, 18, 242, initial)
        d.win.select(d.field, 0, len(initial))
        for i, name in enumerate(n[:5]):
            d.text(12, 36 + 10 * i, name, 4)
        y = h - 32
        d.button(56, y, 64, '実行' if listing else '保存', lambda: action(d.win.get_text(d.field)), True)
        d.button(140, y, 64, '取消', self.close_dialog)
        d.cancel = self.close_dialog
        self.open_dialog(d)

    def confirm_discard(self, then):
        """Runs then() now, or after the user saved or discarded the changes."""
        if not self.modified():
            then()
            return
        d = Dialog(self, '確認', 260, 64)
        d.text(8, 8, '変更を保存しますか？')
        d.button(8, 28, 76, '保存', lambda: self.save(then), True)
        d.button(92, 28, 76, '破棄', lambda: (self.close_dialog(), then()))
        d.button(176, 28, 76, '取消', self.close_dialog)
        d.cancel = self.close_dialog
        self.open_dialog(d)

    # ---- commands ----

    def new(self):
        self.close_dialog()
        self.load_text('', None)

    def open(self):
        self.confirm_discard(lambda: self.ask_name('開く', 'ファイル名 (' + self.docs.folder + ')',
                                                   self.name or '', self.open_name, listing=True))

    def open_name(self, name):
        try:
            text, crlf, bom = self.docs.load(name)
        except DocError as e:
            self.message(str(e))
            return
        self.close_dialog()
        self.load_text(text, name, crlf, bom)

    def save(self, then=None):
        if self.name is None:
            self.save_as(then)
            return
        self.write(self.name, then)

    def save_as(self, then=None):
        self.ask_name('名前を付けて保存', 'ファイル名 (' + self.docs.folder + ')', self.name or 'メモ.txt',
                      lambda name: self.save_name(name, then))

    def save_name(self, name, then=None):
        try:
            exists = name != self.name and self.docs.exists(name)
        except DocError as e:
            self.message(str(e))
            return
        if exists:
            d = Dialog(self, '確認', 260, 64)
            d.text(8, 8, '上書きしますか？ ' + name[:12])
            d.button(40, 28, 80, '上書き', lambda: self.write(name, then), True)
            d.button(140, 28, 80, '取消', self.close_dialog)
            d.cancel = self.close_dialog
            self.open_dialog(d)
        else:
            self.write(name, then)

    def write(self, name, then=None):
        version = self.win.version(self.ed)
        try:
            self.docs.save(name, self.win.get_text(self.ed), self.crlf, self.bom)
        except DocError as e:
            self.message('保存失敗: ' + str(e))   # the document stays as it is
            return
        self.name, self.saved_version = name, version
        self.close_dialog()
        if then:
            then()

    def request_quit(self):
        self.confirm_discard(self.do_quit)

    def do_quit(self):
        self.close_dialog()
        self.quit = True

    def menu(self, m, item):
        if m == 0:
            if self.dialog is not None:
                return
            {F_NEW: lambda: self.confirm_discard(self.new), F_OPEN: self.open, F_SAVE: self.save,
             F_SAVE_AS: self.save_as, F_QUIT: self.request_quit}.get(item, lambda: None)()
        elif m == 1 and item in EDIT:
            w = self.desk.top()
            f = w.focused() if w is not None else None
            if f is not None:
                try:
                    w.edit(f, EDIT[item])
                except ValueError:                  # a button has the focus
                    pass

    # ---- events ----

    def handle(self):
        while True:
            ev = self.desk.poll()
            if ev is None:
                break
            kind, win = ev[0], ev[1]
            d = self.dialog
            if kind == kd.MENU:
                self.menu(ev[4], ev[5])
            elif kind == kd.ACTIVATE and d is not None and win == d.win:
                d.actions[ev[2]]()
            elif kind == kd.KEY and d is not None and win == d.win and ev[4] == kd.KEY_ESCAPE:
                d.cancel()
            elif kind == kd.KEY and win == self.win and ev[6] == kd.MOD_CTRL and ev[4] == kd.KEY_CHAR:
                ch = chr(ev[5])
                if ch in 'sS':
                    self.save()
                elif ch in 'oO':
                    self.open()
                elif ch in 'nN':
                    self.confirm_discard(self.new)
        self.refresh()


def sleep_ms(ms):
    if ms > 0:
        if hasattr(time, 'sleep_ms'):
            time.sleep_ms(ms)
        else:
            time.sleep(ms / 1000)


def keyboard(app, source=None, idle_ms=5):
    from kagura.keyinput import StdinSource, TerminalKeys
    keys = TerminalKeys(app.desk)
    src = source if source is not None else StdinSource()
    try:
        while not app.quit:
            n = 0
            while n < 64 and not app.quit:   # one key at a time: the app sees each in order
                got = src.pump(keys, 64 - n, True)
                if not got:
                    break
                n += got
                app.handle()
            app.handle()                     # a lone Escape, decoded on time-out
            app.desk.present()               # one frame for the whole batch
            if not n:
                sleep_ms(idle_ms)
    finally:
        if source is None:
            src.close()


TOUR_TEXT = ('神楽メモ帳へようこそ。\n'
             'これはKAGURA-9の日本語エディタです。\n'
             '\n'
             '・矢印キーで移動\n'
             '・Shiftで選択\n'
             '・Ctrl+Sで保存\n')


def tour(app, step, key_ms=0, step_ms=0):
    d = app.desk

    def k(code, ch=0, mods=0):
        d.key(code, ch, mods)
        app.handle()
        d.present()
        sleep_ms(key_ms)

    def typ(s):
        for c in s:
            if c == '\n':
                k(kd.KEY_ENTER)
            elif ord(c) < 128:
                k(kd.KEY_CHAR, c)
            else:
                d.text(c)
                app.handle()
                d.present()
                sleep_ms(key_ms)

    def scene(name):
        app.handle()
        step(name)
        sleep_ms(step_ms)

    scene('empty')
    typ(TOUR_TEXT)
    scene('typed')
    for _ in range(5):                      # up to line 2 (the caret is on the empty line 7)
        k(kd.KEY_UP)
    k(kd.KEY_END)
    k(kd.KEY_LEFT, 0, kd.MOD_SHIFT)
    k(kd.KEY_LEFT, 0, kd.MOD_SHIFT)
    k(kd.KEY_LEFT, 0, kd.MOD_SHIFT)
    scene('selected')
    typ('（試作版）です。')
    scene('replaced')
    for i in range(16):                     # more lines than the window shows
        typ('\n%02d 行目のテキスト' % (i + 1))
    scene('scrolled')
    k(kd.KEY_PGUP)
    k(kd.KEY_HOME, 0, kd.MOD_CTRL)
    scene('top')
    k(kd.KEY_CHAR, 's', kd.MOD_CTRL)        # untitled: Save As
    scene('save-as')
    for _ in range(6):
        k(kd.KEY_BACKSPACE)
    typ('demo.txt')
    k(kd.KEY_ENTER)
    scene('saved')
    k(kd.KEY_F10)                           # ファイル > 新規 (saved: no question)
    k(kd.KEY_ENTER)
    scene('new')
    typ('一時的なメモ')
    k(kd.KEY_CHAR, 'o', kd.MOD_CTRL)        # changed: asks first
    scene('ask-discard')
    k(kd.KEY_TAB)
    k(kd.KEY_ENTER)                         # 破棄
    scene('open')
    typ('demo.txt')
    k(kd.KEY_ENTER)
    scene('reopened')


def main(script=False, desk=None, docs=None, out=print, key_ms=None, step_ms=None, dump=None):
    own = desk is None
    if own:
        from kagura.desktop import Desktop
        desk = Desktop(menus=MENUS, cursor=False)
    if key_ms is None:
        key_ms = 60 if own else 0
    if step_ms is None:
        step_ms = 1000 if own else 0
    app = Editor(desk, docs or Documents(), 'スクリプト' if script else 'キーボード')
    scenes = [0]

    def step(name):
        import binascii
        scenes[0] += 1
        tiles = desk.present()
        mirror = getattr(desk, 'mirror', None)
        out('SCENE %d %s %08x %d%s' % (scenes[0], name, desk.crc(), tiles,
                                       ' tile4 %08x' % binascii.crc32(mirror) if mirror else ''))
        if dump:   # host only: raw 4bpp snapshots for reference pictures
            buf = bytearray(32000)
            desk.snapshot(buf)
            with open('%s/%02d-%s.raw' % (dump, scenes[0], name), 'wb') as f:
                f.write(buf)

    try:
        desk.present()
        if script:
            tour(app, step, key_ms, step_ms)
        else:
            keyboard(app)
    finally:
        if own:
            desk.close()
    return app


class HostDesktop:
    """kagura_desktop.Desktop with present() into a TILE4 mirror (no hardware)."""
    def __init__(self, menus):
        self._kd = kd.Desktop(320, 200, menus=menus, cursor=False)
        self.mirror = bytearray(32000)

    def present(self):
        return self._kd.present(self.mirror)

    def __getattr__(self, name):
        return getattr(self._kd, name)


if __name__ == '__main__':
    import sys
    if '--host' in sys.argv:
        folder = sys.argv[sys.argv.index('--host') + 1]
        dump = sys.argv[sys.argv.index('--dump') + 1] if '--dump' in sys.argv else None
        main(script=True, desk=HostDesktop(MENUS), docs=Documents(folder), dump=dump)
    else:
        main()
