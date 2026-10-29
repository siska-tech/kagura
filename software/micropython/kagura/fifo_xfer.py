# SPDX-License-Identifier: Apache-2.0
"""Optional RP2040 FIFO pump; leaves the PIO program and CS owner unchanged.

Install Pump once per transport. transfer has PIOTransport._xfer's signature.
Only byte buffers use the native path; other buffers retain Python semantics.
The caller still owns READY, CS, DMA abort and exception recovery.
"""
from array import array
from time import ticks_us, ticks_diff, sleep_ms
import sys
import micropython


if sys.implementation.name == 'micropython':
    @micropython.viper
    def pump(tx, rx, settings) -> int:
        source = ptr8(tx)
        destination = ptr8(rx)
        c = ptr32(settings)
        registers = ptr32(c[0])
        sm = int(c[1])
        n = int(c[2])
        shift = int(c[3])
        flags = int(c[4])
        offset = int(c[5])
        increment = int(c[6])
        last = int(c[7])
        timeout = int(c[8])
        tx_length = int(c[10])
        rx_start = int(c[11])
        payload_start = int(c[12])
        sent = 0
        got = 0
        spins = 0
        progress = int(ticks_us())
        while got < n:
            status = uint(registers[1])
            if sent < n and (status & (uint(1) << (16 + sm))) == uint(0):
                value = uint(0)
                if flags & 1 and sent < tx_length:
                    value = uint(source[sent]) << shift
                current = offset
                if increment:
                    current = (offset + sent - payload_start) & 31
                if sent >= payload_start and (current == 7 or current == 8 or current == 14):
                    value |= uint(0x80000000)
                if sent == last:
                    value |= uint(0x40000000)
                registers[4 + sm] = value
                sent += 1
            if (uint(registers[1]) & (uint(1) << (8 + sm))) == uint(0):
                value = uint(registers[8 + sm]) & 255
                if got == 0:
                    c[13] = value
                if flags & 2 and got >= rx_start:
                    destination[got - rx_start] = value
                got += 1
                progress = int(ticks_us())
            spins += 1
            # Yield only occasionally. sleep_ms(0) services pending Ctrl-C on
            # RP2, including a PIO stalled indefinitely on the FPGA BUSY pin.
            if spins == 32:
                spins = 0
                sleep_ms(0)
                if int(ticks_diff(ticks_us(), progress)) >= timeout:
                    c[9] = uint(got - 1 if got else 0)
                    return 0
        return 1
else:
    pump = None


class Pump:
    def __init__(self, transport, timeout_type):
        if pump is None:
            raise RuntimeError('RP2040 Viper FIFO kernel unavailable')
        self.transport = transport
        self.timeout_type = timeout_type
        self.fallback = transport._xfer
        self.empty = bytearray(1)
        self.packet = bytearray(33)
        self.original_write = transport.write
        self.original_readinto = transport.readinto
        sm = transport._sm_id
        self.settings = array('I', [0x50200000 + (sm // 4) * 0x100000,
                                  sm % 4, 0, 23 if transport.lanes == 1 else 22,
                                  0, 32, 0, 0, transport.timeout_us, 0, 0, 0, 0, 0])

    def transfer(self, tx=None, rx=None, count=None, offset=None, inc=False,
                 release_last=False):
        if (tx is not None and getattr(tx, 'itemsize', 1) != 1 or
                rx is not None and getattr(rx, 'itemsize', 1) != 1):
            return self.fallback(tx, rx, count, offset, inc, release_last)
        n = len(tx) if tx is not None else (len(rx) if rx is not None else count)
        if rx is not None and n > len(rx):
            return self.fallback(tx, rx, count, offset, inc, release_last)
        if rx is not None and n and not isinstance(rx, bytearray):
            rx[0] = rx[0]  # Validate writable views before acquiring a pointer.
        c = self.settings
        c[2] = n
        c[4] = (1 if tx is not None else 0) | (2 if rx is not None else 0)
        c[5] = 32 if offset is None else offset
        c[6] = int(inc)
        c[7] = n - 1 if self.transport.lanes == 4 and release_last and n else 0xffffffff
        c[8] = self.transport.timeout_us
        c[10], c[11], c[12] = n, 0, 0
        if not pump(tx if tx is not None else self.empty,
                    rx if rx is not None else self.empty, c):
            raise self.timeout_type(c[9])

    def _packet(self, tx, rx, n, tx_length, rx_start, payload_start,
                offset=32, inc=False, release=False):
        c = self.settings
        c[2], c[4], c[5], c[6] = n, 1 | (2 if rx is not None else 0), offset, int(inc)
        c[7] = 1 if release else 0xffffffff
        c[8] = self.transport.timeout_us
        c[10], c[11], c[12] = tx_length, rx_start, payload_start
        if not pump(tx, rx if rx is not None else self.empty, c):
            # Completed is relative to this transaction's payload, not header.
            prefix = rx_start if rx is not None else payload_start
            raise self.timeout_type(max(0, c[9] - prefix))
        if self.transport.lanes == 1:
            self.transport.last_fifo_status = c[13]

    def write(self, offset, data, inc=False):
        raw = self.transport
        if not 0 <= offset <= 31:
            raise ValueError('register offset')
        if (getattr(data, 'itemsize', 1) != 1 or len(data) > 32 or
                not inc and len(data) >= 16 and raw._dma_tx is not None):
            return self.original_write(offset, data, inc)
        if raw._closed or raw._active:
            raise RuntimeError('transport closed or already in use')
        packet = self.packet
        packet[0] = (0x40 if inc else 0) | offset
        for j in range(len(data)):
            packet[j + 1] = data[j]
        try:
            raw._begin()
            self._packet(packet, None, len(data) + 1, len(data) + 1, 0, 1, offset, inc)
            raw._end()
        except BaseException:
            raw._abort()
            raise

    def readinto(self, offset, buffer, inc=False):
        raw = self.transport
        if not 0 <= offset <= 31 or not 1 <= len(buffer) <= 256:
            raise ValueError('register offset or read length (1..256)')
        if getattr(buffer, 'itemsize', 1) != 1:
            return self.original_readinto(offset, buffer, inc)
        if not isinstance(buffer, bytearray):
            buffer[0] = buffer[0]
        if raw._closed or raw._active:
            raise RuntimeError('transport closed or already in use')
        packet = self.packet
        packet[0], packet[1] = 0x80 | (0x40 if inc else 0) | offset, len(buffer) & 255
        try:
            raw._begin()
            self._packet(packet, buffer, len(buffer) + 3, 2, 3, len(buffer) + 3,
                         release=raw.lanes == 4)
            raw._end()
        except BaseException:
            raw._abort()
            raise
