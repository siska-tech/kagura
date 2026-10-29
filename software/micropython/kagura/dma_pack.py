# SPDX-License-Identifier: Apache-2.0
"""Optional RP2 Viper byte-to-PIO-word expansion, preserving the wire format."""
import sys
from time import ticks_us, ticks_diff


def python_pack(data, high, words, start, count):
    j = 1
    for k in range(start, start + count):
        words[j] = high[data[k]]
        j += 2


# @micropython.viper is compiler syntax, not a runtime module attribute.
# CPython host tests deliberately take the reference implementation instead.
viper_pack = viper_pack32 = None
native_error = None
if sys.implementation.name == 'micropython':
    try:
        try:
            from .dma_pack_viper import viper_pack, viper_pack32
        except ImportError:
            from kagura_dma_pack_viper import viper_pack, viper_pack32
    except (ImportError, SyntaxError, ValueError) as error:
        # Missing helper, unsupported emitter, or incompatible native .mpy.
        native_error = repr(error)


def pack(data, high, words, start, count):
    # Transport.write passes a memoryview. Preserve the old element-wise
    # behavior for multi-byte buffers rather than reinterpreting their bytes.
    if viper_pack is not None and getattr(data, 'itemsize', 1) == 1:
        viper_pack(data, high, words, start, count)
    else:
        python_pack(data, high, words, start, count)


def pack32(data, high, words, start, count):
    """Full-word variant for zero-low-half DMA workspaces, not arbitrary arrays."""
    if viper_pack32 is not None and getattr(data, 'itemsize', 1) == 1:
        viper_pack32(data, high, words, start, count)
    else:
        python_pack(data, high, words, start, count)


def transfer(transport, data, queued, timeout_type, chunk=128, packer=None):
    """Shared, unchanged DMA handshake; also bridges older frozen drivers.

    The caller's write() still owns CS, exception recovery, and DMA abort.
    The byte-expansion kernel is the only accelerated operation here.
    """
    high, words = transport._high[queued], transport._words
    tx, rx = transport._dma_tx, transport._dma_rx
    if packer is None:
        packer = pack
    n, done = len(data), 0
    while done < n:
        m = min(chunk, n - done)
        packer(data, high, words, done, m)
        rx.config(read=transport._sm, write=transport._sink, count=m,
                  ctrl=transport._rx_ctrl, trigger=True)
        tx.config(read=words, write=transport._sm, count=m,
                  ctrl=transport._tx_ctrl, trigger=True)
        left = m
        progress = ticks_us()
        while rx.active():
            count = rx.count
            if count != left:
                left = count
                progress = ticks_us()
            elif ticks_diff(ticks_us(), progress) >= transport.timeout_us:
                raise timeout_type(done + max(0, m - left - 1))
        done += m
