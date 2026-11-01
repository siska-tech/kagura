# SPDX-License-Identifier: Apache-2.0
"""Widget Gallery: arrows/Tab, Enter, Escape. run(console=kagura_console)."""
from kagura.ui import VBox, HBox, Label, Button, Panel, ProgressBar, Screen


def build(app):
    screen = Screen(color=0)
    root = screen.add(VBox(x=8, y=8, width=304, height=224, spacing=8, padding=4))
    root.add(Label('KAGURA-UI / 日本語'))
    root.add(Label('Tab: focus / Enter: activate'))
    status = root.add(Label('Count: 0', width=240))
    progress = root.add(ProgressBar(width=272))
    row = root.add(HBox(spacing=8))
    state = [0]
    def increment():
        state[0] += 1
        status.set_text('Count: %d' % state[0])
        progress.set_value(state[0] % 101)
    row.add(Button('START', on_click=increment))
    row.add(Button('RESET', on_click=lambda: progress.set_value(0)))
    root.add(Panel(width=272, height=24)).add(Label('Panel / HDMI', x=4, y=8))
    root.add(Button('Second screen', on_click=lambda: app.set_root(second)))
    second = Screen(color=2)
    second.add(Label('Screen 2 / 画面切替', x=8, y=8))
    second.add(Button('BACK', x=8, y=32, on_click=lambda: app.set_root(screen)))
    app.set_root(screen)


def run(**kwargs):
    from ui_demo_common import launch
    launch(build, **kwargs)
