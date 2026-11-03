# SPDX-License-Identifier: Apache-2.0
"""神楽デスクトップ, keyboard only: menus, windows, fields and Japanese text.

Everything happens through key events and UTF-8 text input, as from a
keyboard; nothing uses the pointer. The scripted tour is deterministic and
non-destructive (it writes no files), so its scenes can be compared between
the host and the board, and filmed:

On KAGURA-9 (the HDMI console running, firmware with kagura_desktop):
    import desktop_keys; desktop_keys.main()                 # scripted tour
    desktop_keys.main(key_ms=120, step_ms=1500)              # slower, for video
    desktop_keys.main(script=False)                          # your keyboard (terminal)
On a PC (unix port with kagura_desktop), without hardware:
    micropython desktop_keys.py --host [--dump DIR]          # a CRC (and snapshot) per scene

The window says where the input comes from: スクリプト for the tour,
キーボード for a real keyboard (a terminal on USB or the console UART; see
kagura/keyinput.py). ファイル > 終了 ends the keyboard session; Ctrl+C
interrupts it, and the console comes back either way.

Keys: F10 menus (arrows, Enter, Esc), F6 next window, Ctrl+W close, Tab and
Shift+Tab move between fields and buttons, Enter presses the default
button, Ctrl+Insert / Shift+Insert / Shift+Delete copy, paste and cut (the
編集 menu does the same; Ctrl+C stays the MicroPython interrupt).
"""
import binascii
import time

import kagura_desktop as kd

MENUS = (('ファイル', ('新しいメモ', '情報…', '-', '終了')),
         ('編集', ('切り取り', 'コピー', '貼り付け', '-', 'すべて選択')),
         ('ウィンドウ', ('次のウィンドウ', '閉じる')))
M_FILE, M_EDIT, M_WINDOW = 0, 1, 2
EDIT_COMMANDS = {0: kd.EDIT_CUT, 1: kd.EDIT_COPY, 2: kd.EDIT_PASTE, 4: kd.EDIT_SELECT_ALL}
SOURCE = {'script': 'スクリプト', 'keyboard': 'キーボード'}


def sleep_ms(ms):
    if ms > 0:
        if hasattr(time, 'sleep_ms'):
            time.sleep_ms(ms)
        else:
            time.sleep(ms / 1000)


class App:
    def __init__(self, desk, source='script'):
        self.desk = desk
        self.quit = False
        self.about = None
        self.saved = None
        m = self.memo = desk.create_window('メモ帳', 6, 16, 206, 104)
        m.fill_rect(0, 0, 204, 12, 12)
        m.text(4, 2, '入力: ' + SOURCE[source], 1)
        m.text(4, 18, '件名', 1)
        self.subject = m.field(40, 16, 156)
        m.text(4, 36, '本文', 1)
        self.body = m.field(40, 34, 156)
        m.text(4, 54, '短い', 1)
        self.short = m.field(40, 52, 60, '', 1)      # narrow: long text scrolls
        self.count = m.text(4, 72, '0文字', 5, 2)
        self.status = m.text(4, 84, '状態: 起動', 8, 2)
        d = self.dialog = desk.create_window('名前を付けて保存', 110, 104, 200, 72, closable=False)
        d.text(6, 6, 'ファイル名', 1)
        self.name = d.field(6, 18, 186, 'メモ.TXT')
        self.ok = d.button(36, 38, 56, 16, '保存', kd.BTN_DEFAULT, True)
        self.cancel = d.button(104, 38, 56, 16, '取消', 0, True)
        self.memo.activate()

    def set_status(self, text):
        self.memo.set_text(self.status, '状態: ' + text)

    def focused_field(self):
        w = self.desk.top()
        f = w.focused() if w is not None else None
        if f is None:
            return None, None
        try:
            w.selection(f)
            return w, f
        except ValueError:          # a button
            return None, None

    def handle(self):
        while True:
            ev = self.desk.poll()
            if ev is None:
                return
            kind, win, a = ev[0], ev[1], ev[2]
            if kind == kd.MENU:
                self.menu(ev[4], ev[5])
            elif kind == kd.CHANGE and win == self.memo:
                n = sum(len(self.memo.get_text(f)) for f in (self.subject, self.body, self.short))
                self.memo.set_text(self.count, '%d文字' % n)
            elif kind == kd.ACTIVATE and win == self.dialog:
                if a == self.ok:
                    self.saved = self.dialog.get_text(self.name)
                    self.set_status('保存(仮) ' + self.saved)   # the demo writes nothing
                else:
                    self.set_status('取消')
                self.memo.activate()
            elif kind == kd.KEY and ev[4] == kd.KEY_ESCAPE and win is not None and win == self.about:
                self.about.close()
                self.about = None

    def menu(self, m, item):
        if m == M_FILE:
            if item == 0:
                for f in (self.subject, self.body, self.short):
                    self.memo.set_text(f, '')
                self.memo.set_text(self.count, '0文字')
                self.set_status('新しいメモ')
                self.memo.activate()
            elif item == 1:
                self.open_about()
            elif item == 3:
                self.quit = True
        elif m == M_EDIT and item in EDIT_COMMANDS:
            w, f = self.focused_field()
            if f is not None:
                w.edit(f, EDIT_COMMANDS[item])
        elif m == M_WINDOW:
            self.desk.key(kd.KEY_F6 if item == 0 else kd.KEY_CHAR, 'w' if item else 0,
                          kd.MOD_CTRL if item else 0)

    def open_about(self):
        if self.about is not None and self.about.is_open():
            self.about.activate()
            return
        a = self.about = self.desk.create_window('情報', 60, 50, 180, 60)
        a.text(8, 8, '神楽-9 キーボード操作', 1)
        a.text(8, 22, 'C言語の編集エンジン', 1)
        a.text(8, 38, 'Escで閉じる', 4)


