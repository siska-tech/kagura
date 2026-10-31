# SPDX-License-Identifier: Apache-2.0
"""Viper kernels of kagura.link: whole transactions and operations per call.

Settings words (array('I'), see kagura/link.py for the names):
 0 PIO base   1 SM 0..3   2 n        3 shift      4 flags (2 = keep RX)
 5 offset     6 inc       7 release index (QSPI read turnaround, else -1)
 8 FIFO timeout us        9 completed bytes on a FIFO timeout
10 TX length 11 RX start 12 payload start 13 first RX byte (SPI FIFO_STATUS)
14 CS mask   15 READY mask 16 QSPI      17 pins-out / 18 pins-in instruction
19 tail us   20 header length, 21..24 header bytes
25 payload offset 26 payload length 27 flush max_gap 28..34 flush stats
35 TX DMA ch 36 RX DMA ch 37 TX CTRL 38 RX CTRL 39 word buffer address
40 sink address 41 DMA chunk words 42 DMA on 43 TX FIFO address 44 RX FIFO
45 wait timeout us (device timeout for status, FENCE and COMMIT waits)

Results: >= 0 done (a read returns its byte), -1 FIFO/BUSY timeout, -2 READY
low, -3 wait timeout, 0x100 | code for a non-zero ERROR_CODE. Every loop
that can wait calls sleep_ms(0) at least every 4 ms, so Ctrl-C interrupts a
stalled device as it does in the Python driver.
"""
import micropython
from time import sleep_ms


