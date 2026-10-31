# SPDX-License-Identifier: Apache-2.0
"""kagura.link on PC: its Viper kernel source runs against a model of the
RP2040 PIO FIFOs, SIO, timer and DMA wired to the register model of
test_driver.py. Every operation must leave the model, the return values,
the framebuffer and the exceptions exactly as the plain Python driver does.
Wire semantics only; native timing and code generation are Pico tests.
"""
import ast
import random
import sys
import types
from array import array
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import test_driver as T
from viper_emulator import Pointer, int32
from unittest import TestCase, main
from kagura import Kagura, DeviceError, regs as R
from kagura.framebuffer import TileFramebuffer
from kagura.link import Link
from kagura.transport_rp2 import TransferTimeout

SOURCE = T.ROOT / 'software/micropython/kagura/link_viper.py'
PIO_BASES = (0x50200000, 0x50300000)
CHUNK = 128


class Hardware:
    """What the kernels see at their fixed addresses, driving the model."""

    def __init__(self, model, lanes=4, sm=1):
        self.model, self.sm = model, sm
        self.shift = 22 if lanes == 4 else 23
        self.time = 0
        self.ready = True
        self.stall = False          # queued bytes never see BUSY low
        self.interrupt_after = None  # sleep_ms(0) calls before a KeyboardInterrupt
        self.polls = 0
        self.cs = True
        self.held = []              # TX words waiting for BUSY
        self.rx = []
        self.buffers = {}           # fake address -> buffer
        self.channels = {}          # DMA channel -> registers
        self.aborts = []
        self.transactions = 0

    # pointers
    def ptr32(self, target):
        if not isinstance(target, int):
            return Pointer(target, 4)
        address = target & 0xFFFFFFFF
        if address == 0xd0000000:
            return Registers(self.sio_read, self.sio_write)
        if address == 0x40054000:
            return Registers(self.timer_read, None)
        if address == 0x50000000:
            return Registers(self.dma_read, self.dma_write)
        if address in PIO_BASES:
            return Registers(self.pio_read, self.pio_write)
        return Pointer(self.buffers[address], 4)

    def sleep_ms(self, ms):
        self.polls += 1
        if self.interrupt_after is not None and self.polls >= self.interrupt_after:
            raise KeyboardInterrupt

    def timer_read(self, index):
        assert index == 10
        self.time += 1
        return self.time

    # SIO: GPIO_IN (READY on GPIO 9), OUT_SET / OUT_CLR (CS on GPIO 7)
    def sio_read(self, index):
        assert index == 1
        return (1 << 9) if self.ready else 0

    def sio_write(self, index, value):
        assert value == 1 << 7, value
        if index == 6:
            assert self.cs, 'CS already low'
            self.cs = False
            self.bytes, self.response = [], []
        elif index == 5:
            assert not self.cs
            self.cs = True
            self.end()
        else:
            raise AssertionError(index)

    # PIO: FSTAT, TXF, RXF, SMx_INSTR
    def pio_read(self, index):
        if index == 1:
            full = (1 << (16 + self.sm)) if len(self.held) >= 4 else 0
            empty = 0 if self.rx else (1 << (8 + self.sm))
            return full | empty
        if index == 8 + self.sm:
            return self.rx.pop(0)
        raise AssertionError(index)

    def pio_write(self, index, value):
        if index == 54 + self.sm * 6:
            return   # pin direction instruction
        assert index == 4 + self.sm, index
        assert not self.cs, 'TX word with CS high'
        if self.held or (self.stall and value & 0x80000000):
            self.held.append(value)
            return
        self.byte(value)

    def byte(self, word):
        b = (word >> self.shift) & 255
        n = len(self.bytes)
        self.bytes.append(b)
        if n == 1 and self.bytes[0] & 0x80:   # read: count known, take the data now
            header = self.bytes[0]
            data = bytearray(b or 256)
            self.model.readinto(header & 31, data, bool(header & 0x40))
            self.response = list(data)
        out = 0
        if self.bytes[0] & 0x80 and n >= 3:
            out = self.response[n - 3]
        self.rx.append(out)

    def end(self):
        self.transactions += 1
        if not self.bytes:
            return
        header = self.bytes[0]
        if not header & 0x80:
            self.model.write(header & 31, bytes(self.bytes[1:]), bool(header & 0x40))

    # DMA: per channel READ_ADDR, WRITE_ADDR, TRANS_COUNT, CTRL_TRIG; CHAN_ABORT
    def dma_read(self, index):
        ch, reg = divmod(index, 16)
        r = self.channels[ch]
        if reg == 2:
            return r['left']
        if reg == 3:
            return 0x01000000 if r['busy'] else 0
        raise AssertionError(index)

    def dma_write(self, index, value):
        if index == 273:
            self.aborts.append(value)
            for r in self.channels.values():
                r['busy'] = False
            return
        ch, reg = divmod(index, 16)
        r = self.channels.setdefault(ch, dict(read=0, write=0, left=0, busy=False))
        if reg == 0:
            r['read'] = value
        elif reg == 1:
            r['write'] = value
        elif reg == 2:
            r['left'] = value
        elif reg == 3:
            r['busy'] = True
            if r['write'] == self.txf:          # TX channel: feed the PIO
                base = max(a for a in self.buffers if a <= r['read'])
                words = memoryview(self.buffers[base]).cast('B')
                offset = r['read'] - base
                for i in range(r['left']):
                    self.pio_write(4 + self.sm, int.from_bytes(words[offset + 4 * i:offset + 4 * i + 4], 'little'))
                r['busy'] = False
                r['left'] = 0
                rx = next(c for c in self.channels.values() if c['read'] == self.rxf)
                while rx['busy'] and rx['left'] and self.rx:
                    self.rx.pop(0)
                    rx['left'] -= 1
                rx['busy'] = rx['left'] > 0
        else:
            raise AssertionError(index)


