# SPDX-License-Identifier: Apache-2.0
"""Reversible RP2040 acceleration for any single-owner KAGURA application.

Works with stock MicroPython and optional ARMv6-M .mpy modules. No PIO or
firmware change. Close only after outstanding transfers have returned.
"""
from array import array
try:
    from . import dma_pack, fifo_xfer
except ImportError:
    # Older UF2s freeze the original package; install these helpers at root.
    import kagura_dma_pack as dma_pack
    import kagura_fifo_xfer as fifo_xfer


class Acceleration:
    def __init__(self, transport, timeout_type, fifo=True, chunk=128, packer=None):
        if chunk not in (128, 256, 512):
            raise ValueError('DMA chunk must be 128, 256 or 512')
        if transport._active or transport._closed:
            raise RuntimeError('transport closed or already in use')
        self.transport = transport
        self.closed = False
        self.enabled = False
        self.reason = ''
        self.previous = {}
        self.pump = None
        if dma_pack.viper_pack is None or dma_pack.viper_pack32 is None:
            self.reason = 'Viper DMA kernel unavailable'
            return
        if fifo and fifo_xfer.pump is None:
            self.reason = 'Viper FIFO kernel unavailable'
            return
        if transport._dma_tx is None:
            self.reason = 'DMA unavailable'
            return
        self.words = transport._words
        for name in ('_xfer', 'write', 'readinto', '_xfer_dma'):
            self.previous[name] = transport.__dict__.get(name)
        # Allocate before changing the transport. Buffers remain owned until
        # synchronous DMA completion; no pointer outlives this object.
        words = self.words if chunk == 128 else array('H', [0] * (2 * chunk))
        self.pump = fifo_xfer.Pump(transport, timeout_type) if fifo else None
        if packer is None:
            packer = dma_pack.pack32
        try:
            transport._words = words
            transport._xfer_dma = lambda data, queued: dma_pack.transfer(
                transport, data, queued, timeout_type, chunk, packer)
            if self.pump:
                transport._xfer = self.pump.transfer
                transport.write = self.pump.write
                transport.readinto = self.pump.readinto
            self.enabled = True
        except BaseException:
            self.close()  # Also restore a partially installed session.
            raise

    def close(self):
        if self.closed:
            return
        if not self.previous:
            self.closed = True
            return  # Unavailable native kernels never touched the transport.
        raw = self.transport
        if raw._active or (not raw._closed and (raw._dma_tx.active() or raw._dma_rx.active())):
            raise RuntimeError('cannot disable acceleration during a transfer')
        for name, previous in self.previous.items():
            if previous is None:
                if name in raw.__dict__:
                    delattr(raw, name)
            else:
                setattr(raw, name, previous)
        raw._words = self.words
        self.enabled = False
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
