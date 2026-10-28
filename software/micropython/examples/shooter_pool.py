# SPDX-License-Identifier: Apache-2.0
"""Fixed-capacity structure-of-arrays storage; life=0 is a free slot."""
from array import array


class Pool:
    def __init__(self, size):
        self.size = size
        self.x = array('h', [0] * size)
        self.y = array('h', [0] * size)
        self.vx = array('h', [0] * size)
        self.vy = array('h', [0] * size)
        self.base = array('h', [0] * size)
        self.phase = array('h', [0] * size)
        self.kind = bytearray(size)
        self.life = array('h', [0] * size)

    def spawn(self, x, y, vx=0, vy=0, life=1, kind=0, phase=0):
        for i in range(self.size):
            if not self.life[i]:
                self.x[i], self.y[i] = x, y
                self.vx[i], self.vy[i] = vx, vy
                self.base[i], self.phase[i] = y, phase
                self.kind[i], self.life[i] = kind, life
                return i
        return -1

    def clear(self):
        for i in range(self.size):
            self.life[i] = 0