@micropython.viper
def _xact(tx, rx, settings) -> int:
    """One transaction of n bytes: header from the settings, payload from tx."""
    c = ptr32(settings)
    pio = ptr32(c[0])
    sio = ptr32(0xd0000000)
    timer = ptr32(0x40054000)
    sm = int(c[1])
    n = int(c[2])
    shift = int(c[3])
    want_rx = int(c[4]) & 2
    offset = int(c[5])
    increment = int(c[6])
    last = int(c[7])
    timeout = int(c[8])
    tx_length = int(c[10])
    rx_start = int(c[11])
    payload_start = int(c[12])
    hlen = int(c[20])
    src = int(c[25])
    source = ptr8(tx)
    destination = ptr8(rx)
    tx_full = uint(1) << (16 + sm)
    rx_empty = uint(1) << (8 + sm)
    txi = 4 + sm
    rxf = 8 + sm
    queued = uint(0)
    if offset == 7 or offset == 8 or offset == 14:
        queued = uint(0x80000000)                       # the PIO waits for BUSY low
    if (uint(sio[1]) & uint(c[15])) == uint(0):          # GPIO_IN: READY low
        return -2
    if int(c[16]):
        pio[54 + sm * 6] = c[17]                        # SMx_INSTR: drive IO0..3
    for i in range(2):                                  # t_DIS >= 200 ns
        pass
    sio[6] = c[14]                                      # GPIO_OUT_CLR: CS low
    for i in range(2):                                  # t_CSS >= 200 ns
        pass
    sent = 0
    got = 0
    seen = 0
    spins = 0
    progress = int(timer[10])                           # TIMERAWL
    polled = progress
    stream = want_rx == 0 and increment == 0 and last < 0 and tx_length == n and payload_start == hlen
    cpu_n = n
    if stream and int(c[42]) and n - hlen >= 64:
        cpu_n = hlen                                    # the payload goes by DMA below
    while got < cpu_n:
        status = uint(pio[1])
        if sent < cpu_n and (status & tx_full) == uint(0):
            b = 0
            if sent < hlen:
                b = int(c[21 + sent])
            elif sent < tx_length:
                b = int(source[src + sent - hlen])
            value = uint(b) << shift
            if sent >= payload_start:
                if increment:
                    current = (offset + sent - payload_start) & 31
                    if current == 7 or current == 8 or current == 14:
                        value |= uint(0x80000000)
                else:
                    value |= queued
            if sent == last:
                value |= uint(0x40000000)               # QSPI: release IO after this byte
            pio[txi] = value
            sent += 1
        if (status & rx_empty) == uint(0):
            value = uint(pio[rxf]) & uint(255)
            if got == 0:
                c[13] = value
            if want_rx and got >= rx_start:
                destination[got - rx_start] = value
            got += 1
        spins += 1
        if spins == 256:
            spins = 0
            now = int(timer[10])
            if got != seen:
                seen = got
                progress = now
            elif now - progress >= timeout:
                c[9] = uint(got - 1 if got else 0)
                return -1
            if now - polled >= 4000:
                polled = now
                sleep_ms(0)                             # pending Ctrl-C
    if cpu_n < n:
        # TX DMA feeds the PIO from one half of a double buffer while the CPU
        # packs the next chunk into the other; RX DMA drains the per-byte RX
        # words into a sink.
        dma = ptr32(0x50000000)
        words = ptr32(int(c[39]))
        chunk = int(c[41])
        txb = int(c[35]) * 16
        rxb = int(c[36]) * 16
        total = n - hlen
        m = chunk if total > chunk else total
        for j in range(m):
            words[j] = (uint(source[src + j]) << shift) | queued
        off = 0
        half = 0
        while off < total:
            m = chunk if total - off > chunk else total - off
            dma[rxb] = c[44]                            # READ_ADDR: RX FIFO
            dma[rxb + 1] = c[40]                        # WRITE_ADDR: sink
            dma[rxb + 2] = m                            # TRANS_COUNT
            dma[rxb + 3] = c[38]                        # CTRL_TRIG starts it
            dma[txb] = int(c[39]) + half * chunk * 4
            dma[txb + 1] = c[43]                        # TX FIFO
            dma[txb + 2] = m
            dma[txb + 3] = c[37]
            following = off + m
            if following < total:
                k = chunk if total - following > chunk else total - following
                o = (1 - half) * chunk
                for j in range(k):
                    words[o + j] = (uint(source[src + following + j]) << shift) | queued
            left = m
            progress = int(timer[10])
            while uint(dma[rxb + 3]) & uint(0x01000000):    # BUSY
                count = int(dma[rxb + 2])
                now = int(timer[10])
                if count != left:
                    left = count
                    progress = now
                elif now - progress >= timeout:
                    dma[273] = (1 << int(c[35])) | (1 << int(c[36]))   # CHAN_ABORT
                    c[9] = uint(hlen + off + m - left - 1)
                    return -1
                if now - polled >= 4000:
                    polled = now
                    sleep_ms(0)
            off = following
            half = 1 - half
    t = int(timer[10])
    while int(timer[10]) - t < int(c[19]) + 1:          # final half-cycle before CS high
        pass
    sio[5] = c[14]                                      # GPIO_OUT_SET: CS high
    for i in range(2):                                  # t_CSW >= 200 ns
        pass
    if int(c[16]):
        pio[54 + sm * 6] = c[18]                        # release IO0..3
    return 0