class Registers:
    def __init__(self, read, write):
        self.read, self.write = read, write

    def __getitem__(self, index):
        return self.read(index)

    def __setitem__(self, index, value):
        self.write(index, value & 0xFFFFFFFF)


def kernels(hw):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    for node in functions:
        node.decorator_list = []
    namespace = dict(ptr8=lambda b: Pointer(b, 1), ptr32=hw.ptr32, int=int32,
                     uint=lambda n: int(n) & 0xFFFFFFFF, sleep_ms=hw.sleep_ms)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return types.SimpleNamespace(**{n.name: namespace[n.name] for n in functions})


class Transport:
    """The parts of PIOTransport that Link uses; the model answers fallbacks."""

    def __init__(self, model, hw, lanes, sm):
        self.model, self.hw, self.lanes, self._sm_id = model, hw, lanes, sm
        self.timeout_us, self._tail_us = 2000, 1
        self._pins_out, self._pins_in = 0xe08f, 0xe080
        self._dma_tx, self._dma_rx = types.SimpleNamespace(channel=2), types.SimpleNamespace(channel=3)
        self._tx_ctrl, self._rx_ctrl = 0x11, 0x22
        self._closed = self._active = False
        self.last_fifo_status = 0
        self.write, self.readinto = model.write, model.readinto
        self.link = None

    def ready(self):
        return self.hw.ready

    def idle(self):
        return self.hw.ready

    def _abort(self):
        self.hw.aborts.append('abort')
        self.hw.cs, self.hw.held, self.hw.rx = True, [], []
        self._active = False


class TestLink(Link):
    def _address(self, buffer):
        address = 0x20000000 + 0x10000 * (len(self._hw.buffers) + 1)
        self._hw.buffers[address] = buffer
        return address


def connect(lanes=4, sm=1, model=None):
    model = model or T.RegisterModel()
    model.ext[R.EXT_SCREEN_HEIGHT] = 240
    model.ext[R.EXT_PATTERN_COUNT_L], model.ext[R.EXT_PATTERN_COUNT_H] = 1200 & 255, 1200 >> 8
    hw = Hardware(model, lanes, sm)
    raw = Transport(model, hw, lanes, sm)
    TestLink._hw = hw
    link = TestLink(raw, TransferTimeout, CHUNK, k=kernels(hw))
    hw.txf, hw.rxf = link.c[43], link.c[44]
    raw.write, raw.readinto, raw.link = link.write, link.readinto, link
    device = Kagura(raw, timeout_us=3000).probe()
    return device, model, hw, raw


def plain(model=None):
    model = model or T.RegisterModel()
    model.ext[R.EXT_SCREEN_HEIGHT] = 240
    model.ext[R.EXT_PATTERN_COUNT_L], model.ext[R.EXT_PATTERN_COUNT_H] = 1200 & 255, 1200 >> 8
    return Kagura(model, timeout_us=3000).probe(), model


def state(model):
    return bytes(model.reg), bytes(model.ext), bytes(model.audio), bytes(model.memory)


