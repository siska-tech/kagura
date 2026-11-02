# SPDX-License-Identifier: Apache-2.0
"""VM calibration loops, timed on the RP2040 with its installed MicroPython
(tools/rp2040_vm_calibrate.py): the cost of the interpreter itself, running
from XIP flash. Pure VM and py/ built-ins only, no allocation.

loops(n, begin, end) brackets each loop with begin()/end().
"""


def loops(n, begin, end):
    def f(a, b):
        return a

    s = 'abcdefgh'
    b = bytearray(16)
    begin()
    for i in range(n):
        pass
    end()
    begin()
    for i in range(n):
        f(i, i)
    end()
    begin()
    for i in range(n):
        s.find('g', 1, 8)
    end()
    begin()
    for i in range(n):
        b[i & 15] = i & 255
    end()


NAMES = ('empty loop', 'Python call, 2 args', "str.find('g', 1, 8)", 'bytearray store')
