# SPDX-License-Identifier: Apache-2.0
"""RP2040 PIO transport. Same instructions/timing as pico/kagura_host.pio.

No global CPU clock changes. Each byte returns one RX word; both FIFOs are
pumped together, including write-only transfers. No blocking put/get on a
full/empty FIFO, so an unplugged device/BUSY stall has a bounded timeout.
"""
from machine import Pin, freq, mem32
from time import ticks_us, ticks_diff, sleep_us
import rp2
from . import regs as R

_owned_sms = set()


def _program(lanes, busy):
    if lanes == 1:
        @rp2.asm_pio(out_init=rp2.PIO.OUT_LOW,
                     sideset_init=rp2.PIO.OUT_LOW,
                     out_shiftdir=rp2.PIO.SHIFT_LEFT,
                     in_shiftdir=rp2.PIO.SHIFT_LEFT,
                     autopush=True, push_thresh=8)
        def spi():
            wrap_target()
            pull(block).side(0)
            out(x, 1).side(0)
            jmp(not_x, "start").side(0)
            wait(0, gpio, busy).side(0)
            label("start")
            set(y, 7).side(0)
            label("bitloop")
            out(pins, 1).side(0)[4]
            in_(pins, 1).side(0)
            nop().side(1)[2]
            jmp(y_dec, "bitloop").side(1)[2]
            wrap()
        return spi
    @rp2.asm_pio(out_init=(rp2.PIO.IN_LOW,) * 4,
                 set_init=(rp2.PIO.IN_LOW,) * 4,
                 sideset_init=rp2.PIO.OUT_LOW,
                 out_shiftdir=rp2.PIO.SHIFT_LEFT,
                 in_shiftdir=rp2.PIO.SHIFT_LEFT,
                 autopush=True, push_thresh=8)
    def qspi():
        wrap_target()
        label("top")
        pull(block).side(0)
        out(x, 1).side(0)
        jmp(not_x, "start").side(0)
        wait(0, gpio, busy).side(0)
        label("start")
        out(y, 1).side(0)
        out(pins, 4).side(0)[4]
        in_(pins, 4).side(0)
        nop().side(1)[5]
        out(pins, 4).side(0)[4]
        in_(pins, 4).side(0)
        nop().side(1)[5]
        jmp(not_y, "top").side(0)
        set(pindirs, 0).side(0)
        wrap()
    return qspi


class TransferTimeout(OSError):
    """Some bytes may already have taken effect; never replay automatically."""
    def __init__(self, completed):
        self.completed = completed  # conservative prefix within current transfer
        super().__init__("PIO/BUSY timeout; transfer outcome may be partial")


