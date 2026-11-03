# SPDX-License-Identifier: Apache-2.0
"""神楽-9 showcase: a paced, filmable tour of the native desktop and editor.

Made for a video of the HDMI output: one subject at a time, no cascade of
overlapping windows, a caption band at the bottom that says what happens,
and only the 8x8 font (black on white or cream). The input is scripted and
says so on screen (入力: スクリプト); for real typing use desktop_editor.

Chapters: title -> menus by keyboard -> Japanese editing -> save and reopen
(on a RAM disk: nothing is written to flash) -> two windows side by side,
switched with F6 -> end card.

On KAGURA-9 (the HDMI console running, firmware with the editor):
    import desktop_showcase; desktop_showcase.main()                  # about 2 minutes
    desktop_showcase.main(pace=1.5)                                  # slower
On a PC (unix port):
    micropython desktop_showcase.py --host DIR [--dump D]           # a CRC per scene

Every scene prints `SCENE <n> <name> <framebuffer crc32>`; the same
sequence on the host and the board must give the same CRCs. Pacing changes
only the timing, never a frame.
"""
import time

import kagura_desktop as kd

import desktop_editor as de

MENUS = de.MENUS
CAPTION = (0, 166, 320, 34)          # caption band: frame below everything else
STAGE = (0, 11, 320, 154)            # where the subject of a chapter goes


def sleep_ms(ms):
    if ms > 0:
        if hasattr(time, 'sleep_ms'):
            time.sleep_ms(int(ms))
        else:
            time.sleep(ms / 1000)


