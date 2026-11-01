# SPDX-License-Identifier: Apache-2.0
"""Four animated exhibits, with pre-rendered Japanese captions in palette 15."""
import time
import gc
from array import array
import framebuffer_demo as F
from kagura.framebuffer import TileFramebuffer
from kagura import regs as R

CHAPTERS = ((F.Plasma, 'plasma', 14), (F.Tunnel, 'tunnel', 18),
            (F.Tesseract, 'tesseract', 16), (F.Ribbon, 'ribbon', 16))
CAPTION_Y = 216
CAPTION_OFFSET = 40 * (CAPTION_Y // 8) * 32
CAPTION_PALETTE = b'\x00\x00\xed\x0f\x12\x00\xdf\x02' + bytes(24)


def run(d, advance, assets, speed=1):
    fb = TileFramebuffer(d)
    pal, raw = array('H', [0] * 16), bytearray(32)
    music = None
    try:
        d.write_memory(R.VRAM_PALETTE_BASE, bytes(32))
        fb.initialize()
        cells = bytearray(1200)
        cells[1080:] = bytes((15,)) * 120
        fb.set_cell_palettes(cells)
        d.write_memory(R.VRAM_PALETTE_BASE + 15 * 32, CAPTION_PALETTE)
        music = F.Music(d, R)
        next_tick, tick = time.ticks_us(), 0

        def play():
            nonlocal next_tick, tick
            now = time.ticks_us()
            if time.ticks_diff(now, next_tick) >= 0:
                music.tick(tick)
                tick += 1
                next_tick = time.ticks_add(now, F.TICK_US)

        for factory, name, seconds in CHAPTERS:
            print('SHOWCASE graphics', name)
            gc.collect()
            scene = factory()
            with open(assets + '/' + name + '.caption', 'rb') as f:
                caption = f.read()
            if len(caption) != 3840:
                raise ValueError('caption must contain 320x24 tile-native pixels')
            scene.enter(fb, play)
            fb.buffer[CAPTION_OFFSET:] = caption
            fb.mark_dirty(0, CAPTION_Y, 320, 24)
            start = time.ticks_ms()
            duration = max(1, int(seconds * 1000 * speed))
            t, fade, leaving = 0, F.FADE, False
            while fade:
                if advance() or time.ticks_diff(time.ticks_ms(), start) >= duration:
                    leaving = True
                if leaving:
                    fade -= 1
                scene.frame(fb, t, pal)
                # Original draw operations already marked any caption tiles
                # they touched dirty. Restoring fixed bytes adds no new views.
                fb.buffer[CAPTION_OFFSET:] = caption
                fb.flush(16)
                play()
                F._pack(raw, pal, min(16, t * 16 // F.FADE, fade * 16 // F.FADE))
                d.write_memory(R.VRAM_PALETTE_BASE, raw)
                d.commit(wait=False)
                t += 1
            caption = scene = None
    finally:
        if music is not None:
            music.stop()
