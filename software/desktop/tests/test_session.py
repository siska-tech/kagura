# SPDX-License-Identifier: Apache-2.0
"""kagura.desktop (the hardware session) against a recording fake device.

Checks what the session writes to the KAGURA-9: BG map (rows 0..24 point at
patterns 0..999, every other cell at the blank pattern 1000), no high-bank
cells, palette bank, SCROLL_Y 236, BACKDROP, display enable after the first
frame; that the patterns it sends always equal the desktop's TILE4 image;
that a failing device leaves the console resumed; and close() hands the
screen back to the console.

  MICROPYPATH=software/micropython micropython software/desktop/tests/test_session.py
"""
import sys

from kagura import regs as R
from kagura.desktop import Desktop, PALETTE

failed = 0


class FakeDevice:
    abi, height, caps = (0, 6), 240, 0x5B

    def require(self, mask):
        assert self.caps & mask == mask

    def wait_status(self, mask, value):
        pass

    def __init__(self, fail_after=None):
        self.busy = 0
        self.vram = bytearray(0x10000)
        self.ext = {R.EXT_PATTERN_COUNT_L: 1200 & 255, R.EXT_PATTERN_COUNT_H: 1200 >> 8}
        self.regs = {}
        self.writes = 0
        self.fail_after = fail_after

    def ext_read(self, i):
        return self.ext.get(i, 0)

    def ext_write(self, i, v):
        self.ext[i] = v

    def write_reg(self, r, v):
        self.regs[r] = v

    def commit(self, wait=True):
        pass

    def fence(self):
        pass

    def check_errors(self):
        pass

    def write_memory(self, address, data):
        self.writes += 1
        if self.fail_after is not None and self.writes > self.fail_after:
            raise OSError(5)
        self.vram[address:address + len(data)] = data


class FakeConsole:
    def __init__(self, device):
        self.screen = type('S', (), {'device': device})()
        self.paused = False
        self.resumed = 0

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        self.resumed += 1


def check(cond, what):
    global failed
    if not cond:
        failed += 1
        print('FAIL', what)


def word(vram, col, row):
    a = 0x8000 + row * 128 + col * 2
    return vram[a] | vram[a + 1] << 8


def test_setup_and_frames():
    dev = FakeDevice()
    con = FakeConsole(dev)
    desk = Desktop(console=con, menus=(('ファイル', ('開く',)),))
    check(con.paused, 'console paused while the desktop is open')
    check(word(dev.vram, 0, 0) == 0 and word(dev.vram, 39, 24) == 999, 'map rows 0..24 -> patterns 0..999')
    check(all(word(dev.vram, c, r) == 1000 for r in range(32) for c in range(64) if r >= 25 or c >= 40),
          'other cells -> blank pattern 1000')
    check(dev.vram[0x9000:0x9100] == bytes(256), 'no high-bank cells')
    check(dev.vram[1000 * 32:1001 * 32] == bytes(32), 'blank pattern is colour 0')
    check(all(dev.vram[0x9400 + 2 * i] | dev.vram[0x9401 + 2 * i] << 8 == PALETTE[i] for i in range(16)), 'palette')
    check(dev.ext.get(R.EXT_SCROLL_Y) == 236 and dev.ext.get(R.EXT_BACKDROP) == 0, 'scroll and backdrop')
    check(dev.regs.get(R.REG_DISPLAY_CTRL) == 3, 'display on after the first frame')
    image = bytearray(32000)
    desk.tile4(image)
    check(dev.vram[:32000] == image, 'first frame: every pattern sent')
    w = desk.create_window('神楽デスクトップ', 20, 30, 200, 100)
    w.text(8, 8, 'こんにちは', 1)
    tiles = desk.present()
    desk.tile4(image)
    check(tiles > 0 and dev.vram[:32000] == image, 'updates: changed patterns sent')
    check(desk.present() == 0, 'nothing to send when idle')
    desk.close()
    check(not con.paused and con.resumed == 1, 'console resumed on close')
    desk.close()
    check(con.resumed == 1, 'close twice is harmless')


def test_failure_releases():
    dev = FakeDevice(fail_after=10)
    con = FakeConsole(dev)
    try:
        Desktop(console=con)
        check(False, 'a failing device raises')
    except OSError:
        pass
    check(not con.paused and con.resumed == 1, 'console resumed after a failed start')


def test_wrong_mode():
    dev = FakeDevice()
    dev.height = 480
    try:
        Desktop(device=dev)
        check(False, 'wrong mode rejected')
    except ValueError:
        pass


for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith('test_')):
    before = failed
    fn()
    print('%-4s %s' % ('ok' if failed == before else 'FAIL', name[5:]))
print('session tests, %d failed' % failed)
sys.exit(1 if failed else 0)
