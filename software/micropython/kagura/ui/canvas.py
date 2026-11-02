# SPDX-License-Identifier: Apache-2.0
"""Zoomed cell canvas, and a 4bpp sprite editor built on it."""
from .widget import Widget

# Same value as kagura.framebuffer.TILE4; not imported so the UI loads without the SDK.
TILE4 = 0x40


def _int(value, name):
    # type() rather than isinstance(): bools are rejected on CPython as on MicroPython.
    if type(value) is not int:
        raise TypeError(name + ' must be int')


class Sprite4:
    """width x height pixels, 4 bits each, in KAGURA tile layout (TILE4).

    8x8 tiles in row-major order; a tile is 32 bytes, 8 rows of 4 bytes; each
    byte holds two pixels, the even (left) x in bits 7..4. Pixel value 0 is
    transparent, as for hardware sprites. A 16x16 image is 128 bytes and equals
    the four patterns of a 16x16 sprite: top-left, top-right, bottom-left,
    bottom-right. source() can be passed to TileFramebuffer.blit().
    """

    def __init__(self, width=16, height=16, data=None):
        _int(width, 'width')
        _int(height, 'height')
        if width <= 0 or height <= 0 or width & 7 or height & 7:
            raise ValueError('sprite size must be a positive multiple of 8')
        self.width, self.height = width, height
        self.data = bytearray(width * height // 2)
        if data is not None:
            self.load(data)

    def _offset(self, x, y):
        _int(x, 'x')
        _int(y, 'y')
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError('pixel outside sprite')
        return ((y >> 3) * (self.width >> 3) + (x >> 3)) * 32 + (y & 7) * 4 + ((x & 7) >> 1)

    def get(self, x, y):
        value = self.data[self._offset(x, y)]
        return value & 15 if x & 1 else value >> 4

    def set(self, x, y, color):
        """Returns True if the pixel changed."""
        offset = self._offset(x, y)
        _int(color, 'color')
        if not 0 <= color <= 15:
            raise ValueError('color')
        old = self.data[offset]
        new = (old & 240) | color if x & 1 else (old & 15) | color << 4
        if new == old:
            return False
        self.data[offset] = new
        return True

    def export(self):
        return bytes(self.data)

    def load(self, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError('sprite data must be bytes, bytearray or memoryview')
        if len(data) != len(self.data):
            raise ValueError('sprite data must be %d bytes' % len(self.data))
        self.data[:] = data

    def source(self):
        return (self.data, self.width, self.height, TILE4)


class Canvas(Widget):
    """columns x rows cells of zoom x zoom pixels, with a cursor cell.

    Subclasses return each cell's colour from cell() and act in activate(),
    erase() and text(). paint() draws only the cells inside the renderer clip,
    one fill per run of equal cells in a row, so invalidate_cell() repaints a
    single cell. Cursor keys move the cursor and are consumed; Tab leaves.
    """
    focusable = True
    opaque = True

    def __init__(self, columns, rows, zoom=1, **kwargs):
        for value, name in ((columns, 'columns'), (rows, 'rows'), (zoom, 'zoom')):
            _int(value, name)
            if value <= 0:
                raise ValueError(name + ' must be positive')
        super().__init__(width=columns * zoom, height=rows * zoom, **kwargs)
        self.columns, self.rows, self.zoom = columns, rows, zoom
        self.cursor = (0, 0)

    def cell(self, cx, cy):
        return 0

    def cell_at(self, x, y):
        """Cell under screen pixel (x, y), or None."""
        left, top = self.bounds[0], self.bounds[1]
        cx, cy = (x - left) // self.zoom, (y - top) // self.zoom
        if x >= left and y >= top and cx < self.columns and cy < self.rows:
            return cx, cy
        return None

    def cell_rect(self, cx, cy):
        z = self.zoom
        x, y = self.bounds[0] + cx * z, self.bounds[1] + cy * z
        return (x, y, x + z, y + z)

    def invalidate_cell(self, cx, cy):
        if self.app is not None:
            self.app.damage(self.cell_rect(cx, cy))

    def set_cursor(self, cx, cy):
        cx = max(0, min(self.columns - 1, cx))
        cy = max(0, min(self.rows - 1, cy))
        old = self.cursor
        if (cx, cy) != old:
            self.cursor = (cx, cy)
            self.invalidate_cell(old[0], old[1])
            self.invalidate_cell(cx, cy)

    def paint(self, renderer, theme):
        left, top = self.bounds[0], self.bounds[1]
        z, clip = self.zoom, renderer.clip
        c0, c1 = max(0, (clip[0] - left) // z), min(self.columns, (clip[2] - left + z - 1) // z)
        r0, r1 = max(0, (clip[1] - top) // z), min(self.rows, (clip[3] - top + z - 1) // z)
        if c0 >= c1:
            return
        cell = self.cell
        for cy in range(r0, r1):
            y, start, color = top + cy * z, c0, cell(c0, cy)
            for cx in range(c0 + 1, c1):
                value = cell(cx, cy)
                if value != color:
                    renderer.fill_rect(left + start * z, y, (cx - start) * z, z, color)
                    start, color = cx, value
            renderer.fill_rect(left + start * z, y, (c1 - start) * z, z, color)
        if self.focused and z >= 3:
            x, y = self.cell_rect(self.cursor[0], self.cursor[1])[:2]
            renderer.rect(x, y, z, z, theme.focus)

    def handle(self, event):
        if event.kind == 'release':
            return False
        key, (cx, cy) = event.key, self.cursor
        if key in ('up', 'down', 'left', 'right'):
            self.set_cursor(cx + (key == 'right') - (key == 'left'), cy + (key == 'down') - (key == 'up'))
            return True
        if key == 'enter' or key == 'text' and event.text == ' ':
            return self.activate(cx, cy)
        if key in ('delete', 'backspace'):
            return self.erase(cx, cy)
        if key == 'text':
            return self.text(event.text)
        return False

    def activate(self, cx, cy):
        return False

    def erase(self, cx, cy):
        return False

    def text(self, text):
        return False


class SpriteCanvas(Canvas):
    """Edits a Sprite4 in place (the caller may keep and share the Sprite4).

    Enter/Space paints `color`, Delete/Backspace erases to 0 (transparent), a
    hex digit selects `color`. Transparent pixels are shown in UI colour
    `backdrop`. on_change(x, y), if given, runs after a pixel changes.
    """

    def __init__(self, sprite=None, zoom=8, color=1, backdrop=0, on_change=None, **kwargs):
        sprite = Sprite4() if sprite is None else sprite
        super().__init__(sprite.width, sprite.height, zoom, **kwargs)
        self.sprite, self.backdrop, self.on_change = sprite, backdrop, on_change
        self.color = 0
        self.set_color(color)

    def cell(self, cx, cy):
        return self.sprite.get(cx, cy) or self.backdrop

    def set_color(self, color):
        _int(color, 'color')
        if not 0 <= color <= 15:
            raise ValueError('color')
        self.color = color

    def put(self, x, y, color):
        if self.sprite.set(x, y, color):
            self.invalidate_cell(x, y)
            if self.on_change is not None:
                self.on_change(x, y)

    def reload(self, data):
        """Replace every pixel (Sprite4.load) and repaint the canvas."""
        self.sprite.load(data)
        self.invalidate()

    def activate(self, cx, cy):
        self.put(cx, cy, self.color)
        return True

    def erase(self, cx, cy):
        self.put(cx, cy, 0)
        return True

    def text(self, text):
        value = '0123456789abcdef'.find(text.lower()) if len(text) == 1 else -1
        if value < 0:
            return False
        self.set_color(value)
        return True