class Driver:
    """Scripted keyboard: every key goes through the desktop like a real one,
    then the application runs and the frame is presented. Pacing is only for
    watching; it does not change any frame."""
    def __init__(self, app, step, key_ms=0, step_ms=0):
        self.app, self.step, self.key_ms, self.step_ms = app, step, key_ms, step_ms

    def frame(self):
        self.app.handle()
        self.app.desk.present()
        sleep_ms(self.key_ms)

    def key(self, k, ch=0, mods=0):
        self.app.desk.key(k, ch, mods)
        self.frame()

    def type(self, s):
        for c in s:
            if ord(c) < 128:
                self.app.desk.key(kd.KEY_CHAR, c)
            else:
                self.app.desk.text(c)        # as committed by an input method
            self.frame()

    def scene(self, name):
        self.app.handle()
        self.step(name)
        sleep_ms(self.step_ms)


def tour(drv):
    k = drv.key
    drv.scene('start')
    k(kd.KEY_F10)                                    # ファイル menu
    drv.scene('menu-file')
    k(kd.KEY_RIGHT)                                  # 編集 menu
    drv.scene('menu-edit')
    k(kd.KEY_ESCAPE)
    drv.type('Hello, ')
    drv.type('神楽デスクトップ')
    drv.scene('typed')
    k(kd.KEY_HOME, 0, kd.MOD_SHIFT)                  # select the subject
    drv.scene('selected')
    k(kd.KEY_INSERT, 0, kd.MOD_CTRL)                 # copy
    k(kd.KEY_TAB)                                    # to 本文
    k(kd.KEY_INSERT, 0, kd.MOD_SHIFT)                # paste
    drv.type('を日本語で編集')
    k(kd.KEY_LEFT, 0, kd.MOD_SHIFT)                  # select 編集 and type over it
    k(kd.KEY_LEFT, 0, kd.MOD_SHIFT)
    drv.type('入力')
    drv.scene('pasted')
    k(kd.KEY_TAB)                                    # to the narrow field
    drv.type('長い文章は横にスクロールします')
    drv.scene('scrolled')
    k(kd.KEY_HOME)
    drv.scene('scrolled-home')
    k(kd.KEY_F10)                                    # ファイル > 情報… by keys
    k(kd.KEY_DOWN)
    k(kd.KEY_ENTER)
    drv.scene('about')
    k(kd.KEY_ESCAPE)                                 # the application closes it
    drv.scene('about-closed')
    k(kd.KEY_F6)                                     # to the dialog
    drv.scene('dialog')
    k(kd.KEY_HOME, 0, kd.MOD_SHIFT)                  # select the whole name, type a new one
    drv.type('日記.TXT')
    k(kd.KEY_TAB)                                    # to 保存
    drv.scene('dialog-ok-focused')
    k(kd.KEY_ENTER)                                  # ACTIVATE 保存: memo comes back
    drv.scene('saved')
    k(kd.KEY_TAB, 0, kd.MOD_SHIFT)                   # back from 短い to 本文
    k(kd.KEY_F10)                                    # 編集 > すべて選択, then 切り取り
    k(kd.KEY_RIGHT)
    for _ in range(3):
        k(kd.KEY_DOWN)
    k(kd.KEY_ENTER)
    k(kd.KEY_F10)
    k(kd.KEY_RIGHT)
    k(kd.KEY_ENTER)
    drv.scene('cut-by-menu')


def keyboard(app, step, source=None, idle_ms=5):
    """Real keyboard: terminal bytes from stdin until ファイル > 終了."""
    from kagura.keyinput import StdinSource, TerminalKeys
    keys = TerminalKeys(app.desk)
    src = source if source is not None else StdinSource()
    step('keyboard')
    try:
        while not app.quit:
            n = src.pump(keys)
            app.handle()
            app.desk.present()
            if not n:
                sleep_ms(idle_ms)
    finally:
        if source is None:
            src.close()
    return keys


def main(script=True, desk=None, out=print, key_ms=None, step_ms=None, source=None, dump=None):
    own = desk is None
    if own:
        from kagura.desktop import Desktop
        desk = Desktop(menus=MENUS, cursor=False)   # keyboard only: no pointer
    # On the board the tour is paced to be watchable; the host runs at full speed.
    if key_ms is None:
        key_ms = 0 if not own else 80
    if step_ms is None:
        step_ms = 0 if not own else 1000
    app = App(desk, source or ('script' if script else 'keyboard'))
    scenes = [0]

    def step(name):
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
        if script:
            tour(Driver(app, step, key_ms, step_ms))
        else:
            keyboard(app, step)
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
        dump = sys.argv[sys.argv.index('--dump') + 1] if '--dump' in sys.argv else None
        main(desk=HostDesktop(MENUS), dump=dump)
    else:
        main()
