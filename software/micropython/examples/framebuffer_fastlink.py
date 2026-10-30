# SPDX-License-Identifier: Apache-2.0
"""Experimental Viper register path for TileFramebuffer flush and per-frame I/O.

On the RP2040 each Python statement costs microseconds, so the driver spends
about 1 ms per register access and ~6 ms per FENCE in Python, not on the
wire. Here whole operations run in Viper: a transaction (READY check, QSPI
pins out, CS low, header and payload through the PIO FIFOs with the same word
format and queued flags as fifo_xfer_viper.pump, CS high, pins in), and on
top of it register access, memory write with error check, FENCE, COMMIT,
AUDIO_COMMIT and a whole TileFramebuffer flush. Python makes one call per
operation. Payloads of 64 bytes or more go to the PIO by DMA (the
transport's two channels) while Viper packs the next 256-byte chunk, which
reaches about 1 MB/s at QSPI 5 MHz, the same as the C host.

Same PIO program and pins as PIOTransport, which stays the owner; a failed
transaction calls its _abort(). Timeouts use the hardware timer. The kernels
do not poll for Ctrl-C, so a stalled device returns only after the timeout.
"""
import micropython
from array import array
from time import ticks_us, ticks_diff
from kagura import regs as R
from kagura.device import DeviceError

# settings words
_PIO, _SM, _N, _SHIFT, _FLAGS, _OFFSET, _INC, _LAST, _TIMEOUT, _DONE = range(10)
_TXLEN, _RXSTART, _PAYLOAD, _FIRST, _CS, _READY, _QSPI, _PINS_OUT, _PINS_IN, _TAIL = range(10, 20)
_HLEN, _H0 = 20, 21   # up to four header bytes in words 21..24
_SRC, _LEN, _GAP = 25, 26, 27   # payload offset and length; flush max_gap
_STATS = 28          # flush: tiles, bytes, runs, writes, fences, transfer_us, wait_us
_CHUNK = 256         # DMA payload words per half buffer

# Results below zero are transport failures, 0x100|code a non-zero ERROR_CODE.
_TIMEOUT_FIFO, _NOT_READY, _TIMEOUT_WAIT = -1, -2, -3


@micropython.viper
def _xact(tx, rx, settings) -> int:
    """One transaction: 0 done, -1 FIFO/BUSY timeout (bytes in settings[9]), -2 not READY."""
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
    queued = uint(0)
    if offset == 7 or offset == 8 or offset == 14:
        queued = uint(0x80000000)                                # wait for BUSY low
    if (uint(sio[1]) & uint(c[15])) == uint(0):                   # GPIO_IN: READY low
        return -2
    if int(c[16]):
        pio[54 + sm * 6] = c[17]                                 # SMx_INSTR: pins out
    t = int(timer[10])                                           # TIMERAWL
    while int(timer[10]) - t < 2:
        pass
    sio[6] = c[14]                                               # GPIO_OUT_CLR: CS low
    t = int(timer[10])
    while int(timer[10]) - t < 2:
        pass
    sent = 0
    got = 0
    spins = 0
    progress = int(timer[10])
    if want_rx == 0 and increment == 0 and last < 0 and tx_length == n and payload_start == hlen:
        # Write-only stream (every pattern upload): no per-byte offset, read-back
        # or timer work; progress is checked every 256 spins.
        txi = 4 + sm
        rxf = 8 + sm
        seen = 0
        cpu_n = n
        if int(c[42]) and n - hlen >= 64:
            cpu_n = hlen                                         # payload goes by DMA below
        while got < cpu_n:
            status = uint(pio[1])
            if sent < cpu_n and (status & tx_full) == uint(0):
                if sent < hlen:
                    pio[txi] = uint(c[21 + sent]) << shift
                else:
                    pio[txi] = (uint(source[src + sent - hlen]) << shift) | queued
                sent += 1
            if (status & rx_empty) == uint(0):
                value = uint(pio[rxf])
                if got == 0:
                    c[13] = value & uint(255)
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
        if cpu_n < n:
            # Payload: TX DMA feeds PIO words from one half of a double buffer
            # while the CPU packs the next chunk into the other; RX DMA drains
            # the per-byte RX words into a sink.
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
                dma[rxb] = c[44]                                 # READ_ADDR: RX FIFO
                dma[rxb + 1] = c[40]                             # WRITE_ADDR: sink
                dma[rxb + 2] = m
                dma[rxb + 3] = c[38]                             # CTRL_TRIG
                dma[txb] = int(c[39]) + half * chunk * 4
                dma[txb + 1] = c[43]                             # TX FIFO
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
                while uint(dma[rxb + 3]) & uint(0x01000000):     # BUSY
                    count = int(dma[rxb + 2])
                    if count != left:
                        left = count
                        progress = int(timer[10])
                    elif int(timer[10]) - progress >= timeout:
                        dma[273] = (1 << int(c[35])) | (1 << int(c[36]))   # CHAN_ABORT
                        c[9] = uint(hlen + off + m - left - 1)
                        return -1
                off = following
                half = 1 - half
        n = 0                                                    # skip the general loop
    while got < n:
        if sent < n and (uint(pio[1]) & tx_full) == uint(0):
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
                value |= uint(0x40000000)                        # QSPI read turnaround
            pio[4 + sm] = value
            sent += 1
        if (uint(pio[1]) & rx_empty) == uint(0):
            value = uint(pio[8 + sm]) & uint(255)
            if got == 0:
                c[13] = value
            if want_rx and got >= rx_start:
                destination[got - rx_start] = value
            got += 1
            progress = int(timer[10])
        spins += 1
        if spins == 64:
            spins = 0
            if int(timer[10]) - progress >= timeout:
                c[9] = uint(got - 1 if got else 0)
                return -1
    t = int(timer[10])
    while int(timer[10]) - t < int(c[19]) + 1:
        pass
    sio[5] = c[14]                                               # GPIO_OUT_SET: CS high
    t = int(timer[10])
    while int(timer[10]) - t < 2:
        pass
    if int(c[16]):
        pio[54 + sm * 6] = c[18]                                 # pins in
    return 0


