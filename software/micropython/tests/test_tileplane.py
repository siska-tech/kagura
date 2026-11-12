# SPDX-License-Identifier: Apache-2.0
"""kagura.tileplane.TilePlane against the queue-aware register model.

  python3 -I software/micropython/tests/test_tileplane.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import test_driver as T
from unittest import TestCase, main
from kagura import Kagura, DeviceError, regs as R
from kagura.tileplane import TilePlane

COLORS = tuple(range(0x100, 0x110))


def word(memory, col, row):
    a = 0x8000 + row * 128 + col * 2
    return memory[a] | memory[a + 1] << 8


class RecordingLink:
    """Stands in for kagura.link.Link (transport.accelerate())."""
    def __init__(self, model):
        self.model, self.calls = model, []

    def write_memory(self, address, data, timeout_us):
        self.calls.append(('write', address, bytes(data)))
        self.model.memory[address:address + len(data)] = data

    def fence(self, timeout_us):
        self.calls.append(('fence',))


class TilePlaneTests(TestCase):
    def setUp(self):
        self.model = T.RegisterModel()
        self.model.ext[R.EXT_SCREEN_HEIGHT] = 240
        self.model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
        self.model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
        self.d = Kagura(self.model).probe()

    def test_desktop_layout(self):
        # 40x25 centred: rows 0..24 hold patterns 0..999 on lines 20..219.
        plane = TilePlane(self.d, 40, 25, palette=2, colors=COLORS)
        self.model.memory[1000 * 32:1001 * 32] = b'\xff' * 32
        plane.open()
        m = self.model.memory
        self.assertEqual(self.model.reg[R.REG_DISPLAY_CTRL], 0)
        self.assertEqual(plane.blank, 1000)
        bank = 2 << 10
        self.assertEqual(word(m, 0, 0), bank)
        self.assertEqual(word(m, 39, 24), bank | 999)
        self.assertTrue(all(word(m, c, r) == bank | 1000 for r in range(32) for c in range(64)
                            if r >= 25 or c >= 40))
        self.assertEqual(m[0x9000:0x9100], bytes(256))
        self.assertEqual(m[1000 * 32:1001 * 32], bytes(32))
        self.assertEqual([m[0x9440 + 2 * i] | m[0x9441 + 2 * i] << 8 for i in range(16)], list(COLORS))
        e = self.model.ext
        self.assertEqual((e[R.EXT_SCROLL_X_L] | e[R.EXT_SCROLL_X_H] << 8, e[R.EXT_SCROLL_Y]), (0, 236))
        self.assertEqual(e[R.EXT_BACKDROP], 32)
        self.assertEqual(e[R.EXT_RS_COUNT], 0)
        frame = bytes(range(256)) * 125
        plane.write(0, frame)
        plane.show()
        self.assertEqual(self.model.reg[R.REG_DISPLAY_CTRL],
                         R.DISPLAY_CTRL_DISPLAY_ENABLE | R.DISPLAY_CTRL_BG_ENABLE)
        self.assertEqual(m[:32000], frame)
        back = bytearray(64)
        plane.read(998, back)
        self.assertEqual(back, frame[998 * 32:])
        self.assertEqual(plane.error_code(), 0)
        plane.hide()
        self.assertEqual(self.model.reg[R.REG_DISPLAY_CTRL], 0)

    def test_placement(self):
        plane = TilePlane(self.d, 10, 4, left=16, top=8)
        plane.open()
        e = self.model.ext
        self.assertEqual((e[R.EXT_SCROLL_X_L] | e[R.EXT_SCROLL_X_H] << 8, e[R.EXT_SCROLL_Y]),
                         (512 - 16, 256 - 8))
        self.assertEqual(word(self.model.memory, 9, 3), 39)
        self.assertEqual(word(self.model.memory, 10, 0), 40)
        centred = TilePlane(self.d, 20, 10)
        self.assertEqual((centred.left, centred.top), (80, 80))

    def test_runs_are_fenced_and_bounded(self):
        plane = TilePlane(self.d, 40, 25)
        plane.open()
        self.model.calls.clear()
        with plane:
            self.assertEqual(self.d.busy, 1)
            plane.write(5, bytes(range(64)))
            plane.check()
        self.assertEqual(self.d.busy, 0)
        self.assertEqual(self.model.memory[160:224], bytes(range(64)))
        fences = [c for c in self.model.calls if c[0] == R.REG_COMMAND and c[1] == bytes((R.CMD_FENCE,))]
        self.assertEqual(len(fences), 1)
        for first, data in ((-1, bytes(32)), (999, bytes(64)), (0, bytes(31)), (1000, bytes(32))):
            with self.assertRaises(ValueError):
                plane.write(first, data)
        with self.assertRaises(ValueError):
            plane.read(999, bytearray(33))

    def test_accelerated_link(self):
        link = RecordingLink(self.model)
        self.model.link = link
        plane = TilePlane(self.d, 40, 25)
        plane.write(3, bytes(range(96)))
        self.assertEqual(link.calls, [('write', 96, bytes(range(96))), ('fence',)])

    def test_check_raises_on_error_code(self):
        plane = TilePlane(self.d, 40, 25)
        self.model.reg[R.REG_ERROR_CODE] = R.ERROR_CODE_INVALID_ADDRESS
        with self.assertRaises(DeviceError):
            plane.check()

    def test_rejects_bad_configurations(self):
        for args in ((0, 25), (41, 25), (40, 31), (40, 26), (32, 32)):
            with self.assertRaises(ValueError):
                TilePlane(self.d, *args)
        with self.assertRaises(ValueError):
            TilePlane(self.d, 40, 25, colors=(0,) * 15)
        with self.assertRaises(ValueError):
            TilePlane(self.d, 40, 25, top=41)
        self.model.ext[R.EXT_PATTERN_COUNT_L] = 0
        with self.assertRaises(ValueError):
            TilePlane(self.d, 40, 25).open()
        self.model.ext[R.EXT_SCREEN_HEIGHT] = 180
        with self.assertRaises(ValueError):
            TilePlane(Kagura(self.model).probe(), 40, 25)


if __name__ == '__main__':
    main()
