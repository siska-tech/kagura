# SPDX-License-Identifier: Apache-2.0
"""KAGURA Studio sprite editor: a 16x16 4bpp sprite, edited with the keyboard.

Arrows move, Enter/Space paint, Delete/Backspace erase (0 = transparent),
0-9/A-F pick a colour, Tab switches to the palette, U undoes (U again redoes),
P prints the sprite as hex, Escape quits. The sprite is a Sprite4 (TILE4
layout, 128 bytes); export_hex()/import_hex() exchange it as 256 hex digits.

From the REPL:
    import ui_sprite_editor
    ui_sprite_editor.run(console=kagura_console, input_adapter=StdinInput())
    ui_sprite_editor.editor.export_hex()      # after quitting
"""
import binascii
from kagura.ui import Screen, Panel, Label
from kagura.ui.canvas import Canvas, SpriteCanvas, Sprite4

editor = None  # the last built SpriteEditor, for REPL export/import


class _Grid(SpriteCanvas):
    def __init__(self, owner, sprite, **kwargs):
        self.owner = owner
        super().__init__(sprite, zoom=8, on_change=owner._changed, **kwargs)

    def put(self, x, y, color):
        if self.sprite.get(x, y) != color:
            self.owner._remember()
        super().put(x, y, color)

    def set_cursor(self, cx, cy):
        super().set_cursor(cx, cy)
        self.owner._show_cursor()

    def set_color(self, color):
        super().set_color(color)
        if getattr(self.owner, 'grid', None) is self:  # not while SpriteCanvas.__init__ runs
            self.owner._show_color()

    def text(self, text):
        return self.owner._key(text) or super().text(text)


class _Preview(SpriteCanvas):
    """1:1 view of the same Sprite4. When the whole preview is repainted and the
    backend exposes its TileFramebuffer, the TILE4 data is drawn with one blit
    (pixel value 0 shows colour 0, as backdrop 0 does); single pixels and other
    backends use the Canvas paint."""
    focusable = False

    def paint(self, renderer, theme):
        fb = getattr(renderer.backend, 'fb', None)
        b, c = self.bounds, renderer.clip
        if (fb is not None and self.backdrop == 0 and
                c[0] <= b[0] and c[1] <= b[1] and b[2] <= c[2] and b[3] <= c[3]):
            fb.blit(self.sprite.source(), b[0], b[1])
        else:
            super().paint(renderer, theme)


def _set_label(label, text):
    # The editor's labels have a fixed size: new text needs a repaint, not a layout pass.
    if label.text != text:
        label.text = text
        label.invalidate()


# Above this many changed pixels, repaint the grid and preview whole instead of per pixel.
_BULK = 16


class _Palette(Canvas):
    """The 16 colours as a 4x4 grid; Enter/Space selects the colour under the cursor."""

    def __init__(self, owner, **kwargs):
        super().__init__(4, 4, zoom=16, **kwargs)
        self.owner = owner

    def cell(self, cx, cy):
        return cy * 4 + cx

    def activate(self, cx, cy):
        self.owner.select(cy * 4 + cx)
        return True

    def text(self, text):
        if self.owner._key(text):
            return True
        value = '0123456789abcdef'.find(text.lower()) if len(text) == 1 else -1
        if value < 0:
            return False
        self.owner.select(value)
        return True