class Show:
    def __init__(self, desk, docs, step, pace=1.0, key_ms=90, hold_ms=1800):
        self.desk, self.docs, self.step = desk, docs, step
        self.key_ms, self.hold_ms = key_ms * pace, hold_ms * pace
        c = self.cap = desk.create_window('', *CAPTION, closable=False, movable=False)
        c.fill_rect(0, 0, 318, 21, 15)
        self.line1 = c.text(6, 2, '', 1)
        self.line2 = c.text(6, 12, '', 4)
        c.text(250, 12, '入力:スクリプト', 5)
        self.editor = None

    # ---- pacing ----

    def frame(self, ms=None):
        if self.editor is not None:
            self.editor.handle()
        self.desk.present()
        sleep_ms(self.key_ms if ms is None else ms)

    def key(self, code, ch=0, mods=0):
        self.desk.key(code, ch, mods)
        self.frame()

    def type(self, s):
        for c in s:
            if c == '\n':
                self.desk.key(kd.KEY_ENTER)
            elif ord(c) < 128:
                self.desk.key(kd.KEY_CHAR, c)
            else:
                self.desk.text(c)
            self.frame()

    def scene(self, name, hold=1.0):
        if self.editor is not None:
            self.editor.handle()
        self.step(name)
        sleep_ms(self.hold_ms * hold)

    def caption(self, first, second=''):
        self.cap.set_text(self.line1, first)
        self.cap.set_text(self.line2, second)

    def card(self, name, title, subtitle):
        """A centred title card over an empty stage."""
        w = self.desk.create_window('', 40, 50, 240, 70, closable=False, movable=False)
        w.fill_rect(0, 0, 238, 57, 15)
        w.text((238 - 8 * len(title)) // 2, 16, title, 1)
        w.text((238 - 8 * len(subtitle)) // 2, 34, subtitle, 4)
        self.scene(name, 1.4)
        w.close()


def chapters(s):
    d = s.desk
    s.caption('神楽-9 日本語デスクトップ', 'RP2040 + Tang Nano 9K / HDMI')
    s.card('title', '神楽-9', 'キーボードで動く日本語環境')

    # 1. Menus by keyboard: an empty stage, only the menu bar moves.
    s.caption('F10でメニュー、矢印で移動', 'マウスは使いません')
    s.scene('menus-intro', 0.6)
    s.key(kd.KEY_F10)
    s.scene('menu-file', 0.7)
    s.key(kd.KEY_DOWN)
    s.key(kd.KEY_DOWN)
    s.key(kd.KEY_RIGHT)
    s.scene('menu-edit', 0.7)
    s.key(kd.KEY_ESCAPE)

    # 2. The editor fills the stage.
    s.caption('日本語を入力しています', '文字コードはUTF-8')
    s.card('card-editor', '日本語エディタ', 'UTF-8 / 8191バイト')
    e = s.editor = de.Editor(d, s.docs, 'スクリプト', STAGE)
    s.frame(0)
    s.type('神楽メモ帳で日本語を書きます。\n')
    s.type('漢字、ひらがな、カタカナ、ASCIIも\n同じ画面で編集できます。\n')
    s.scene('typed')
    s.caption('Shift+矢印で選択して置き換え', '上下の移動は表示の桁を保ちます')
    s.key(kd.KEY_UP)
    s.key(kd.KEY_UP)
    s.key(kd.KEY_END)
    for _ in range(6):                                   # select 'ASCIIも'
        s.key(kd.KEY_LEFT, 0, kd.MOD_SHIFT)
    s.scene('selected', 0.8)
    s.type('英数字も')
    s.scene('replaced', 0.8)
    s.caption('長い文書は上下にスクロール', 'PgUp / PgDn / Ctrl+Home')
    s.key(kd.KEY_END, 0, kd.MOD_CTRL)
    for i in range(14):
        s.type('%02d: 神楽-9 は RP2040 と FPGA の小さなコンピュータ\n' % (i + 1))
    s.scene('scrolled')
    s.key(kd.KEY_PGUP)
    s.key(kd.KEY_HOME, 0, kd.MOD_CTRL)
    s.scene('top', 0.8)

    # 3. Save and reopen: one dialog, centred over the editor.
    s.caption('Ctrl+Sで保存（RAMディスク）', '書き込み先は一時ファイル→名前変更')
    s.key(kd.KEY_CHAR, 's', kd.MOD_CTRL)
    for _ in range(6):
        s.key(kd.KEY_BACKSPACE)
    s.type('神楽.txt')
    s.scene('save-as', 0.8)
    s.key(kd.KEY_ENTER)
    s.scene('saved', 0.8)
    s.caption('新規にしてから開き直します', '保存した内容がそのまま戻ります')
    s.key(kd.KEY_CHAR, 'n', kd.MOD_CTRL)
    s.scene('new', 0.6)
    s.key(kd.KEY_CHAR, 'o', kd.MOD_CTRL)
    s.type('神楽.txt')
    s.scene('open', 0.8)
    s.key(kd.KEY_ENTER)
    s.scene('reopened')
    e.win.close()
    s.editor = None

    # 4. Two windows side by side, never overlapping: F6 switches.
    s.caption('F6でウィンドウを切り替え', 'Tabで入力欄とボタンを移動')
    s.card('card-windows', 'ウィンドウ切替', 'F6で次のウィンドウへ')
    left = d.create_window('連絡先', 4, 16, 152, 146, closable=False, movable=False)
    left.text(6, 6, '名前', 1)
    left.field(6, 18, 138)
    left.text(6, 40, 'メモ', 1)
    left.field(6, 52, 138)
    right = d.create_window('設定', 164, 16, 152, 146, closable=False, movable=False)
    right.text(6, 6, 'ユーザー名', 1)
    right.field(6, 18, 138, 'kagura')
    right.button(6, 44, 64, 16, '適用', kd.BTN_DEFAULT, True)
    left.activate()
    s.frame(0)
    s.type('山田 花子')
    s.key(kd.KEY_TAB)
    s.type('来週の打ち合わせ')
    s.scene('left')
    s.key(kd.KEY_F6)
    s.key(kd.KEY_END)
    s.type('9')
    s.scene('right')
    s.key(kd.KEY_F6)
    s.scene('back-left', 0.8)
    left.close()
    right.close()

    s.caption('神楽-9', 'github.com/siska-tech/kagura')
    s.card('end', 'ありがとうございました', 'C言語の編集エンジン + MicroPython')


def main(desk=None, docs=None, out=print, pace=1.0, dump=None):
    own = desk is None
    if own:
        from kagura.desktop import Desktop
        desk = Desktop(menus=MENUS, cursor=False)
        if docs is None:
            docs = de.ram_docs(blocks=32)                # 16 KB in RAM: never flash
    scenes = [0]

    def step(name):
        import binascii
        scenes[0] += 1
        tiles = desk.present()
        mirror = getattr(desk, 'mirror', None)
        out('SCENE %d %s %08x %d%s' % (scenes[0], name, desk.crc(), tiles,
                                       ' tile4 %08x' % binascii.crc32(mirror) if mirror else ''))
        if dump:
            buf = bytearray(32000)
            desk.snapshot(buf)
            with open('%s/%02d-%s.raw' % (dump, scenes[0], name), 'wb') as f:
                f.write(buf)

    try:
        desk.present()
        chapters(Show(desk, docs, step, pace if own else 0))
    finally:
        if own:
            desk.close()


if __name__ == '__main__':
    import sys
    if '--host' in sys.argv:
        folder = sys.argv[sys.argv.index('--host') + 1]
        dump = sys.argv[sys.argv.index('--dump') + 1] if '--dump' in sys.argv else None
        # Labelled as on the board (ram_docs), so host and board frames are identical.
        main(desk=de.HostDesktop(MENUS), docs=de.Documents(folder, '/ramdocs/docs'), dump=dump)
    else:
        main()
