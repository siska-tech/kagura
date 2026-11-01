# SPDX-License-Identifier: Apache-2.0
from .widget import Widget


class Label(Widget):
    def __init__(self, text='', color=None, **kwargs):
        if not isinstance(text, str):
            raise TypeError('text must be str')
        super().__init__(**kwargs)
        self.text, self.color = text, color
        self._size_text = self._size_font = self._size = None

    def _text_size(self, font):
        # Layout measures every child on each relayout; per-character measuring
        # dominated it on RP2040. Strings are immutable, so identity is a safe key.
        text = self.text
        if self._size_text is not text or self._size_font is not font:
            self._size = font.measure(text)
            self._size_text, self._size_font = text, font
        return self._size

    def set_text(self, text):
        if not isinstance(text, str):
            raise TypeError('text must be str')
        if self.text != text:
            self.invalidate()
            self.text = text
            self.relayout()

    def measure(self, font):
        if self.width is not None and self.height is not None:
            return self.width, self.height
        w, h = self._text_size(font)
        return (w if self.width is None else self.width,
                h if self.height is None else self.height)

    def paint(self, renderer, theme):
        theme.font.draw(renderer, self.text, self.bounds[0], self.bounds[1],
                        theme.foreground if self.color is None else self.color)


class Button(Label):
    focusable = True

    def __init__(self, text='', on_click=None, **kwargs):
        super().__init__(text, **kwargs)
        self.on_click = on_click
        self.pressed = False

    def measure(self, font):
        if self.width is not None and self.height is not None:
            return self.width, self.height
        w, h = self._text_size(font)
        return (w + 8 if self.width is None else self.width,
                h + 8 if self.height is None else self.height)

    def paint(self, renderer, theme):
        x, y, right, bottom = self.bounds
        # Border colour over the whole button, then the face inside: the same
        # pixels as fill + 4-line rect, in 2 backend calls instead of 5.
        renderer.fill_rect(x, y, right - x, bottom - y,
                           theme.focus if self.focused else theme.disabled)
        renderer.fill_rect(x + 1, y + 1, right - x - 2, bottom - y - 2,
                           theme.pressed if self.pressed else theme.button)
        theme.font.draw(renderer, self.text, x + 4, y + 4,
                        theme.foreground if self.enabled else theme.disabled)

    def handle(self, event):
        if event.key == 'enter' or event.key == 'text' and event.text == ' ':
            if event.kind == 'release':
                self.pressed = False
                self.invalidate()
                return True
            self.pressed = True
            self.invalidate()
            if self.on_click is not None:
                self.on_click()
            return True
        return False


class ProgressBar(Widget):
    def __init__(self, value=0, maximum=100, width=120, height=12, **kwargs):
        if maximum <= 0:
            raise ValueError('maximum must be positive')
        super().__init__(width=width, height=height, **kwargs)
        self.maximum = maximum
        self.value = max(0, min(maximum, value))

    def set_value(self, value):
        value = max(0, min(self.maximum, value))
        if value != self.value:
            self.value = value
            self.invalidate()

    def paint(self, renderer, theme):
        x, y, right, bottom = self.bounds
        renderer.fill_rect(x, y, right - x, bottom - y, theme.panel)
        renderer.fill_rect(x, y, (right - x) * self.value // self.maximum,
                           bottom - y, theme.focus)


class ListView(Widget):
    """Bounded visible rows; caller owns items (no list copy)."""
    focusable = True

    def __init__(self, items, on_select=None, width=120, height=64, **kwargs):
        super().__init__(width=width, height=height, **kwargs)
        self.items, self.on_select = items, on_select
        self.selected, self.top = (0 if items else -1), 0

    def set_items(self, items):
        self.items = items
        self.selected = max(0, min(len(items) - 1, self.selected)) if items else -1
        self.top = 0
        self.invalidate()

    def handle(self, event):
        if event.kind == 'release':
            return False
        if event.key in ('up', 'down') and self.items:
            selected = max(0, min(len(self.items) - 1,
                                 self.selected + (1 if event.key == 'down' else -1)))
            if selected != self.selected:
                self.selected = selected
                rows = max(1, (self.bounds[3] - self.bounds[1]) // self.app.theme.font.height)
                self.top = max(min(self.top, selected), selected - rows + 1)
                self.invalidate()
            return True
        if event.key == 'enter' and self.selected >= 0:
            if self.on_select is not None:
                self.on_select(self.selected, self.items[self.selected])
            return True
        return False

    def paint(self, renderer, theme):
        x, y, right, bottom = self.bounds
        renderer.fill_rect(x, y, right - x, bottom - y, theme.panel)
        index = self.top
        while y < bottom and index < len(self.items):
            if index == self.selected:
                renderer.fill_rect(x, y, right - x, theme.font.height,
                                   theme.focus if self.focused else theme.button)
            theme.font.draw(renderer, self.items[index], x, y, theme.foreground)
            index += 1
            y += theme.font.height
