# SPDX-License-Identifier: Apache-2.0
"""DMA writes of the plain Python transport: byte to PIO word expansion.

Only the transport without kagura.link uses this (no Viper, or after
acceleration.close()); with the link, DMA payloads are packed in Viper.
"""
from time import ticks_us, ticks_diff


def python_pack(data, high, words, start, count):
    """words[1::2] = high[byte] for data[start:start + count] (16-bit halves)."""
    j = 1
    for k in range(start, start + count):
        words[j] = high[data[k]]
        j += 2


def transfer(transport, data, queued, timeout_type, chunk=128, packer=None):
    """One write's payload by DMA, `chunk` bytes at a time.

    The caller's write() owns CS, exception recovery and DMA abort.
    """
    high, words = transport._high[queued], transport._words
    tx, rx = transport._dma_tx, transport._dma_rx
    if packer is None:
        packer = python_pack
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
