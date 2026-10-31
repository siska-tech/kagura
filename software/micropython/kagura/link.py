# SPDX-License-Identifier: Apache-2.0
"""Whole transactions and operations in single Viper calls (RP2040).

On the RP2040 each Python statement costs microseconds, so the plain driver
spends about 1 ms per register access and 6 ms per FENCE in Python rather
than on the wire. transport.accelerate() installs a Link when its kernels
load: PIOTransport.write/readinto then run CS, pin direction, FIFOs and DMA
in one call each, and Kagura.write_memory/fence/commit/audio_commit/
wait_status and TileFramebuffer.flush become one call per operation.
Payloads of 64 bytes or more reach the PIO by DMA while the CPU packs the
next chunk (about 1 MB/s at QSPI 5 MHz).

Same PIO program, pins, word format, error checks and exceptions as the
Python driver; PIOTransport stays the owner and a failed transaction calls
its _abort(). Ctrl-C is serviced at least every 4 ms while waiting.
"""
import sys
from array import array
from time import ticks_us, ticks_diff
from .device import DeviceError

kernels = None
native_error = None
if sys.implementation.name == 'micropython':
    try:
        from . import link_viper as kernels
    except (ImportError, SyntaxError, ValueError, NotImplementedError) as error:
        native_error = repr(error)   # stock firmware without Viper: keep the Python path

# Settings word indices (link_viper.py documents them all).
_N, _FLAGS, _OFFSET, _INC, _LAST, _DONE = 2, 4, 5, 6, 7, 9
_TXLEN, _RXSTART, _PAYLOAD, _FIRST = 10, 11, 12, 13
_HLEN, _H0, _SRC, _LEN, _GAP, _STATS, _WAIT = 20, 21, 25, 26, 27, 28, 45
_STAT_NAMES = ('tiles', 'bytes', 'runs', 'writes', 'fences', 'transfer_us', 'wait_us')