class SpriteEditor:
    def __init__(self, app, data=None):
        self.app = app
        self.sprite = Sprite4(16, 16, data)
        self._undo = None
        # A canvas cell, a preview pixel and a label stay separate damage rectangles.
        app.damage_limit = 4
        root = self.root = Screen(color=2)
        root.add(Label('KAGURA Studio / Sprite 16x16', x=8, y=4, width=304, height=8))
        self.grid = root.add(_Grid(self, self.sprite, x=8, y=20))
        self.preview = root.add(_Preview(self.sprite, zoom=1, x=152, y=20))
        root.add(Label('1:1', x=176, y=24, width=24, height=8))
        self.palette = root.add(_Palette(self, x=152, y=48))
        self.swatch = root.add(Panel(x=224, y=48, width=24, height=24))
        self.color_label = root.add(Label('', x=224, y=80, width=88, height=8))
        self.cursor_label = root.add(Label('', x=152, y=120, width=96, height=8))
        root.add(Label('Arrows move  Enter paint  Del erase', x=8, y=160, width=304, height=8))
        root.add(Label('0-F colour  Tab palette  U undo  P hex', x=8, y=172, width=304, height=8))
        self.status = root.add(Label('', x=8, y=196, width=304, height=8))
        self._show_color()
        self._show_cursor()
        app.set_root(root)
        app.focus.set(self.grid)

    # --- state shown on screen
    def _show_color(self):
        color = self.grid.color
        self.swatch.color = color
        self.swatch.invalidate()
        _set_label(self.color_label, 'Color %d%s' % (color, ' (clear)' if color == 0 else ''))
        cx, cy = color % 4, color // 4
        if self.palette.cursor != (cx, cy):
            if self.palette.focused:
                self.palette.set_cursor(cx, cy)
            else:
                # The cursor is drawn only while focused; gaining focus repaints the palette.
                self.palette.cursor = (cx, cy)

    def _show_cursor(self):
        _set_label(self.cursor_label, 'X %d Y %d' % self.grid.cursor)

    def _changed(self, x, y):
        self.preview.invalidate_cell(x, y)

    def _key(self, text):
        if text in ('u', 'U'):
            self.undo()
            return True
        if text in ('p', 'P'):
            print('SPRITE_HEX', self.export_hex())
            _set_label(self.status, 'Printed hex to the REPL')
            return True
        return False

    # --- editing
    def select(self, color):
        self.grid.set_color(color)

    def _remember(self):
        self._undo = self.sprite.export()

    def _replace(self, data):
        """Load data and repaint only the pixels that changed."""
        old = self.sprite.export()
        self.sprite.load(data)
        new = self.sprite.data
        # One pass: collect changed bytes; past _BULK changed pixels, repaint whole.
        changed, count = [], 0
        for i in range(128):
            d = old[i] ^ new[i]
            if d:
                count += (d > 15) + (d & 15 != 0)
                if count > _BULK:
                    self.grid.invalidate()
                    self.preview.invalidate()
                    return old
                changed.append(i)
        for i in changed:
            d = old[i] ^ new[i]
            tile, rest = i >> 5, i & 31
            x, y = (tile & 1) * 8 + (rest & 3) * 2, (tile >> 1) * 8 + (rest >> 2)
            for dx in (0, 1):
                if d & (0xf0 >> dx * 4):
                    self.grid.invalidate_cell(x + dx, y)
                    self.preview.invalidate_cell(x + dx, y)
        return old

    def undo(self):
        """One level; a second undo redoes."""
        if self._undo is None:
            _set_label(self.status, 'Nothing to undo')
            return False
        self._undo = self._replace(self._undo)
        _set_label(self.status, 'Undo')
        return True

    def export_hex(self):
        return binascii.hexlify(self.sprite.export()).decode()

    def import_hex(self, text):
        """256 hex digits (whitespace ignored); undoable. ValueError leaves the sprite unchanged."""
        if not isinstance(text, str):
            raise TypeError('hex text must be str')
        text = ''.join(text.split())
        if len(text) != 256:
            raise ValueError('sprite hex must be 256 digits')
        try:
            data = binascii.unhexlify(text)
        except Exception:
            raise ValueError('sprite hex must be 256 digits')
        self._undo = self._replace(data)
        _set_label(self.status, 'Imported')


def build(app, data=None):
    global editor
    editor = SpriteEditor(app, data)


def run(data_hex=None, **kwargs):
    from ui_demo_common import launch
    data = None if data_hex is None else binascii.unhexlify(''.join(data_hex.split()))
    launch(lambda app: build(app, data), **kwargs)
