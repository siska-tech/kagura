# SPDX-License-Identifier: Apache-2.0
"""Optional RP2 Viper byte-to-PIO-word expansion, preserving the wire format."""
import micropython
import sys
from time import ticks_us, ticks_diff


def python_pack(data, high, words, start, count):
    j = 1
    for k in range(start, start + count):
        words[j] = high[data[k]]
        j += 2


# @micropython.viper is compiler syntax, not a runtime module attribute.
# CPython host tests deliberately take the reference implementation instead.
if sys.implementation.name == 'micropython':
    @micropython.viper
    def viper_pack(data, high, words, start: int, count: int):
        source = ptr8(data)
        table = ptr16(high)
        destination = ptr16(words)
        for j in range(count):
            destination[j * 2 + 1] = table[source[start + j]]
else:
    viper_pack = None

def pack(data, high, words, start, count):
    # Transport.write passes a memoryview. Preserve the old element-wise
    # behavior for multi-byte buffers rather than reinterpreting their bytes.
    if viper_pack is not None and getattr(data, 'itemsize', 1) == 1:
        viper_pack(data, high, words, start, count)
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