class Link:
    def __init__(self, transport, timeout_type, chunk=128, cs=7, ready=9, k=None):
        """k overrides the kernel module (the PC tests run the source on a model)."""
        self.k = k or kernels
        if self.k is None:
            raise RuntimeError('Viper link kernels unavailable')
        if transport._dma_tx is None:
            raise RuntimeError('DMA unavailable')
        self.raw, self.timeout_type = transport, timeout_type
        # Buffers of wider items keep the transport's previous semantics.
        self.fallback_write, self.fallback_readinto = transport.write, transport.readinto
        sm = transport._sm_id
        base = 0x50200000 + (sm // 4) * 0x100000
        # Allocate everything before the transport changes hands.
        self.words, self.sink, self.buf = array('I', [0] * (2 * chunk)), bytearray(4), bytearray(4)
        c = self.c = array('I', [0] * 46)
        c[0], c[1], c[3] = base, sm % 4, 23 if transport.lanes == 1 else 22
        c[8] = transport.timeout_us
        c[14], c[15], c[16] = 1 << cs, 1 << ready, int(transport.lanes == 4)
        c[17], c[18], c[19] = transport._pins_out, transport._pins_in, transport._tail_us
        c[35], c[36] = transport._dma_tx.channel, transport._dma_rx.channel
        c[37], c[38] = transport._tx_ctrl, transport._rx_ctrl
        c[39], c[40] = self._address(self.words), self._address(self.sink)
        c[41], c[42] = chunk, 1
        c[43] = base + 0x10 + (sm % 4) * 4   # TXF
        c[44] = c[43] + 0x10                 # RXF

    @staticmethod
    def _address(buffer):
        import uctypes
        return uctypes.addressof(buffer)

    # Every kernel call goes through here: one owner at a time, the
    # transport's own recovery on any failure, the driver's exceptions.
    def _call(self, name, kernel, *args):
        raw = self.raw
        if raw._closed or raw._active:
            raise RuntimeError('transport closed or already in use')
        raw._active = True
        try:
            r = kernel(*args)
        except BaseException:
            raw._abort()   # e.g. KeyboardInterrupt mid-transfer: CS high, DMA off
            raise
        raw._active = False
        if r >= 0x100:
            raise DeviceError(r & 255)
        if r < 0:
            raw._abort()
            if r == -2:
                raise OSError('KAGURA is not READY (reset or disconnected)')
            if r == -3:
                raise OSError('KAGURA timeout: ' + name)
            raise self.timeout_type(self.c[_DONE])
        if raw.lanes == 1:
            raw.last_fifo_status = self.c[_FIRST]
        return r

    # PIOTransport.write/readinto replacements (same validation and results).
    def write(self, offset, data, inc=False):
        if not 0 <= offset <= 31:
            raise ValueError('register offset')
        if getattr(data, 'itemsize', 1) != 1:
            return self.fallback_write(offset, data, inc)
        header = (0x40 if inc else 0) | offset
        n = len(data)
        if n <= 3:
            value = 0
            for i in range(n):
                value |= data[i] << (8 * i)
            self._call('write', self.k._short, self.c, self.buf, header | n << 8, value)
            return
        c = self.c
        c[_N] = c[_TXLEN] = n + 1
        c[_FLAGS], c[_OFFSET], c[_INC], c[_LAST] = 0, offset, int(inc), 0xffffffff
        c[_RXSTART], c[_PAYLOAD], c[_HLEN], c[_H0], c[_SRC] = 0, 1, 1, header, 0
        self._call('write', self.k._xact, data, self.buf, c)

    def readinto(self, offset, buffer, inc=False):
        if not 0 <= offset <= 31 or not 1 <= len(buffer) <= 256:
            raise ValueError('register offset or read length (1..256)')
        if getattr(buffer, 'itemsize', 1) != 1:
            return self.fallback_readinto(offset, buffer, inc)
        if len(buffer) == 1 and not inc:
            buffer[0] = self._call('read', self.k._short, self.c, self.buf, 0x80 | offset, 0)
            return
        n, c = len(buffer), self.c
        c[_N], c[_TXLEN], c[_FLAGS], c[_OFFSET], c[_INC] = n + 3, 2, 2, offset, int(inc)
        c[_LAST] = 1 if self.raw.lanes == 4 else 0xffffffff
        c[_RXSTART], c[_PAYLOAD], c[_HLEN] = 3, n + 3, 2
        c[_H0], c[_H0 + 1], c[_SRC] = 0x80 | (0x40 if inc else 0) | offset, n & 255, 0
        self._call('read', self.k._xact, self.buf, buffer, c)

    # Kagura operations; the device validates arguments first.
    def write_memory(self, address, data, timeout_us):
        c = self.c
        c[_SRC], c[_LEN], c[_WAIT] = 0, len(data), timeout_us
        self._call('write_memory', self.k._write_memory, c, self.buf, address, data)

    def fence(self, timeout_us):
        self.c[_WAIT] = timeout_us
        self._call('FENCE', self.k._fence, self.c, self.buf)

    def wait_status(self, mask, value, timeout_us):
        self.c[_WAIT] = timeout_us
        self._call('STATUS', self.k._wait, self.c, self.buf, 0, mask << 8 | value)

    def commit(self, wait, timeout_us):
        self.c[_WAIT] = timeout_us
        self._call('STATUS', self.k._commit, self.c, self.buf, 3 | (0 if wait else 0x100))

    def audio_commit(self, timeout_us):
        self.c[_WAIT] = timeout_us
        self._call('AUDIO_COMMIT', self.k._commit, self.c, self.buf, 4)

    def ext_writes(self, pairs, count):
        self._call('ext', self.k._batch, self.c, self.buf, pairs, count, 0x0a)

    def audio_writes(self, pairs, count):
        self._call('audio', self.k._batch, self.c, self.buf, pairs, count, 0x0c)

    def flush(self, dirty, buffer, max_gap, stats, timeout_us):
        """Fill stats like TileFramebuffer._flush; exceptions leave unconfirmed runs dirty."""
        c = self.c
        c[_GAP], c[_WAIT] = max_gap, timeout_us
        for i in range(7):
            c[_STATS + i] = 0
        start = ticks_us()
        try:
            self._call('FENCE', self.k._flush, c, self.buf, dirty, buffer)
        finally:
            for i in range(7):
                stats[_STAT_NAMES[i]] = c[_STATS + i]
            stats['total_us'] = ticks_diff(ticks_us(), start)
