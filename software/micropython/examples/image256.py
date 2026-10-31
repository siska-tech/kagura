# SPDX-License-Identifier: Apache-2.0
"""Show pseudo-256-colour pictures (.kimg), as a PSRAM slideshow when possible.

Convert pictures on the PC with software/pico/send_image.py --save photo.kimg
photo.jpg. With a PSRAM bitstream every file goes into a PSRAM slot once and
the pictures then change by COPY alone (kagura.image256.Slots); otherwise the
first one is shown.

    import image256
    image256.run(['sunset.kimg', 'photo.kimg'], seconds=30)
"""
import time
import kagura
from kagura import image256, regs as R
from kagura.framebuffer import TileFramebuffer


def run(paths, seconds=30, hold_ms=3000, fb=None):
    """Connect if no fb is given (QSPI 5 MHz); returns the fb."""
    if isinstance(paths, str):
        paths = [paths]
    if fb is None:
        d = kagura.connect(mode='qspi', baudrate=5_000_000)
        fb = TileFramebuffer(d)
        d.write_memory(0x9400, bytes(image256.PALETTE))   # initialize()'s COMMIT applies it
        fb.initialize()
    if len(paths) == 1 or not fb.device.caps & R.CAPS_PSRAM:
        image256.show(fb, paths[0])
        return fb
    slots = image256.Slots(fb)
    for slot, path in enumerate(paths):
        start = time.ticks_ms()
        slots.save_file(slot, path)
        print('IMAGE256 saved slot=%d %s ms=%d' % (slot, path, time.ticks_diff(time.ticks_ms(), start)))
    end = time.ticks_add(time.ticks_ms(), seconds * 1000)
    shown = 0
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        start = time.ticks_ms()
        slots.show(shown % len(paths))
        print('IMAGE256 slot=%d change_ms=%d' % (shown % len(paths), time.ticks_diff(time.ticks_ms(), start)))
        shown += 1
        time.sleep_ms(hold_ms)
    return fb
