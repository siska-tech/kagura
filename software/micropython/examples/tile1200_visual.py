# SPDX-License-Identifier: Apache-2.0
"""Interactive Pico visual acceptance. Leaves the scene active for observation."""
import gc
import framebuf
import json
import os
import kagura1200 as K
from kagura1200 import regs as R, dma_pack
from kagura1200.video import Video
from kagura1200.audio import Audio


def pattern(n):
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            color = 0 if x == 0 or y == 0 else 1 + ((n + x // 2 + y // 2) % 14)
            if y in (2, 4) and 1 <= x <= 6:
                color = 15 if n & (1 << ((y // 2 - 1) * 6 + x - 1)) else 1
            i = y * 4 + x // 2
            out[i] |= color << (4 if x % 2 == 0 else 0)
    return out


class Scene:
    def __init__(self):
        dma_pack.viper_pack = dma_pack.viper_pack32 = None
        self.d = K.connect(mode='qspi', baudrate=5_000_000)
        self.v, self.a = Video(self.d), Audio(self.d)
        self.words, self.upper = bytearray(4096), bytearray(256)
        self.d.write_reg(R.REG_DISPLAY_CTRL, 0)
        self.d.commit()
        self.d.fill(0xA000, 2048)
        self.v.scroll(0, 0)
        self.v.raster_scroll(())
        for first in range(0, 1200, 16):
            self.v.tiles(first, b''.join(pattern(n) for n in range(first, min(first + 16, 1200))))
        self.v.tile(0, bytes(32))
        bitmap = framebuf.FrameBuffer(bytearray(8), 8, 8, framebuf.MONO_HLSB)
        for code in range(32, 127):
            bitmap.fill(0)
            bitmap.text(chr(code), 0, 0, 1)
            tile = bytearray(32)
            for y in range(8):
                for x in range(8):
                    if bitmap.pixel(x, y):
                        tile[y * 4 + x // 2] |= 15 << (4 if x % 2 == 0 else 0)
            self.v.tile(code, tile)
        # An asymmetric arrow makes flips easy to distinguish on the next page.
        arrow = (0x00, 0x10, 0x30, 0x7E, 0x30, 0x10, 0x00, 0x00)
        tile = bytearray(32)
        for y, row in enumerate(arrow):
            for x in range(8):
                if row & (128 >> x):
                    tile[y * 4 + x // 2] |= 15 << (4 if x % 2 == 0 else 0)
        self.v.tile(1199, tile)
        colors = (0x000, 0x222, 0xF33, 0xF93, 0xFF3, 0x3F3, 0x3F9, 0x3FF,
                  0x39F, 0x33F, 0x93F, 0xF3F, 0xF39, 0xAAA, 0xDDD, 0xFFF)
        for palette in range(4):
            for index, color in enumerate(colors):
                if index == 15:
                    color = (0xFFF, 0xF33, 0x3F3, 0x39F)[palette]
                self.v.palette(palette * 16 + index, color)
        for c in range(6):
            self.a.stop(c)
        self.d.audio_write(R.AUDIO_MASTER_GAIN, 64)
        self.d.audio_commit()
        for channel, address, period in ((0, 0x400000, 128), (1, 0x410000, 64)):
            half = period // 2
            cycle = bytes((((i if i < half else period - 1 - i) * (256 // half)) - 128) & 255 for i in range(period))
            sample = cycle * (4096 // period)
            self.d.write_memory(address, sample)
            self.d.fence()
            self.a.prepare_pcm(channel, address, address + len(sample), loop=address)
            self.a.play_pcm(channel, left=12 if channel == 0 else 0,
                            right=12 if channel == 1 else 0)
        self.page(0)

    def cell(self, x, y, tile, palette=0, h=False, v=False):
        index = y * 64 + x
        word = (tile & 1023) | (palette << 10) | (int(h) << 14) | (int(v) << 15)
        self.words[index * 2] = word & 255
        self.words[index * 2 + 1] = word >> 8
        mask = 1 << (index % 8)
        self.upper[index // 8] = (self.upper[index // 8] & ~mask) | ((tile >> 10) << (index % 8))

    def text(self, x, y, value, palette=0):
        for c in value:
            self.cell(x, y, ord(c), palette)
            x += 1

    def page(self, number):
        self.d.write_reg(R.REG_DISPLAY_CTRL, 0)
        self.d.commit()
        self.words[:] = bytes(4096)
        self.upper[:] = bytes(256)
        self.d.fill(0xA000, 2048)
        self.text(0, 0, 'KAGURA-9  1200 TILES  ABI 0.6')
        if number == 0:
            self.text(0, 2, 'EXTRA 176 TILES: 1024..1199')
            for row in range(11):
                first = 1024 + row * 16
                for col in range(16):
                    self.cell(2 + col, 4 + row, first + col)
                self.text(20, 4 + row, '%04d-%04d' % (first, first + 15))
            self.text(0, 17, 'LAST 1199:')
            self.cell(12, 17, 1199)
            self.text(0, 18, 'INVALID 1200/2047:')
            self.text(23, 18, '[ ] [ ]')
            self.cell(24, 18, 1200)
            self.cell(28, 18, 2047)
        else:
            self.text(0, 2, 'BG BOUNDARIES     SPRITES')
            for row, tile in enumerate((1023, 1024, 1087, 1088, 1151, 1152, 1199)):
                y = 4 + row * 2
                self.text(0, y, '%04d' % tile)
                self.cell(7, y, tile)
                self.v.sprite(row, 176, y * 8, tile=tile)
            self.text(0, 18, '1199 FLIPS: N H V HV')
            for col, flags in enumerate(((False, False), (True, False), (False, True), (True, True))):
                self.cell(24 + col * 3, 18, 1199, col, *flags)
        self.text(0, 20, 'PCM: LEFT 375Hz / RIGHT 750Hz')
        self.text(0, 21, 'VISUAL/AUDIO: AWAITING YOUR CHECK')
        self.d.write_memory(0x8000, self.words)
        self.d.write_memory(0x9000, self.upper)
        self.d.write_reg(R.REG_DISPLAY_CTRL, 7)
        self.d.commit()
        self.d.fence()
        self.d.check_errors()
        print('VISUAL1200_READY ' + json.dumps(dict(page=number, abi=list(self.d.abi),
              height=self.d.height, error=self.d.read_reg(R.REG_ERROR_CODE),
              pcm=[self.a.pcm_status(c) for c in (0, 1)], uname=list(os.uname()),
              visual_verified=False, audio_quality_verified=False)))
        gc.collect()

    def close(self):
        for c in (0, 1):
            base = R.AUDIO_PCM_BASE + c * R.AUDIO_PCM_STRIDE
            self.d.audio_write(base + R.AUDIO_PCM_CONTROL, 0)
            self.d.audio_write(base + R.AUDIO_PCM_CMD, R.AUDIO_PCM_CMD_STOP)
        self.d.audio_commit()
        self.d.deinit()