class LinkTests(TestCase):
    def test_register_operations_match_the_driver(self):
        for lanes in (1, 4):
            for sm in (0, 3):
                rng = random.Random(lanes * 10 + sm)
                fast, fm, hw, _ = connect(lanes, sm)
                slow, sm_ = plain()
                for _ in range(300):
                    op = rng.randrange(6)
                    a, v = rng.randrange(256), rng.randrange(256)
                    reg = rng.choice((R.REG_FENCE_TAG, R.REG_LENGTH_L, R.REG_INC_L))
                    for d in (fast, slow):
                        if op == 0:
                            d.write_reg(reg, v)
                        elif op == 1:
                            d.ext_write(a, v)
                        elif op == 2:
                            d.audio_write(a, v)
                    if op == 3:
                        self.assertEqual(fast.ext_read(a), slow.ext_read(a))
                    elif op == 4:
                        self.assertEqual(fast.audio_read(a), slow.audio_read(a))
                    elif op == 5:
                        self.assertEqual(fast.read_reg(R.REG_FENCE_TAG), slow.read_reg(R.REG_FENCE_TAG))
                buf_f, buf_s = bytearray(5), bytearray(5)
                fast.transport.readinto(R.REG_ID0, buf_f, True)
                slow.transport.readinto(R.REG_ID0, buf_s, True)
                self.assertEqual(buf_f, buf_s)
                self.assertEqual(state(fm), state(sm_))
                self.assertEqual(fast.busy, 0)
                self.assertTrue(hw.cs)

    def test_queued_flags_follow_the_byte_offsets(self):
        fast, model, hw, _ = connect()
        words = []
        write = hw.pio_write
        hw.pio_write = lambda i, v: (words.append(v) if i == 4 + hw.sm else None, write(i, v))
        # Header, then AUDIO_REG_INDEX, AUDIO_REG_DATA and COMMAND: only the last waits.
        fast.transport.write(R.REG_AUDIO_REG_INDEX, bytes((0x04, 9, R.CMD_FENCE)), True)
        self.assertEqual([bool(w & 0x80000000) for w in words], [False, False, False, True])
        words.clear()
        fast.write_reg(R.REG_COMMAND, R.CMD_FENCE)
        self.assertEqual([bool(w & 0x80000000) for w in words], [False, True])

    def test_write_memory_sizes_and_dma(self):
        rng = random.Random(5)
        for lanes in (1, 4):
            fast, fm, hw, _ = connect(lanes)
            slow, sm_ = plain()
            for size in (1, 3, 4, 63, 64, 65, 127, 128, 129, 300, 1000, 4096):
                address = rng.randrange(0, 0x8000 - size)
                data = bytes(rng.randrange(256) for _ in range(size))
                fast.write_memory(address, data)
                slow.write_memory(address, data)
                fast.fence()
                slow.fence()
            self.assertEqual(state(fm), state(sm_))
            self.assertGreater(len(hw.channels), 0, 'large payloads use DMA')
            self.assertEqual(hw.aborts, [])

    def test_fence_commit_audio_and_waits(self):
        fast, fm, hw, _ = connect()
        slow, sm_ = plain()
        for d in (fast, slow):
            d.write_memory(0x9400, bytes(range(64)))
            d.fence()
            d.commit()
            d.commit(wait=False)
            d.wait_status(R.STATUS_COMMIT_BUSY, 0)
            d.audio_writes(bytes((0x04, 12, 0x05, 9, 0x14, 33)))
            d.audio_commit()
            d.ext_writes(bytes((R.EXT_SCROLL_X_L, 77, R.EXT_RS_INDEX, 0, R.EXT_RS_LINE, 16, R.EXT_RS_Y, 5)))
        self.assertEqual(state(fm), state(sm_))
        self.assertEqual((fm.ext[R.EXT_SCROLL_X_L], fm.ext[R.EXT_RS_LINE], fm.ext[R.EXT_RS_Y]), (77, 16, 5))
        with self.assertRaises(ValueError):
            fast.audio_writes(b'\x01')
        with self.assertRaises(ValueError):
            fast.ext_writes(b'\x01')

    def test_device_error_is_reported_as_by_the_driver(self):
        for name, call in (('fence', lambda d: d.fence()), ('commit', lambda d: d.commit()),
                           ('write_memory', lambda d: d.write_memory(0, bytes(100))),
                           ('audio_commit', lambda d: d.audio_commit())):
            fast, fm, hw, _ = connect()
            slow, sm_ = plain()
            fm.reg[R.REG_ERROR_CODE] = sm_.reg[R.REG_ERROR_CODE] = R.ERROR_CODE_BAD_ACCESS
            with self.assertRaises(DeviceError) as f:
                call(fast)
            with self.assertRaises(DeviceError) as s:
                call(slow)
            self.assertEqual(f.exception.code, s.exception.code, name)
            self.assertEqual(fast.busy, 0)
            self.assertFalse(fast.transport._active)

    def test_error_found_after_the_fence_wait(self):
        # An error the queue raises while the FENCE completes must still be
        # reported by the check that follows the DONE_TAG wait.
        fast, fm, hw, _ = connect()
        slow, sm_ = plain()
        for d, m in ((fast, fm), (slow, sm_)):
            reads, readinto = [0], m.readinto
            def hook(offset, buffer, inc=False, m=m, reads=reads, readinto=readinto):
                readinto(offset, buffer, inc)
                if offset == R.REG_DONE_TAG:
                    reads[0] += 1
                    if reads[0] == 2:
                        m.reg[R.REG_ERROR_CODE] = R.ERROR_CODE_INVALID_ADDRESS
            m.readinto = hook
            with self.assertRaises(DeviceError) as e:
                d.fence()
            self.assertEqual(e.exception.code, R.ERROR_CODE_INVALID_ADDRESS)

    def test_not_ready_stall_and_interrupt_recover_the_transport(self):
        fast, fm, hw, raw = connect()
        hw.ready = False
        with self.assertRaisesRegex(OSError, 'READY'):
            fast.write_reg(R.REG_FENCE_TAG, 1)
        hw.ready = True
        for size in (2, 3000):   # FIFO path and DMA path
            hw.aborts.clear()
            hw.stall = True
            with self.assertRaises(TransferTimeout):
                fast.write_memory(0, bytes(size))
            hw.stall = False
            self.assertIn('abort', hw.aborts)
            if size > 64:
                self.assertTrue(any(isinstance(a, int) for a in hw.aborts), 'CHAN_ABORT written')
            self.assertFalse(raw._active)
        fast.write_reg(R.REG_FENCE_TAG, 7)
        self.assertEqual(fast.read_reg(R.REG_FENCE_TAG), 7)
        # Ctrl-C is polled every 4 ms, well inside the 100 ms default timeout.
        raw.link.c[8] = 50000
        hw.stall, hw.interrupt_after = True, 1
        with self.assertRaises(KeyboardInterrupt):
            fast.write_memory(0, bytes(3000))
        self.assertFalse(raw._active)
        self.assertTrue(hw.cs)

    def test_wait_timeout_message_matches_the_driver(self):
        fast, fm, hw, _ = connect()
        fm.reg[R.REG_STATUS] |= R.STATUS_COMMIT_BUSY
        with self.assertRaisesRegex(OSError, 'KAGURA timeout: STATUS'):
            fast.commit()
        fm.reg[R.REG_STATUS] &= ~R.STATUS_COMMIT_BUSY

    def test_wide_buffers_keep_the_previous_path(self):
        fast, fm, hw, raw = connect()
        calls = []
        raw.link.fallback_write = lambda *a: calls.append(a)
        fast.transport.write(R.REG_VRAM_WRITE, array('H', [1, 2]))
        self.assertEqual(len(calls), 1)

    def test_framebuffer_flush_matches_the_python_flush(self):
        rng = random.Random(9)
        fast, fm, hw, _ = connect()
        slow, sm_ = plain()
        fbs = [TileFramebuffer(fast), TileFramebuffer(slow)]
        for fb in fbs:
            fb.set_viper(False)
            fb.initialize()
        for gap in (0, 1, 7, 40):
            for _ in range(3):
                for _ in range(rng.randrange(1, 40)):
                    x, y, w, h, c = (rng.randrange(-20, 330), rng.randrange(-20, 250),
                                     rng.randrange(1, 60), rng.randrange(1, 40), rng.randrange(16))
                    for fb in fbs:
                        fb.fill_rect(x, y, w, h, c)
                stats = [fb.flush(gap) for fb in fbs]
                for key in ('tiles', 'bytes', 'runs', 'writes', 'fences'):
                    self.assertEqual(stats[0][key], stats[1][key], key)
                self.assertEqual(bytes(fbs[0].dirty), bytes(fbs[1].dirty))
        self.assertEqual(fm.memory, sm_.memory)

    def test_flush_failure_keeps_unconfirmed_runs_dirty(self):
        fast, fm, hw, _ = connect()
        fb = TileFramebuffer(fast)
        fb.set_viper(False)
        fb.initialize()
        for t in (3, 500, 1100):
            fb.pixel(t % 40 * 8, t // 40 * 8, 5)
        fences = [0]
        write = fm.write
        def fail_second_fence(offset, data, inc=False):
            if offset == R.REG_COMMAND and data == bytes((R.CMD_FENCE,)):
                fences[0] += 1
                if fences[0] == 2:
                    fm.reg[R.REG_ERROR_CODE] = R.ERROR_CODE_BAD_ACCESS
            write(offset, data, inc)
        fm.write = fail_second_fence
        with self.assertRaises(DeviceError):
            fb.flush()
        self.assertEqual([t for t in range(1200) if fb.dirty[t]], [500, 1100])
        self.assertEqual(fb.last_flush['fences'], 2)
        self.assertEqual(fast.busy, 0)


if __name__ == '__main__':
    main()