@micropython.viper
def _short(settings, buf, op: int, data: int) -> int:
    """A transaction of at most four bytes, which the 4-word FIFOs take whole.

    op bit 7 set: read the register op & 31 and return its byte. Otherwise op &
    0xff is the write header (bit 6 = INC) and op >> 8 the count 0..3 of
    little-endian data bytes. The last byte is also left in buf[0].
    """
    c = ptr32(settings)
    pio = ptr32(c[0])
    sio = ptr32(0xd0000000)
    timer = ptr32(0x40054000)
    sm = int(c[1])
    shift = int(c[3])
    qspi = int(c[16])
    if (uint(sio[1]) & uint(c[15])) == uint(0):
        return -2
    if qspi:
        pio[54 + sm * 6] = c[17]
    for i in range(2):
        pass
    sio[6] = c[14]
    for i in range(2):
        pass
    tx = 4 + sm
    header = op & 255
    offset = header & 31
    if header & 0x80:
        n = 4                                           # header, count, dummy, data
        pio[tx] = uint(header) << shift
        if qspi:
            pio[tx] = (uint(1) << shift) | uint(0x40000000)
        else:
            pio[tx] = uint(1) << shift
        pio[tx] = 0
        pio[tx] = 0
    else:
        count = op >> 8
        n = 1 + count
        pio[tx] = uint(header) << shift
        for k in range(count):
            current = offset
            if header & 0x40:
                current = (offset + k) & 31
            word = uint((data >> (8 * k)) & 255) << shift
            if current == 7 or current == 8 or current == 14:
                word |= uint(0x80000000)
            pio[tx] = word
    rx_empty = uint(1) << (8 + sm)
    got = 0
    value = 0
    start = int(timer[10])
    polled = start
    timeout = int(c[8])
    while got < n:
        if (uint(pio[1]) & rx_empty) == uint(0):
            value = int(pio[8 + sm]) & 255
            if got == 0:
                c[13] = value
            got += 1
        else:
            now = int(timer[10])
            if now - start >= timeout:
                c[9] = uint(got - 1 if got else 0)
                return -1
            if now - polled >= 4000:
                polled = now
                sleep_ms(0)
    for i in range(int(c[19]) * 5):                     # final half-cycle, >= 4.4 turns per us
        pass
    sio[5] = c[14]
    for i in range(2):
        pass
    if qspi:
        pio[54 + sm * 6] = c[18]
    ptr8(buf)[0] = value
    if header & 0x80:
        return value
    return 0


@micropython.viper
def _errors(settings, buf) -> int:
    e = int(_short(settings, buf, 0x80 | 0x17, 0))      # ERROR_CODE
    if e > 0:
        return 0x100 | e
    return e


@micropython.viper
def _wait(settings, buf, offset: int, mask_value: int) -> int:
    """Poll register offset until (value & mask) == want; mask in bits 15..8."""
    timer = ptr32(0x40054000)
    timeout = int(ptr32(settings)[45])
    mask = (mask_value >> 8) & 255
    want = mask_value & 255
    start = int(timer[10])
    polled = start
    while True:
        r = int(_short(settings, buf, 0x80 | offset, 0))
        if r < 0 or (r & mask) == want:
            return r if r < 0 else 0
        now = int(timer[10])
        if now - start >= timeout:
            return -3
        if now - polled >= 4000:
            polled = now
            sleep_ms(0)


@micropython.viper
def _write_memory(settings, buf, address: int, data) -> int:
    """INC=1, VRAM_ADDR, VRAM_WRITE of settings[26] bytes from data[settings[25]], ERROR_CODE."""
    c = ptr32(settings)
    r = int(_short(settings, buf, 0x50 | 0x200, 1))     # INC_L, INC_H
    if r == 0:
        r = int(_short(settings, buf, 0x44 | 0x300, address))   # VRAM_ADDR_L..H
    if r < 0:
        return r
    n = int(c[26]) + 1
    c[2] = n
    c[4] = 0
    c[5] = 7
    c[6] = 0
    c[7] = -1
    c[10] = n
    c[11] = 0
    c[12] = 1
    c[20] = 1
    c[21] = 7                                           # VRAM_WRITE, queued
    r = int(_xact(data, buf, settings))
    if r < 0:
        return r
    return int(_errors(settings, buf))


@micropython.viper
def _fence(settings, buf) -> int:
    """device.fence(): a tag other than the current DONE_TAG, then wait for it."""
    tag = int(_short(settings, buf, 0x80 | 0x16, 0))    # DONE_TAG
    if tag < 0:
        return tag
    tag = (tag + 1) & 255
    r = int(_short(settings, buf, 0x15 | 0x100, tag))   # FENCE_TAG
    if r == 0:
        r = int(_short(settings, buf, 0x0e | 0x100, 2)) # COMMAND FENCE
    if r == 0:
        r = int(_errors(settings, buf))
    if r == 0:
        r = int(_wait(settings, buf, 0x16, 0xff00 | tag))
    if r == 0:
        r = int(_errors(settings, buf))
    return r


