# SPDX-License-Identifier: Apache-2.0
"""Shared lifecycle for the three GUI demos; no board globals changed."""
import time
from kagura.ui import App, Theme, BitmapFont8, StdinInput

# Kept for the initial acceptance fixture; applications should use StdinInput.
USBInput = StdinInput


def launch(build, console=None, device=None, exclusive=False, mode='spi',
           font_path='/fonts/misaki8.kfnt', seconds=None, input_adapter=None):
    import kagura
    from kagura_ja import Font
    font = Font(font_path)
    own_device = console is None and device is None
    app = None
    try:
        if console is not None:
            device = console.screen.device
        elif device is None:
            if not exclusive:
                raise ValueError('provide console or explicitly use exclusive=True')
            device = kagura.connect(mode=mode)
        app = App(device, console=console, exclusive=exclusive,
                  theme=Theme(BitmapFont8(font)),
                  input_adapter=input_adapter if input_adapter is not None else
                  (None if console is not None else StdinInput()))
        update = build(app)
        if seconds is None and update is None:
            app.run()
        else:
            from kagura.ui.events import now_us, elapsed
            start = now_us()
            app.running = True
            while app.running and (seconds is None or elapsed(now_us(), start) < seconds * 1000000):
                if update is not None:
                    update()
                app.step()
                time.sleep_ms(10)
    finally:
        if app is not None:
            app.close()
        font.close()
        if own_device and device is not None:
            device.deinit()
