# SPDX-License-Identifier: Apache-2.0
"""神楽デスクトップ: a Japanese GEM-style desktop driven from MicroPython.

The windows, menus, compositor and Japanese text are the native desktop
(kagura_desktop, software/desktop); this file is only the application:
what windows exist, what they show, and how it reacts to events.

On KAGURA-9 (the HDMI console running, firmware with kagura_desktop):
    import desktop_ja; desktop_ja.main()            # scripted tour, then exit
    desktop_ja.main(script=False)                   # keyboard: F10 menus, F6 windows
On a PC (unix port with kagura_desktop), without hardware:
    micropython desktop_ja.py --host [--dump DIR]   # a CRC (and snapshot) per scene

Every scene of the tour prints `SCENE <n> <name> <framebuffer crc32>`; the
host run prints the same CRCs, which the hardware test compares.
"""
import binascii

import kagura_desktop as kd

MENUS = (('ファイル', ('開く', '情報…', '-', '終了')),
         ('編集', ('元に戻す', '-', 'コピー', '貼り付け')),
         ('表示', ('アイコン', '一覧')),
         ('設定', ('画面', 'スプライト工房')))
M_FILE, M_EDIT, M_VIEW, M_SETTINGS = 0, 1, 2, 3

FILES = (('folder', '文書'), ('file', 'メモ.TXT'), ('studio', '絵.SPR'),
         ('app', 'ゲーム.PRG'), ('text', '設定.CFG'), ('drive', '音楽'))
HEART = ('0000000000111000016661001666661016626661162666661666666616666666'
         '0000000000111000016661001666661066666610666666106666661066666610'
         '0166666600166666000166660000166600000166000000160000000100000000'
         '6666610066661000666100006610000061000000100000000000000000000000')
FACE = ('00000000000000000000001100001188000118dd00118ddd0018dd210018dd11'
        '000000000000000011000000dd110000dddd1000ddddd100dd21dd10dd11dd10'
        '018ddddd018ddd6d018dddd60188dddd00188888000111110000000000000000'
        'ddddddd1ddd6ddd1666dddd1dddddd8188888810111111000000000000000000')
ZOOM, GRID = 6, 4


