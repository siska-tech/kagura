# SPDX-License-Identifier: Apache-2.0
"""PIO FIFO semantics, not an emulation of hardware timing or performance."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'kagura/fifo_xfer.py'


class Registers:
    def __init__(self, sm, shift, receive=True):
        self.sm, self.shift, self.receive = sm, shift, receive
        self.words, self.rx = [], []

    def __getitem__(self, index):
        if index == 1:
            return (0 if self.rx else 1 << (8 + self.sm))
        if index == 8 + self.sm:
            return self.rx.pop(0)
        raise AssertionError(index)

    def __setitem__(self, index, value):
        assert index == 4 + self.sm
        self.words.append(value)
        if self.receive:
            self.rx.append((value >> self.shift) & 255)


def kernel(registers, interrupt=False):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'pump')
    function.decorator_list = []
    clock = [0]
    def tick():
        clock[0] += 1
        return clock[0]
    def sleep(ms):
        if interrupt:
            raise KeyboardInterrupt
    namespace = dict(ptr8=lambda b: b,
                     ptr32=lambda p: registers if isinstance(p, int) else p,
                     uint=int, ticks_us=tick, ticks_diff=lambda a,b:a-b,
                     sleep_ms=sleep)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(SOURCE), 'exec'), namespace)
    return namespace['pump']


class FifoTests(unittest.TestCase):
    def test_wire_words_flags_and_receive(self):
        for lanes in (1, 4):
            for sm in range(4):
                for inc in (False, True):
                    shift = 23 if lanes == 1 else 22
                    r = Registers(sm, shift)
                    source = bytes(range(64))
                    output = bytearray(64)
                    c = [0x50200000, sm, 64, shift, 3, 7, int(inc), 63 if lanes == 4 else 0xffffffff, 100, 0, 64, 0, 0, 0]
                    self.assertEqual(kernel(r)(source, output, c), 1)
                    self.assertEqual(output, source)
                    for j, word in enumerate(r.words):
                        offset = (7+j)&31 if inc else 7
                        self.assertEqual(word, (j<<shift) | (0x80000000 if offset in (7,8,14) else 0) |
                                         (0x40000000 if lanes == 4 and j==63 else 0))

    def test_read_packet_dummy_and_release(self):
        r = Registers(0, 22)
        c = [0x50200000, 0, 7, 22, 3, 32, 0, 1, 100, 0, 2, 3, 7, 0]
        out = bytearray(4)
        self.assertEqual(kernel(r)(bytes((0x98, 4)), out, c), 1)
        self.assertEqual(out, bytes(4))
        self.assertEqual(r.words, [0x98 << 22, (4 << 22) | 0x40000000] + [0]*5)
        self.assertEqual(c[13], 0x98)

    def test_write_packet_header_never_queued(self):
        r = Registers(0, 23)
        c = [0x50200000, 0, 3, 23, 1, 7, 1, 0xffffffff, 100, 0, 3, 0, 1, 0]
        self.assertEqual(kernel(r)(b'\x47\xaa\xbb', bytearray(1), c), 1)
        self.assertEqual(r.words, [0x47 << 23, (0xaa << 23) | 0x80000000, (0xbb << 23) | 0x80000000])

    def test_stalled_timeout_and_ctrl_c(self):
        for interrupt in (False, True):
            r = Registers(0, 22, receive=False)
            c = [0x50200000, 0, 1, 22, 1, 7, 0, 0xffffffff, 10, 99, 1, 0, 0, 0]
            if interrupt:
                with self.assertRaises(KeyboardInterrupt):
                    kernel(r, True)(b'x', bytearray(1), c)
            else:
                self.assertEqual(kernel(r)(b'x', bytearray(1), c), 0)
                self.assertEqual(c[9], 0)


if __name__ == '__main__':
    unittest.main()