@micropython.viper
def _audio_idle(settings, buf) -> int:
    """Wait for AUDIO_STATUS.APPLY_BUSY low."""
    timer = ptr32(0x40054000)
    timeout = int(ptr32(settings)[45])
    start = int(timer[10])
    polled = start
    while True:
        r = int(_short(settings, buf, 0x4c | 0x100, 0xe1))     # AUDIO index = AUDIO_STATUS
        if r == 0:
            r = int(_short(settings, buf, 0x80 | 0x0d, 0))
        if r < 0:
            return r
        if (r & 1) == 0:
            return 0
        now = int(timer[10])
        if now - start >= timeout:
            return -3
        if now - polled >= 4000:
            polled = now
            sleep_ms(0)


@micropython.viper
def _commit(settings, buf, command: int) -> int:
    """device.commit() (command 3) or audio_commit() (4); bit 8 skips the final wait."""
    final = (command & 0x100) == 0
    command &= 255
    if command == 3:
        r = int(_wait(settings, buf, 0x00, 0x1000))     # STATUS.COMMIT_BUSY low
    else:
        r = int(_audio_idle(settings, buf))
    if r == 0:
        r = int(_short(settings, buf, 0x0e | 0x100, command))
    if r == 0:
        r = int(_errors(settings, buf))
    if r != 0 or not final:
        return r
    if command == 3:
        return int(_wait(settings, buf, 0x00, 0x1000))
    return int(_audio_idle(settings, buf))


@micropython.viper
def _audio_batch(settings, buf, ops, n: int) -> int:
    """n (index, value) byte pairs, each one INC write of AUDIO_REG_INDEX and DATA."""
    p = ptr8(ops)
    for k in range(n):
        r = int(_short(settings, buf, 0x4c | 0x200, int(p[2 * k]) | (int(p[2 * k + 1]) << 8)))
        if r < 0:
            return r
    return 0


@micropython.viper
def _flush(settings, buf, dirty, data) -> int:
    """TileFramebuffer.flush(): gap merge, runs split at 1023/1024, FENCE each.

    A run becomes clean only after its FENCE and error checks; on failure the
    run and every later one stay dirty. Stats accumulate in settings 28..34.
    """
    c = ptr32(settings)
    d = ptr8(dirty)
    timer = ptr32(0x40054000)
    gap = int(c[27])
    if gap:                                             # mark gap tiles before any I/O
        first = 0
        while first < 1200 and d[first] == 0:
            first += 1
        while first < 1200:
            end = first
            while end < 1200 and d[end]:
                end += 1
            following = end
            while following < 1200 and d[following] == 0:
                following += 1
            if following >= 1200:
                break
            if following - end <= gap:
                for i in range(end, following):
                    d[i] = 1
            first = following
    tile = 0
    while tile < 1200:
        while tile < 1200 and d[tile] == 0:
            tile += 1
        if tile >= 1200:
            break
        first = tile
        while tile < 1200 and d[tile]:
            tile += 1
        count = tile - first
        c[30] = int(c[30]) + 1                          # runs
        c[29] = int(c[29]) + count * 32                 # bytes
        c[31] = int(c[31]) + 1                          # writes
        if first < 1024 and tile > 1024:
            c[31] = int(c[31]) + 1
        t = int(timer[10])
        r = 0
        if first < 1024:
            top = tile
            if top > 1024:
                top = 1024
            c[25] = first * 32
            c[26] = (top - first) * 32
            r = int(_write_memory(settings, buf, first * 32, data))
        if r == 0 and tile > 1024:
            low = first
            if low < 1024:
                low = 1024
            c[25] = low * 32
            c[26] = (tile - low) * 32
            r = int(_write_memory(settings, buf, 0xB000 + (low - 1024) * 32, data))
        c[33] = int(c[33]) + int(timer[10]) - t         # transfer_us
        if r != 0:
            return r
        t = int(timer[10])
        c[32] = int(c[32]) + 1                          # fences
        r = int(_fence(settings, buf))
        c[34] = int(c[34]) + int(timer[10]) - t         # wait_us
        if r != 0:
            return r
        for i in range(first, tile):
            d[i] = 0
        c[28] = int(c[28]) + count                      # tiles
    return 0
