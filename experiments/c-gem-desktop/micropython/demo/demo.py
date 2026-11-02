# SPDX-License-Identifier: Apache-2.0
"""Deterministic two-window demo of the kagura_desktop binding.

Creates a desktop with menus, opens a Notes window and a Sprite window,
draws text, rectangles, a button and a 16x16 sprite at three zooms, then
feeds scripted mouse and keyboard input with explicit times:

   1 open      both windows, Sprite on top
   2 focus     click the Notes title: focus switches, the status line follows
   3 typing    H i ! Backspace ? into Notes
   4 press     mouse down on OK (button drawn pressed)
   5 release   mouse up on OK (label changes)
   6 paint     raise Sprite, pick orange from the palette, drag a stroke
   7 import    load another sprite (whole sprite changes)
   8 move      drag the Notes window by its title (it is raised first)
   9 menu      Window > Close closes the top window (Notes)
  10 closebox  the close box closes Sprite; the app frees the sprite

After each step it prints
  STEP <name> <framebuffer crc32> <TILE4 mirror crc32> <tiles exported>
The mirror only receives what present() exported, so its CRC shows that the
exported runs reproduce the screen. tests/ref_demo.c draws the same scenario
with the C API directly (no kdm, no MicroPython) and must print the same
lines.

  micropython demo/demo.py
"""
import binascii

import kagura_desktop as kd

FACE = ('00000000000000000000001100001188000118dd00118ddd0018dd210018dd11'
        '000000000000000011000000dd110000dddd1000ddddd100dd21dd10dd11dd10'
        '018ddddd018ddd6d018dddd60188dddd00188888000111110000000000000000'
        'ddddddd1ddd6ddd1666dddd1dddddd8188888810111111000000000000000000')
HEART = ('0000000000111000016661001666661016626661162666661666666616666666'
         '0000000000111000016661001666661066666610666666106666661066666610'
         '0166666600166666000166660000166600000166000000160000000100000000'
         '6666610066661000666100006610000061000000100000000000000000000000')
MENUS = (('Desk', ('About demo', '-', 'Quit')), ('Window', ('Close', 'Cycle')))

GRID_X, GRID_Y, ZOOM = 4, 4, 6
SWATCH_X, SWATCH_Y = 108, 60
OK_BOX = (100, 4, 56, 14)