class App:
    def __init__(self, desk):
        self.desk = desk
        self.t = 0
        self.quit = False
        self.files = self.about = self.studio = None
        self.sprite = desk.sprite(HEART)
        self.colour = 6
        w = self.welcome = desk.create_window('神楽デスクトップ', 6, 16, 196, 92)
        w.fill_rect(4, 4, 186, 18, 12)
        w.text(10, 9, 'ようこそ！ 神楽-9 へ', 1)
        w.text(6, 28, '日本語のGEM風デスクトップ', 1)
        w.text(6, 40, 'C言語の画面合成と', 1)
        w.text(6, 50, 'MicroPythonのアプリ', 1)
        self.status = w.text(6, 64, '状態: 起動しました', 5, 2)

    # ---- windows ----

    def open_files(self):
        if self.files is not None and self.files.is_open():
            self.files.activate()
            return
        w = self.files = self.desk.create_window('ファイル', 112, 70, 200, 92)
        for i, (art, name) in enumerate(FILES):
            w.icon(24 + (i % 3) * 60, 6 + (i // 3) * 36, art, name)
        self.set_status('一覧を表示')

    def open_about(self):
        if self.about is not None and self.about.is_open():
            return
        w = self.about = self.desk.create_window('情報', 70, 60, 180, 80, closable=False)
        w.text(8, 8, '神楽-9 デスクトップ', 1)
        w.text(8, 20, '版 0.1  日本語対応', 4)
        w.text(8, 32, 'ファイル 編集 表示 設定', 5, -1, 1)
        self.ok = w.button(62, 46, 52, 16, 'OK', kd.BTN_DEFAULT)
        self.ok_pressed = False

    def open_studio(self):
        if self.studio is not None and self.studio.is_open():
            self.studio.activate()
            return
        w = self.studio = self.desk.create_window('スプライト工房', 140, 20, 176, 130, bg=3)
        w.sprite(GRID, GRID, self.sprite, ZOOM)
        w.sprite(108, 4, self.sprite, 1)
        w.sprite(108, 24, self.sprite, 2, 0)
        for i in range(16):
            w.fill_rect(108 + i % 4 * 14, 60 + i // 4 * 10, 12, 8, i)
        self.colour_id = w.text(4, 106, '色: 6', 1, 3)

    def set_status(self, text):
        if self.welcome.is_open():
            self.welcome.set_text(self.status, '状態: ' + text)

    # ---- events ----

    def handle(self):
        d = self.desk
        while True:
            e = d.poll()
            if e is None:
                return
            kind, w, x, y, key, ch, mods, clicks = e
            if kind == kd.MENU:
                self.menu(key, ch)
            elif kind == kd.CLOSE:
                self.set_status('窓を閉じた')
            elif w is not None and w == self.about and kind in (kd.POINTER_DOWN, kd.POINTER_UP):
                inside = 62 <= x < 114 and 46 <= y < 62
                if kind == kd.POINTER_DOWN and inside:
                    self.ok_pressed = True
                    w.set_flags(self.ok, kd.BTN_DEFAULT | kd.BTN_PRESSED)
                elif kind == kd.POINTER_UP and self.ok_pressed:
                    self.ok_pressed = False
                    w.set_flags(self.ok, kd.BTN_DEFAULT)
                    if inside:
                        w.close()
            elif w is not None and w == self.about and kind == kd.KEY and key in (kd.KEY_ENTER, kd.KEY_ESCAPE):
                w.close()
            elif w is not None and w == self.studio and kind in (kd.POINTER_DOWN, kd.POINTER_MOVE):
                self.paint(x, y, kind == kd.POINTER_DOWN)
            elif w is not None and w == self.files and kind == kd.POINTER_DOWN and clicks == 2:
                self.open_studio()

    def menu(self, m, item):
        if m == M_FILE and item == 0:
            self.open_files()
        elif m == M_FILE and item == 1:
            self.open_about()
        elif m == M_FILE and item == 3:
            self.quit = True
        elif m == M_SETTINGS and item == 1:
            self.open_studio()
        else:
            self.set_status('%s を選びました' % MENUS[m][1][item])

    def paint(self, x, y, down):
        gx, gy = (x - GRID) // ZOOM, (y - GRID) // ZOOM
        if 0 <= x - GRID < 16 * ZOOM and 0 <= y - GRID < 16 * ZOOM:
            self.sprite.set(gx, gy, self.colour)
        elif down and x >= 108 and y >= 60:
            sx, sy = (x - 108) // 14, (y - 60) // 10
            if sx < 4 and sy < 4:
                self.colour = sy * 4 + sx
                self.studio.set_text(self.colour_id, '色: %d' % self.colour)

    # ---- scripted input (explicit times: never an accidental double click) ----

    def ev(self, kind, x, y):
        self.t += 250
        self.desk.pointer(kind, x, y, self.t)

    def click(self, x, y):
        self.ev(kd.POINTER_DOWN, x, y)
        self.ev(kd.POINTER_UP, x, y)

    def drag(self, x, y, dx, dy, steps):
        self.ev(kd.POINTER_DOWN, x, y)
        for i in range(1, steps + 1):
            self.ev(kd.POINTER_MOVE, x + dx * i // steps, y + dy * i // steps)
        self.ev(kd.POINTER_UP, x + dx, y + dy)

    def choose(self, menu_x, item):
        """Opens a menu by its title and releases on an item (10 px rows)."""
        self.ev(kd.POINTER_DOWN, menu_x, 4)
        self.ev(kd.POINTER_MOVE, menu_x + 2, 15 + item * 10)
        self.ev(kd.POINTER_UP, menu_x + 2, 15 + item * 10)


# Menu title x positions: 8 px margin, title width + 16 apart (kd_gfx.c).
FILE_X, SETTINGS_X = 12, 8 + (32 + 16) + (16 + 16) + (16 + 16) + 4


def tour(app, step):
    """The scripted scenes. step(name) presents and reports each one."""
    step('desktop')
    app.choose(FILE_X, 0)                          # ファイル > 開く
    app.handle()
    step('files')
    app.ev(kd.POINTER_DOWN, FILE_X, 4)             # menu open, held
    app.ev(kd.POINTER_MOVE, FILE_X + 2, 25)
    step('menu')
    app.ev(kd.POINTER_UP, FILE_X + 2, 25)          # 情報…
    app.handle()
    step('about')
    wx, wy = app.about.work()[:2]
    app.ev(kd.POINTER_DOWN, wx + 80, wy + 52)
    app.handle()
    step('ok-pressed')
    app.ev(kd.POINTER_UP, wx + 80, wy + 52)
    app.handle()
    step('about-closed')
    app.choose(SETTINGS_X, 1)                      # 設定 > スプライト工房
    app.handle()
    step('studio')
    sx, sy = app.studio.work()[:2]
    app.click(sx + 108 + 2 * 14 + 6, sy + 60 + 3 * 10 + 4)   # orange (14)
    app.drag(sx + GRID + 3 * ZOOM + 3, sy + GRID + 5 * ZOOM + 3, 7 * ZOOM, 0, 7)
    app.handle()
    step('paint')
    app.sprite.load(FACE)
    step('import')
    fx, fy = app.files.frame()[:2]
    app.drag(fx + 16, fy + 4, -100, 30, 4)         # raise ファイル by its visible title, move it
    app.handle()
    step('move')
    cx, cy = app.studio.frame()[:2]
    app.click(cx + 4, cy + 4)                      # raise スプライト工房
    app.click(cx + 4, cy + 4)                      # close box
    app.handle()
    step('closed')


def main(script=True, desk=None, out=print, dump=None):
    own = desk is None
    if own:
        from kagura.desktop import Desktop
        desk = Desktop(menus=MENUS)
    app = App(desk)
    scenes = [0]

    def step(name):
        scenes[0] += 1
        tiles = desk.present()
        mirror = getattr(desk, 'mirror', None)   # host: CRC of the exported TILE4 image too
        out('SCENE %d %s %08x %d%s' % (scenes[0], name, desk.crc(), tiles,
                                       ' tile4 %08x' % binascii.crc32(mirror) if mirror else ''))
        if dump:   # host only: raw 4bpp snapshots for reference pictures
            buf = bytearray(32000)
            desk.snapshot(buf)
            with open('%s/%02d-%s.raw' % (dump, scenes[0], name), 'wb') as f:
                f.write(buf)

    try:
        if script:
            tour(app, step)
        else:
            interactive(app, step)
    finally:
        if own:
            desk.close()
    return app


def interactive(app, step):
    """Keyboard control from the USB/UART terminal: F10 menus, arrows,
    Enter, Esc, F6 next window, Ctrl+W close, q quits."""
    import sys
    keys = {'A': kd.KEY_UP, 'B': kd.KEY_DOWN, 'C': kd.KEY_RIGHT, 'D': kd.KEY_LEFT}
    step('interactive')
    while not app.quit:
        c = sys.stdin.read(1)
        if c == 'q':
            break
        if c == '\x1b':
            c2 = sys.stdin.read(1)
            if c2 == '[':
                c3 = sys.stdin.read(1)
                if c3 in keys:
                    app.desk.key(keys[c3])
                elif c3 == '2':                # ESC [ 21 ~ is F10
                    sys.stdin.read(2)
                    app.desk.key(kd.KEY_F10)
                elif c3 == '1':                # ESC [ 17 ~ is F6
                    sys.stdin.read(2)
                    app.desk.key(kd.KEY_F6)
            else:
                app.desk.key(kd.KEY_ESCAPE)
        elif c in '\r\n':
            app.desk.key(kd.KEY_ENTER)
        elif c == '\x17':
            app.desk.key(kd.KEY_CHAR, 'w', kd.MOD_CTRL)
        app.handle()
        app.desk.present()


class HostDesktop:
    """kagura_desktop.Desktop with present() into a TILE4 mirror (no hardware)."""
    def __init__(self, menus):
        self._kd = kd.Desktop(320, 200, menus=menus)
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
