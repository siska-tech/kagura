# SPDX-License-Identifier: Apache-2.0
"""Reversible RP2040 acceleration: installs kagura.link on a PIOTransport.

PIOTransport.accelerate(), which connect() calls, owns the session. With the
Viper link kernels and DMA available, transport.write/readinto and the
Kagura and TileFramebuffer operations become one Viper call each (see
kagura/link.py). Without them the transport is left untouched, enabled is
False and reason says why. Close only after outstanding transfers have
returned; the plain Python transport then takes over again.
"""
try:
    from . import link as link_module
except ImportError:
    link_module = None   # older frozen packages have no kagura.link


class Acceleration:
    def __init__(self, transport, timeout_type, chunk=128):
        if chunk not in (128, 256, 512):
            raise ValueError('DMA chunk must be 128, 256 or 512')
        if transport._active or transport._closed:
            raise RuntimeError('transport closed or already in use')
        self.transport, self.chunk = transport, chunk
        self.closed = False
        self.enabled = False
        self.reason = ''
        self.previous = {}
        self.link = None
        if link_module is None or link_module.kernels is None:
            error = link_module.native_error if link_module is not None else None
            self.reason = 'Viper link kernels unavailable' + (': ' + error if error else '')
            return
        if transport._dma_tx is None:
            self.reason = 'DMA unavailable'
            return
        for name in ('write', 'readinto', 'link'):
            self.previous[name] = transport.__dict__.get(name)
        try:
            # Link allocates its buffers before the transport changes hands and
            # keeps the plain write/readinto for buffers of wider items.
            self.link = link_module.Link(transport, timeout_type, chunk)
            transport.write = self.link.write
            transport.readinto = self.link.readinto
            transport.link = self.link
            self.enabled = True
        except BaseException:
            self.close()  # Also restore a partially installed session.
            raise

    def close(self):
        if self.closed:
            return
        if not self.previous:
            self.closed = True
            return  # Unavailable kernels never touched the transport.
        raw = self.transport
        if raw._active or (not raw._closed and (raw._dma_tx.active() or raw._dma_rx.active())):
            raise RuntimeError('cannot disable acceleration during a transfer')
        for name, previous in self.previous.items():
            if previous is None:
                if name in raw.__dict__:
                    delattr(raw, name)
            else:
                setattr(raw, name, previous)
        self.enabled = False
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