class Demo:
    def __init__(self, out=print):
        self.out = out
        self.t = 0
        self.vram = bytearray(32000)
        d = self.desk = kd.Desktop(320, 200, menus=MENUS)

        n = self.notes = d.create_window('Notes', 12, 20, 168, 100)
        n.fill_rect(4, 4, 60, 20, 12)
        n.rect(4, 4, 60, 20, 1)
        self.hello = n.text(8, 10, 'Hello', 1)
        n.text(4, 30, 'Typed:', 1)
        self.typed = ''
        self.typed_id = n.text(56, 30, '', 5)
        self.status = n.text(4, 44, 'status: -', 4, -1, 1)
        self.ok = n.button(*OK_BOX, 'OK')
        self.pressed = False
        n.hline(4, 60, 152, 4)

        self.spr = d.sprite(HEART)
        s = self.paint = d.create_window('Sprite', 128, 60, 180, 128, bg=3)
        s.sprite(GRID_X, GRID_Y, self.spr, ZOOM)
        s.sprite(108, 4, self.spr, 1)
        s.sprite(108, 24, self.spr, 2, 0)
        for i in range(16):
            s.fill_rect(SWATCH_X + i % 4 * 14, SWATCH_Y + i // 4 * 10, 12, 8, i)
        self.colour = 6
        self.colour_id = s.text(100, 102, 'COLOUR 6', 1, 3)

    # ---- input (explicit times: 250 ms apart, never a double click) ----

    def ev(self, kind, x, y):
        self.t += 250
        self.desk.pointer(kind, x, y, self.t)

    def click(self, x, y):
        self.ev(kd.POINTER_DOWN, x, y)
        self.ev(kd.POINTER_UP, x, y)

    def key(self, key, ch=0):
        self.t += 250
        self.desk.key(key, ch, 0, self.t)

    def drag(self, x, y, dx, dy, steps):
        self.ev(kd.POINTER_DOWN, x, y)
        for i in range(1, steps + 1):
            self.ev(kd.POINTER_MOVE, x + dx * i // steps, y + dy * i // steps)
        self.ev(kd.POINTER_UP, x + dx, y + dy)

    # ---- application logic: everything arrives through poll() ----

    def handle(self):
        d = self.desk
        while True:
            e = d.poll()
            if e is None:
                return
            kind, w, x, y, key, ch, mods, clicks = e
            if kind == kd.FOCUS:
                self.notes_text(self.status, 'status: ' + ('Notes' if w == self.notes else 'Sprite'))
            elif kind == kd.KEY and w == self.notes:
                if key == kd.KEY_CHAR:
                    self.typed += chr(ch)
                elif key == kd.KEY_BACKSPACE:
                    self.typed = self.typed[:-1]
                self.notes.set_text(self.typed_id, self.typed)
            elif w == self.notes and kind in (kd.POINTER_DOWN, kd.POINTER_UP):
                inside = OK_BOX[0] <= x < OK_BOX[0] + OK_BOX[2] and OK_BOX[1] <= y < OK_BOX[1] + OK_BOX[3]
                if kind == kd.POINTER_DOWN and inside:
                    self.pressed = True
                    self.notes.set_flags(self.ok, kd.BTN_PRESSED)
                elif kind == kd.POINTER_UP and self.pressed:
                    self.pressed = False
                    self.notes.set_flags(self.ok, 0)
                    if inside:
                        self.notes.set_text(self.hello, 'Clicked')
            elif w == self.paint and kind in (kd.POINTER_DOWN, kd.POINTER_MOVE):
                gx, gy = (x - GRID_X) // ZOOM, (y - GRID_Y) // ZOOM
                if 0 <= x - GRID_X < 16 * ZOOM and 0 <= y - GRID_Y < 16 * ZOOM:
                    self.spr.set(gx, gy, self.colour)
                elif kind == kd.POINTER_DOWN:
                    sx, sy = (x - SWATCH_X) // 14, (y - SWATCH_Y) // 10
                    if 0 <= sx < 4 and 0 <= sy < 4 and x >= SWATCH_X and y >= SWATCH_Y:
                        self.colour = sy * 4 + sx
                        self.paint.set_text(self.colour_id, 'COLOUR %d' % self.colour)
            elif kind == kd.MENU and key == 1 and ch == 0:   # Window > Close
                top = d.top()
                if top is not None:
                    self.closing(top)
                    top.close()
            elif kind == kd.CLOSE:
                self.closing(w)

    def notes_text(self, item, text):
        if self.notes.is_open():
            self.notes.set_text(item, text)

    def closing(self, w):
        if w == self.paint:
            self.spr.free()

    def step(self, name):
        self.handle()
        tiles = self.desk.present(self.vram)
        self.out('STEP %s %08x %08x %d' % (name, self.desk.crc(), binascii.crc32(self.vram), tiles))

    # ---- the scenario ----

    def run(self):
        self.step('open')
        self.click(40, 24)                          # Notes title
        self.step('focus')
        for c in 'Hi!':
            self.key(kd.KEY_CHAR, c)
        self.key(kd.KEY_BACKSPACE)
        self.key(kd.KEY_CHAR, '?')
        self.step('typing')
        wx, wy = self.notes.work()[:2]
        self.ev(kd.POINTER_DOWN, wx + 120, wy + 10)
        self.step('press')
        self.ev(kd.POINTER_UP, wx + 120, wy + 10)
        self.step('release')
        self.click(250, 64)                         # Sprite title
        px, py = self.paint.work()[:2]
        self.click(px + SWATCH_X + 2 * 14 + 6, py + SWATCH_Y + 3 * 10 + 4)   # orange, 14
        self.drag(px + GRID_X + 3 * ZOOM + 3, py + GRID_Y + 5 * ZOOM + 3, 7 * ZOOM, 0, 7)
        self.step('paint')
        self.spr.load(FACE)
        self.step('import')
        self.drag(40, 24, 24, 40, 3)                # Notes title: raise and move
        self.step('move')
        self.ev(kd.POINTER_DOWN, 60, 4)             # Window menu (title x 56)
        self.ev(kd.POINTER_MOVE, 62, 15)
        self.ev(kd.POINTER_UP, 62, 15)              # Close
        self.step('menu')
        fx, fy = self.paint.frame()[:2]
        self.click(fx + 5, fy + 5)                  # close box
        self.step('closebox')
        return self


if __name__ == '__main__':
    Demo().run()
