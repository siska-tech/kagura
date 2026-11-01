# SPDX-License-Identifier: Apache-2.0
from .fonts import BitmapFont8


class Theme:
    def __init__(self, font=None):
        self.font = font if font is not None else BitmapFont8()
        self.background, self.foreground = 0, 1
        self.panel, self.button, self.focus, self.pressed, self.disabled = 2, 3, 4, 5, 6
        self.palette = (0x112, 0xFFF, 0x224, 0x446, 0x5DF, 0x38A, 0x777,
                        0x3D8, 0xF65, 0xFC5, 0x95F, 0x5AF, 0xBDE, 0xAAB, 0xEEE, 0x000)