@micropython.viper
def _short(settings, buf, op: int, data: int) -> int:
    """A transaction of at most four bytes, which the 4-word FIFOs hold whole.

    op bit 7 set: read one byte from register op & 31 and return it.
    Otherwise op & 0xff is the write header (bit 6 = INC) and op >> 8 the
    count (1..3) of little-endian data bytes. Failures are -1/-2 as _xact.
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
        pio[54 + sm * 6] = c[17]                                 # pins out
    for i in range(2):                                           # t_DIS >= 200 ns (0.225 us/turn)
        pass
    sio[6] = c[14]                                               # CS low
    for i in range(2):                                           # t_CSS >= 200 ns
        pass
    tx = 4 + sm
    header = op & 255
    if header & 0x80:
        n = 4                                                    # header, count, dummy, data
        pio[tx] = uint(header) << shift
        if qspi:
            pio[tx] = (uint(1) << shift) | uint(0x40000000)      # release the bus after it
        else:
            pio[tx] = uint(1) << shift
        pio[tx] = 0
        pio[tx] = 0
    else:
        count = op >> 8
        n = 1 + count
        offset = header & 31
        queued = uint(0)
        if (header & 0x40) == 0 and (offset == 7 or offset == 8 or offset == 14):
            queued = uint(0x80000000)
        pio[tx] = uint(header) << shift
        for k in range(count):
            pio[tx] = (uint((data >> (8 * k)) & 255) << shift) | queued
    rx_empty = uint(1) << (8 + sm)
    got = 0
    value = 0
    start = int(timer[10])
    timeout = int(c[8])
    while got < n:
        if (uint(pio[1]) & rx_empty) == uint(0):
            value = int(pio[8 + sm]) & 255
            if got == 0:
                c[13] = value
            got += 1
        elif int(timer[10]) - start >= timeout:
            c[9] = uint(got - 1 if got else 0)
            return -1
    for i in range(int(c[19]) * 5):                              # last half-cycle: tail_us at >= 4.4 turns/us
        pass
    sio[5] = c[14]                                               # CS high
    for i in range(2):                                           # t_CSW >= 200 ns
        pass
    if qspi:
        pio[54 + sm * 6] = c[18]                                 # pins in
    if header & 0x80:
        return value
    return 0


@micropython.viper
def _errors(settings, buf) -> int:
    e = int(_short(settings, buf, 0x80 | 0x17, 0))  # ERROR_CODE
    if e > 0:
        return 0x100 | e
    return e


@micropython.viper
def _wait(settings, buf, offset: int, mask_value: int) -> int:
    """Poll until (reg & mask) == value; mask in bits 15..8, value in 7..0."""
    timer = ptr32(0x40054000)
    timeout = int(ptr32(settings)[8])
    mask = (mask_value >> 8) & 255
    want = mask_value & 255
    start = int(timer[10])
    while True:
        r = int(_short(settings, buf, 0x80 | offset, 0))
        if r < 0:
            return r
        if (r & mask) == want:
            return 0
        if int(timer[10]) - start >= timeout:
            return -3


@micropython.viper
def _write_memory(settings, buf, address: int, data) -> int:
    """INC=1, VRAM_ADDR, VRAM_WRITE of data[settings[25]:][:settings[26]], then ERROR_CODE."""
    c = ptr32(settings)
    r = int(_short(settings, buf, 0x50 | 0x200, 1))  # INC = 1
    if r == 0:
        r = int(_short(settings, buf, 0x44 | 0x300, address))  # VRAM_ADDR_L..H
    if r < 0:
        return r
    c[4] = 0
    c[11] = 0
    c[7] = -1
    c[12] = 1
    n = int(c[26])
    c[20] = 1                                                    # VRAM_WRITE, queued
    c[21] = 7
    c[2] = n + 1
    c[10] = n + 1
    c[5] = 7
    c[6] = 0
    r = int(_xact(data, buf, settings))
    if r < 0:
        return r
    return int(_errors(settings, buf))


@micropython.viper
def _fence(settings, buf) -> int:
    tag = int(_short(settings, buf, 0x80 | 0x16, 0))  # DONE_TAG
    if tag < 0:
        return tag
    tag = (tag + 1) & 255
    r = int(_short(settings, buf, 0x15 | 0x100, tag))  # FENCE_TAG
    if r == 0:
        r = int(_short(settings, buf, 0x0e | 0x100, 2))  # COMMAND FENCE
    if r == 0:
        r = int(_errors(settings, buf))
    if r == 0:
        r = int(_wait(settings, buf, 0x16, 0xff00 | tag))
    if r == 0:
        r = int(_errors(settings, buf))
    return r


@micropython.viper
def _commit(settings, buf, command: int) -> int:
    """COMMIT (3) waits STATUS.COMMIT_BUSY; AUDIO_COMMIT (4) waits APPLY_BUSY.

    Waits for the previous one before issuing, and afterwards unless bit 8 of
    command is set (return as soon as it is queued, like commit(wait=False)).
    """
    r = 0
    final = (command & 0x100) == 0
    command &= 255
    for step in range(2):
        if step == 1 and not final:
            return 0
        if command == 3:
            r = int(_wait(settings, buf, 0x00, 0x1000))          # STATUS & COMMIT_BUSY == 0
        else:
            start = int(ptr32(0x40054000)[10])
            while True:
                r = int(_short(settings, buf, 0x0c | 0x100, 0xe1))  # AUDIO index = AUDIO_STATUS
                if r == 0:
                    r = int(_short(settings, buf, 0x80 | 0x0d, 0))
                if r < 0 or (r & 1) == 0:
                    break
                if int(ptr32(0x40054000)[10]) - start >= int(ptr32(settings)[8]):
                    r = -3
                    break
            if r > 0:
                r = 0
        if r != 0:
            return r
        if step == 0:
            r = int(_short(settings, buf, 0x0e | 0x100, command))
            if r == 0:
                r = int(_errors(settings, buf))
            if r != 0:
                return r
    return 0


@micropython.viper
def _audio_batch(settings, buf, ops, n: int) -> int:
    """n (index, value) byte pairs, each an INC write of AUDIO_REG_INDEX and DATA."""
    p = ptr8(ops)
    for k in range(n):
        r = int(_short(settings, buf, 0x4c | 0x200, int(p[2 * k]) | (int(p[2 * k + 1]) << 8)))
        if r < 0:
            return r
    return 0


@micropython.viper
def _flush(settings, buf, dirty, data) -> int:
    """Send dirty runs (gaps up to settings[27] merged first), FENCE each, clear on success."""
    c = ptr32(settings)
    d = ptr8(dirty)
    timer = ptr32(0x40054000)
    gap = int(c[27])
    if gap:                                                      # mark gap tiles before any I/O
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
        c[30] = int(c[30]) + 1
        c[29] = int(c[29]) + count * 32
        c[31] = int(c[31]) + 1
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
        c[33] = int(c[33]) + int(timer[10]) - t
        if r != 0:
            return r
        t = int(timer[10])
        c[32] = int(c[32]) + 1
        r = int(_fence(settings, buf))
        c[34] = int(c[34]) + int(timer[10]) - t
        if r != 0:
            return r
        for i in range(first, tile):                             # only a confirmed run is clean
            d[i] = 0
        c[28] = int(c[28]) + count
    return 0


class FastLink:
    """Register, memory and commit operations with the Device method names."""

    def __init__(self, device, cs=7, ready=9):
        raw = device.transport
        if raw._closed or raw._active:
            raise RuntimeError('transport closed or already in use')
        self.device, self.raw = device, raw
        sm = raw._sm_id
        c = self.c = array('I', [0] * 45)
        if raw._dma_tx is not None:
            # Words 35..44: DMA channels and CTRL (the transport's own pair,
            # idle between its transfers), double buffer, sink, FIFO addresses.
            import uctypes
            self.words, self.sink = array('I', [0] * (2 * _CHUNK)), bytearray(4)
            c[35], c[36] = raw._dma_tx.channel, raw._dma_rx.channel
            c[37], c[38] = raw._tx_ctrl, raw._rx_ctrl
            c[39], c[40] = uctypes.addressof(self.words), uctypes.addressof(self.sink)
            c[41], c[42] = _CHUNK, 1
            c[43] = 0x50200000 + (sm // 4) * 0x100000 + 0x10 + (sm % 4) * 4
            c[44] = c[43] + 0x10
        c[_PIO] = 0x50200000 + (sm // 4) * 0x100000
        c[_SM] = sm % 4
        c[_SHIFT] = 23 if raw.lanes == 1 else 22
        c[_TIMEOUT] = device.timeout_us
        c[_CS], c[_READY] = 1 << cs, 1 << ready
        c[_QSPI] = int(raw.lanes == 4)
        c[_PINS_OUT], c[_PINS_IN], c[_TAIL] = raw._pins_out, raw._pins_in, raw._tail_us
        self.buf = bytearray(4)

    def _check(self, r, name):
        if r >= 0x100:
            raise DeviceError(r & 255)
        if r < 0:
            self.raw._abort()
            raise OSError('KAGURA ' + name + (' not READY' if r == _NOT_READY else
                                              ' timeout' if r == _TIMEOUT_WAIT else ' PIO/BUSY timeout'))
        return r

    def _call(self, kernel, *args):  # kernel(settings, scratch, *args)
        raw = self.raw
        if raw._closed or raw._active:
            raise RuntimeError('transport closed or already in use')
        raw._active = True
        try:
            return kernel(self.c, self.buf, *args)
        finally:
            raw._active = False

    def read_reg(self, offset):
        return self._check(self._call(_short, 0x80 | offset, 0), 'read')

    def write_reg(self, offset, value):
        self._check(self._call(_short, offset | 0x100, value), 'write')

    def check_errors(self):
        self._check(self._call(_errors), 'ERROR_CODE')

    def write_memory(self, address, data):
        """No region check: callers pass pattern, palette or wave addresses only."""
        self.c[_SRC], self.c[_LEN] = 0, len(data)
        self._check(self._call(_write_memory, address, data), 'write_memory')

    def fence(self):
        self._check(self._call(_fence), 'FENCE')

    def commit(self, wait=True):
        self._check(self._call(_commit, R.CMD_COMMIT | (0 if wait else 0x100)), 'COMMIT')

    def audio_write(self, index, value):
        self._check(self._call(_short, 0x40 | R.REG_AUDIO_REG_INDEX | 0x200, index | value << 8), 'audio')

    def audio_writes(self, ops, n):
        self._check(self._call(_audio_batch, ops, n), 'audio')

    def audio_commit(self):
        self._check(self._call(_commit, R.CMD_AUDIO_COMMIT), 'AUDIO_COMMIT')

    def flush(self, fb, max_gap=0):
        """TileFramebuffer.flush() in one Viper call: same runs, gap merge, split, FENCE and stats."""
        if not fb.initialized:
            raise RuntimeError('call initialize() successfully before flush()')
        c = self.c
        c[_GAP] = max_gap
        for i in range(_STATS, _STATS + 7):
            c[i] = 0
        start = ticks_us()
        self.device.busy += 1
        try:
            r = self._call(_flush, fb.dirty, fb.buffer)
        finally:
            self.device.busy -= 1
            fb.last_flush = stats = dict(tiles=c[28], bytes=c[29], runs=c[30], writes=c[31], fences=c[32],
                                         transfer_us=c[33], wait_us=c[34],
                                         total_us=ticks_diff(ticks_us(), start))
        self._check(r, 'flush')
        return stats
