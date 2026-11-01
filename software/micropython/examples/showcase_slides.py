# SPDX-License-Identifier: Apache-2.0
"""Stream/COPY presentation cards. Unloaded before RAM-heavy live exhibits."""
import time
from kagura import regs as R
from kagura.image256 import Slots
from kagura.video import Video

SLIDES = ('opening', 'architecture', 'colour', 'game', 'orchestra', 'create', 'closing')


class _Surface:
    """Private buffer-free adapter for Slots.save_file/show, never save/flush."""
    palette = 0
    initialized = False

    def __init__(self, d):
        self.device = d
        self.dirty = bytearray(1200)


class Deck:
    def __init__(self, d):
        self.d, self.surface = d, _Surface(d)
        self.slots = Slots(self.surface)

    def restore(self):
        d = self.d
        d.wait_status(R.STATUS_COMMIT_BUSY, 0)
        d.write_reg(R.REG_DISPLAY_CTRL, 0)
        d.commit()
        high = bytearray(256)
        for tile in range(1024, 1200):
            cell = tile // 40 * 64 + tile % 40
            high[cell // 8] |= 1 << (cell & 7)
        d.fill(R.VRAM_OAM_BASE, R.VRAM_OAM_SIZE, 0)
        d.write_memory(R.VRAM_MAP_EXT_BASE, high)
        video = Video(d)
        video.scroll(0, 0)
        video.raster_scroll(())
        d.ext_write(R.EXT_BACKDROP, 0)
        d.fence()
        self.surface.initialized = True
        self.slots.current = None

    def show(self, slot):
        self.slots.show(slot)
        self.d.write_reg(R.REG_DISPLAY_CTRL, 3)
        self.d.commit()

    def load(self, assets, advance):
        self.restore()
        for slot, name in enumerate(SLIDES):
            advance()
            self.slots.save_file(slot, assets + '/' + name + '.kimg')
            if slot == 0:
                self.show(0)
            print('SHOWCASE slide ready', name)


def preload(d, advance, assets):
    Deck(d).load(assets, advance)


def run(d, advance, assets, cards, speed):
    import showcase_music
    deck, music = Deck(d), None
    try:
        # The launcher already streamed every slot. Reconstruct only tiny
        # metadata, not a framebuffer, after returning from other demos.
        deck.slots.saved.update(range(len(SLIDES)))
        deck.restore()
        music = showcase_music.Music(d)
        for slot, seconds in cards:
            print('SHOWCASE card', SLIDES[slot])
            deck.show(slot)
            end = time.ticks_add(time.ticks_ms(), max(1, int(seconds * 1000 * speed)))
            if slot == 3:
                # Import native game code while its introduction is visible;
                # the held PSG chord continues in hardware during USB reads.
                music.play()
                import starfall
                print('SHOWCASE game code ready')
            while time.ticks_diff(end, time.ticks_ms()) > 0:
                if advance():
                    break
                music.play()
                time.sleep_ms(10)
    finally:
        if music is not None:
            music.stop()
