# SPDX-License-Identifier: Apache-2.0
"""Layout/input mockup only: custom Widget draws a 16x16 sprite preview."""
from kagura.ui import Screen, Panel, HBox, VBox, Label, Button, Widget


class SpritePreview(Widget):
    def __init__(self, **kwargs):
        super().__init__(width=128, height=128, **kwargs)
        self.color = 4

    def paint(self, renderer, theme):
        x, y = self.bounds[:2]
        for row in range(16):
            for col in range(16):
                color = self.color if (col-7)*(col-7)+(row-7)*(row-7)<40 else 2+(row+col)%2
                renderer.fill_rect(x+col*8,y+row*8,7,7,color)


def build(app):
    screen = Screen(color=0)
    menu = screen.add(HBox(x=0, y=0, width=320, height=24, spacing=8, padding=4))
    status = screen.add(Label('Studio mock / Tab + Enter', x=4, y=224, width=312))
    for name in ('File','Edit','View'):
        menu.add(Button(name,on_click=lambda n=name: status.set_text(n+' / mock only')))
    tools = screen.add(VBox(x=4,y=32,width=88,height=160,spacing=6))
    tools.add(Label('TOOLS'))
    for name in ('Pencil','Fill','Select'):
        tools.add(Button(name,on_click=lambda n=name: status.set_text('Tool: '+n)))
    preview = screen.add(SpritePreview(x=100,y=32))
    screen.add(Label('16 x 16',x=100,y=168))
    palette = screen.add(VBox(x=240,y=32,width=76,height=180,spacing=4))
    palette.add(Label('PALETTE'))
    def choose(color):
        preview.color = color
        preview.invalidate()
        status.set_text('Color: %d' % color)
    for color in range(4,10):
        palette.add(Button(str(color),width=64,on_click=lambda c=color: choose(c)))
    app.set_root(screen)


def run(**kwargs):
    from ui_demo_common import launch
    launch(build, **kwargs)