class PIOTransport:
    def __init__(self, mode="spi", baudrate=1_000_000, sm_id=0,
                 io0=2, sck=6, cs=7, busy=8, ready=9, irq=10,
                 timeout_us=100_000):
        if mode not in ("spi", "qspi"):
            raise ValueError("mode must be spi or qspi")
        pins = list(range(io0, io0 + 4)) + [sck, cs, busy, ready, irq]
        if (len(set(pins)) != len(pins) or min(pins) < 0 or max(pins) > 29
                or not 0 <= sm_id <= 7 or not 100_000 <= baudrate <= 5_000_000
                or baudrate * 12 > freq() or not 1 <= timeout_us <= 10_000_000):
            raise ValueError("invalid RP2040 pin, SM, clock or timeout")
        if sm_id in _owned_sms:
            raise RuntimeError("PIO state machine already owned by KAGURA")
        self._sm_id = sm_id
        self.lanes = 1 if mode == "spi" else 4
        self.timeout_us = timeout_us
        self._tail_us = (2_000_000 + baudrate - 1) // baudrate
        self._cs = Pin(cs, Pin.OUT, value=1)
        self._sck = Pin(sck, Pin.OUT, value=0)
        self._io = [Pin(p, Pin.IN) for p in range(io0, io0 + 4)]
        self._busy = Pin(busy, Pin.IN)
        self._ready = Pin(ready, Pin.IN, Pin.PULL_DOWN)
        self._irq = Pin(irq, Pin.IN)  # external 4.7k pull-up required
        # RP2040 PADS_BANK0: 2mA, slow slew, Schmitt input, matching C host.
        for p in list(range(io0, io0 + 4)) + [sck, cs]:
            pad = 0x4001C004 + 4 * p
            mem32[pad] = (mem32[pad] & ~0x31) | 2
        self._program = _program(self.lanes, busy)
        self._config = dict(freq=baudrate * 12, out_base=self._io[0],
                            set_base=self._io[0],
                            in_base=self._io[0 if self.lanes == 4 else 1],
                            sideset_base=self._sck)
        self._sm = rp2.StateMachine(sm_id)
        self._closed = False
        self._active = False
        self.last_fifo_status = 0
        try:
            self._init_sm()
        except BaseException:
            self._sm.active(0)
            self._cs(1)
            for pin in self._io:
                pin.init(Pin.IN)
            # init may have added the program before failing to configure SM.
            try:
                rp2.PIO(sm_id // 4).remove_program(self._program)
            except (ValueError, OSError):
                pass
            raise
        _owned_sms.add(sm_id)

    def _init_sm(self):
        self._sm.init(self._program, **self._config)
        self._sm.active(1)

    def ready(self):
        return bool(self._ready.value())

    def irq_asserted(self):
        return not self._irq.value()

    def _begin(self):
        if self._closed or self._active:
            raise RuntimeError("transport closed or already in use")
        if not self.ready():
            raise OSError("KAGURA is not READY (reset or disconnected)")
        self._active = True
        if self.lanes == 4:
            self._sm.exec("set(pindirs, 15)")
        sleep_us(1)  # t_DIS and t_CSW >= 200ns
        self._cs(0)
        sleep_us(1)  # t_CSS >= 200ns

    def _end(self):
        # Autopush precedes the last rising edge. Wait for the final high
        # half-cycle and following falling edge before deasserting CS.
        sleep_us(self._tail_us)
        self._cs(1)
        sleep_us(1)
        if self.lanes == 4:
            self._sm.exec("set(pindirs, 0)")
        self._active = False

    def _abort(self):
        self._sm.active(0)
        self._cs(1)
        sleep_us(1)
        self._init_sm()  # clears FIFOs/shift counters; SCK low, QSPI input
        self._active = False

    def _xfer(self, tx=None, rx=None, count=None, offset=None, inc=False,
              release_last=False):
        n = len(tx) if tx is not None else (len(rx) if rx is not None else count)
        sent = got = 0
        progress = ticks_us()
        while got < n:
            if sent < n and self._sm.tx_fifo() < 4:
                target = ((offset + sent) & 31) if inc else offset
                queued = target in (R.REG_VRAM_WRITE, R.REG_VRAM_READ_REQUEST,
                                    R.REG_COMMAND)
                value = tx[sent] if tx is not None else 0
                word = (int(queued) << 31) | (value << (23 if self.lanes == 1 else 22))
                if self.lanes == 4 and release_last and sent == n - 1:
                    word |= 1 << 30
                self._sm.put(word)
                sent += 1
            if self._sm.rx_fifo():
                value = self._sm.get() & 255
                if rx is not None:
                    rx[got] = value
                got += 1
                progress = ticks_us()
            if ticks_diff(ticks_us(), progress) >= self.timeout_us:
                raise TransferTimeout(max(0, got - 1))

    def write(self, offset, data, inc=False):
        if not 0 <= offset <= 31:
            raise ValueError("register offset")
        data = memoryview(data)
        header = bytes(((0x40 if inc else 0) | offset,))
        status = bytearray(1)
        if self._closed or self._active:
            raise RuntimeError("transport closed or already in use")
        try:
            self._begin()
            self._xfer(header, status)
            if self.lanes == 1:
                self.last_fifo_status = status[0]
            self._xfer(data, offset=offset, inc=inc)
            self._end()
        except BaseException:
            self._abort()
            raise

    def readinto(self, offset, buffer, inc=False):
        if not 0 <= offset <= 31 or not 1 <= len(buffer) <= 256:
            raise ValueError("register offset or read length (1..256)")
        prefix = bytes((0x80 | (0x40 if inc else 0) | offset, len(buffer) & 255))
        status = bytearray(2)
        if self._closed or self._active:
            raise RuntimeError("transport closed or already in use")
        try:
            self._begin()
            self._xfer(prefix, status, release_last=True)
            if self.lanes == 1:
                self.last_fifo_status = status[0]
            self._xfer(count=1)  # exactly one dummy byte
            self._xfer(rx=buffer)
            self._end()
        except BaseException:
            self._abort()
            raise

    def deinit(self):
        if self._closed:
            return
        self._sm.active(0)
        self._cs(1)
        sleep_us(1)
        self._sck.init(Pin.OUT, value=0)
        for pin in self._io:
            pin.init(Pin.IN)
        self._active = False
        self._closed = True
        rp2.PIO(self._sm_id // 4).remove_program(self._program)
        _owned_sms.discard(self._sm_id)
