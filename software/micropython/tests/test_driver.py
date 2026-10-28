# SPDX-License-Identifier: Apache-2.0
"""Host tests; hardware-facing imports are replaced, never a real device.

python -I software/micropython/tests/test_driver.py
Optional actual upstream assembler/timing test:
  ... --rp2 path/to/micropython/ports/rp2/modules/rp2.py
"""
import importlib.util
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "software/micropython"))
sys.dont_write_bytecode = True
sys.modules["micropython"] = types.SimpleNamespace(const=lambda x: x)
time.ticks_us = lambda: time.monotonic_ns() // 1000
time.ticks_diff = lambda a, b: a - b
time.sleep_us = lambda n: None


class Pin:
    IN, OUT, PULL_DOWN = 0, 1, 2
    def __init__(self, number, *args, value=0):
        self.number, self.level = number, value
        if number == 9:
            self.level = 1  # configured FPGA READY in transport tests
    def value(self):
        return self.level
    def __call__(self, value):
        self.level = value
    def init(self, *args, **kwargs):
        self.level = kwargs.get("value", self.level)


class StateMachine:
    def __init__(self, number=0):
        self.number = number
        self.stalled = False
        self.init_count = 0
        self.replies = []
    def init(self, program, **config):
        self.init_count += 1
        self.rx, self.words, self.instructions = [], [], []
        self.enabled = False
    def active(self, value):
        self.enabled = value
    def exec(self, instruction):
        self.instructions.append(instruction)
    def tx_fifo(self):
        return 0 if not self.stalled else 4
    def rx_fifo(self):
        return len(self.rx)
    def put(self, value, shift=0):
        if len(self.rx) >= 4:
            raise AssertionError("RX was not drained")
        self.words.append(value << shift)
        self.rx.append(self.replies.pop(0) if self.replies else 0)
    def get(self):
        return self.rx.pop(0)


class FakeDMA:
    """Moves TX words into the fake SM at once; the RX channel then completes."""
    stall = False
    def __init__(self):
        self.busy = False
        self.closed = False
        self.count = 0
        self.source = None
    def pack_ctrl(self, **fields):
        return fields
    def config(self, read=None, write=None, count=None, ctrl=None, trigger=False):
        self.count = count
        self.busy = True
        if isinstance(read, StateMachine):  # RX channel drains into a sink
            self.source = read
            FakeDMA.rx = self
            return
        if FakeDMA.stall:
            return
        for i in range(count):
            write.words.append(read[2 * i] | read[2 * i + 1] << 16)
        self.count = self.busy = 0
        FakeDMA.rx.count = FakeDMA.rx.busy = 0
    def active(self, value=None):
        if value is not None:
            self.busy = bool(value)
        return self.busy
    def close(self):
        self.closed = True


machine = types.ModuleType("machine")
machine.Pin, machine.StateMachine = Pin, StateMachine
machine.freq = lambda: 125_000_000
machine.mem32 = {0x4001C004 + 4 * i: 0 for i in range(30)}
sys.modules["machine"] = machine
class FakePIO:
    OUT_LOW, IN_LOW, SHIFT_LEFT, SHIFT_RIGHT, JOIN_NONE = 2, 0, 0, 1, 0
    def __init__(self, index):
        self.index = index
    def remove_program(self, program):
        pass


pio = FakePIO
rp2_arg = None
if "--rp2" in sys.argv:
    i = sys.argv.index("--rp2")
    rp2_arg = Path(sys.argv[i + 1])
    del sys.argv[i:i + 2]
    native = types.ModuleType("_rp2")
    native.PIO, native.StateMachine = pio, StateMachine
    sys.modules["_rp2"] = native
    spec = importlib.util.spec_from_file_location("rp2", rp2_arg)
    rp2 = importlib.util.module_from_spec(spec)
    sys.modules["rp2"] = rp2
    spec.loader.exec_module(rp2)
else:
    rp2 = types.ModuleType("rp2")
    rp2.PIO, rp2.StateMachine = pio, StateMachine
    rp2.asm_pio = lambda **kw: lambda f: f
    rp2.asm_pio_encode = lambda instr, sideset_count, sideset_opt=False: (instr, sideset_count)
    sys.modules["rp2"] = rp2

from kagura import Kagura, DeviceError
from kagura import regs as R
from kagura.audio import Audio
from kagura.video import Video
from kagura.terminal import Terminal, TileScreen
from kagura.console import ConsoleStream
from kagura.console import start
from kagura.transport_rp2 import PIOTransport, TransferTimeout, _program
from kagura.transport_rp2 import _owned_sms


class RegisterModel:
    """Minimal queue-aware ABI model. Queue effects happen only at FENCE."""
    def __init__(self):
        self.reg = bytearray(32)
        self.reg[R.REG_ID0:R.REG_CAPS + 1] = bytes((R.ID0, R.ID1, 0, 5, 0x7B))
        self.reg[R.REG_STATUS] = R.STATUS_INIT_DONE
        self.ext = bytearray(256)
        self.ext[R.EXT_SCREEN_HEIGHT] = 180
        self.audio = bytearray(256)
        self.memory = bytearray(0xA800)
        self.pending = []
        self.calls = []
        self.read_requests = 0
        self.closed = False
        self.pcm_prepare_status = R.AUDIO_PCM_STATUS_READY
    def ready(self):
        return True
    def _addr(self):
        return int.from_bytes(self.reg[4:7], "little")
    def _advance(self):
        self.reg[4:7] = ((self._addr() + int.from_bytes(self.reg[16:18], "little")) & 0xFFFFFF).to_bytes(3, "little")
    def _drain(self):
        for op, addr, payload in self.pending:
            if op == "write":
                self.memory[addr] = payload
            else:
                length, fill = payload
                self.memory[addr:addr + length] = bytes((fill,)) * length
        self.pending.clear()
    def write(self, offset, data, inc=False):
        self.calls.append((offset, bytes(data), inc))
        for i, value in enumerate(data):
            off = (offset + i) & 31 if inc else offset
            if off == R.REG_EXT_REG_DATA:
                self.ext[self.reg[R.REG_EXT_REG_INDEX]] = value
            elif off == R.REG_AUDIO_REG_DATA:
                index = self.reg[R.REG_AUDIO_REG_INDEX]
                if index in (0x6F, 0x8F):
                    self.audio[index] = self.pcm_prepare_status if value & R.AUDIO_PCM_CMD_PREPARE else 0
                else:
                    self.audio[index] = value
            elif off == R.REG_VRAM_WRITE:
                self.pending.append(("write", self._addr(), value))
                self._advance()
            elif off == R.REG_VRAM_READ_REQUEST:
                self.read_requests += 1
                self.reg[R.REG_VRAM_READ_RESULT] = self.memory[self._addr()]
                self._advance()
                self.reg[R.REG_STATUS] |= R.STATUS_READ_READY
            elif off == R.REG_COMMAND:
                if value == R.CMD_FENCE:
                    self._drain()
                    self.reg[R.REG_DONE_TAG] = self.reg[R.REG_FENCE_TAG]
                elif value == R.CMD_COMMIT:
                    self._drain()
                elif value == R.CMD_FILL:
                    self.pending.append(("fill", self._addr(),
                                         (int.from_bytes(self.reg[18:20], "little"), self.reg[20])))
            elif off in (R.REG_ERROR_CODE, R.REG_IRQ_STATUS):
                self.reg[off] &= ~value
            else:
                self.reg[off] = value
    def readinto(self, offset, buffer, inc=False):
        for i in range(len(buffer)):
            off = (offset + i) & 31 if inc else offset
            if off == R.REG_EXT_REG_DATA:
                buffer[i] = self.ext[self.reg[R.REG_EXT_REG_INDEX]]
            elif off == R.REG_AUDIO_REG_DATA:
                buffer[i] = self.audio[self.reg[R.REG_AUDIO_REG_INDEX]]
            else:
                buffer[i] = self.reg[off]
            if off == R.REG_VRAM_READ_RESULT:
                self.reg[R.REG_STATUS] &= ~R.STATUS_READ_READY
    def deinit(self):
        self.closed = True


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.model = RegisterModel()
        self.d = Kagura(self.model, timeout_us=500)
        self.d.probe()

    def test_probe(self):
        self.assertEqual((self.d.abi, self.d.height, self.d.caps), ((0, 5), 180, 0x7B))

    def test_abi_zero_requires_exact_minor(self):
        self.model.reg[R.REG_ABI_MINOR] = 4
        with self.assertRaisesRegex(OSError, "ABI"):
            self.d.probe()

    def test_missing_ready_is_bounded(self):
        self.model.ready = lambda: False
        with self.assertRaisesRegex(OSError, "READY"):
            self.d.probe()
        self.assertEqual(self.d.busy, 0)

    def test_vram_write_fence_read(self):
        data = bytes(range(256)) * 8
        self.d.write_memory(0, data)
        self.assertNotEqual(self.model.memory[:2048], data)
        self.d.fence()
        actual = bytearray(2048)
        self.d.read_memory_into(0, actual)
        self.assertEqual(actual, data)
        self.assertEqual(self.model.read_requests, 2048)
        self.assertFalse(self.model.reg[R.REG_STATUS] & R.STATUS_READ_READY)

    def test_fence_wrap_and_nonzero_initial_done(self):
        self.model.reg[R.REG_DONE_TAG] = 255
        self.d.fence()
        self.assertEqual(self.model.reg[R.REG_DONE_TAG], 0)
        self.d.fence()
        self.assertEqual(self.model.reg[R.REG_DONE_TAG], 1)

    def test_fill(self):
        self.d.fill(0x8000, 4096, 0x5A)
        self.d.fence()
        self.assertEqual(self.model.memory[0x8000:0x9000], b"\x5a" * 4096)

    def test_ranges_and_capability(self):
        for address, length in ((0x7FFF, 2), (0x9600, 1), (0x9000, 1), (0x7FFFFF, 2)):
            with self.assertRaises(ValueError):
                self.d.write_memory(address, bytes(length))
        self.d.caps = 0
        with self.assertRaises(NotImplementedError):
            self.d.write_memory(0x400000, b"a")
        with self.assertRaises(NotImplementedError):
            self.d.copy(0x400000, 0, 1)

    def test_error_not_cleared_or_replayed(self):
        self.model.reg[R.REG_ERROR_CODE] = R.ERROR_CODE_FIFO_FULL
        with self.assertRaises(DeviceError) as error:
            self.d.write_memory(0, b"abc")
        self.assertEqual(error.exception.code, R.ERROR_CODE_FIFO_FULL)
        self.assertEqual(len(self.model.pending), 3)
        self.assertEqual(self.d.busy, 0)
        self.assertEqual(self.model.reg[R.REG_ERROR_CODE], R.ERROR_CODE_FIFO_FULL)

    def test_status_timeout(self):
        with self.assertRaisesRegex(OSError, "STATUS"):
            self.d.wait_status(R.STATUS_READ_READY, R.STATUS_READ_READY)
        self.assertEqual(self.d.busy, 0)

    def test_sprite_signed_and_flags(self):
        Video(self.d).sprite(255, -1, -512, tile=1023, palette=15, size16=True, behind=True)
        self.d.fence()
        self.assertEqual(self.model.memory[0xA7F8:0xA800], bytes((255, 3, 0, 78, 255, 63, 0, 0)))

    def test_raster_validate_before_write(self):
        self.model.calls.clear()
        with self.assertRaises(ValueError):
            Video(self.d).raster_scroll(((30, 0, 0), (20, 1, 2)))
        self.assertEqual(self.model.calls, [])

    def test_pulse_pitch(self):
        Audio(self.d).tone(0, 440)
        self.assertEqual(int.from_bytes(self.model.audio[:3], "little"), 153791)

    def test_pcm_error_has_own_status(self):
        self.model.pcm_prepare_status = R.AUDIO_PCM_STATUS_CONFIG_ERROR
        with self.assertRaisesRegex(OSError, "PCM prepare"):
            Audio(self.d).prepare_pcm(0, 0x400000, 0x401000)
        self.assertEqual(self.d.busy, 0)


class TransportTests(unittest.TestCase):
    def setUp(self):
        # Real PIO assembler is exercised separately. Do not consume PIO RAM
        # in every fake transport instance when testing actual rp2.py.
        self.program_patch = patch("kagura.transport_rp2._program", return_value=None)
        self.program_patch.start()
        _owned_sms.clear()
    def tearDown(self):
        self.program_patch.stop()
        _owned_sms.clear()

    def test_read_count_and_dummy(self):
        for mode in ("spi", "qspi"):
            for length in (1, 255, 256):
                _owned_sms.clear()
                t = PIOTransport(mode=mode)
                t._sm.replies = [32, 0, 0] + [0x4B] * length
                result = bytearray(length)
                t.readinto(24, result, True)
                shift = 23 if mode == "spi" else 22
                words = t._sm.words
                self.assertEqual([(w >> shift) & 255 for w in words[:3]], [0xD8, length & 255, 0])
                self.assertEqual(len(words), length + 3)
                self.assertEqual(result, b"K" * length)
                if mode == "qspi":
                    self.assertTrue(words[1] & (1 << 30))
                    self.assertEqual(t._sm.instructions[-1], rp2.asm_pio_encode("set(pindirs, 0)", 1))
                    # A string makes exec() run the assembler on every transfer.
                    self.assertFalse(any(isinstance(i, str) for i in t._sm.instructions))
                else:
                    self.assertEqual(t.last_fifo_status, 32)
                self.assertEqual(t._cs.value(), 1)

    def test_queue_flags_across_wrap(self):
        t = PIOTransport()
        t.write(30, bytes(50), True)
        flags = [word >> 31 for word in t._sm.words[1:]]
        expected = [int(((30 + i) & 31) in (7, 8, 14)) for i in range(50)]
        self.assertEqual(flags, expected)

    def test_busy_stall_abort_then_reuse(self):
        t = PIOTransport(timeout_us=20)
        t._sm.stalled = True
        with self.assertRaises(TransferTimeout):
            t.write(7, b"abcdef")
        self.assertEqual(t._cs.value(), 1)
        self.assertFalse(t._active)
        self.assertEqual(t._sm.init_count, 2)
        t._sm.stalled = False
        t.write(7, b"ok")
        self.assertEqual(len(t._sm.words), 3)

    def test_keyboard_interrupt_aborts(self):
        t = PIOTransport(mode="qspi")
        with patch.object(t, "_xfer", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                t.readinto(24, bytearray(1))
        self.assertEqual(t._cs.value(), 1)
        self.assertFalse(t._active)
        self.assertEqual(t._sm.init_count, 2)

    def test_invalid_config_and_read(self):
        for config in ({"baudrate": 10_000_000}, {"io0": 6}, {"sm_id": 8}, {"mode": "other"}):
            with self.assertRaises(ValueError):
                PIOTransport(**config)
        t = PIOTransport()
        for length in (0, 257):
            with self.assertRaises(ValueError):
                t.readinto(0, bytearray(length))

    def test_release_sm_and_reconnect(self):
        t = PIOTransport()
        with self.assertRaises(RuntimeError):
            PIOTransport()
        t.deinit()
        t.deinit()
        replacement = PIOTransport()
        replacement.deinit()

    def test_disconnected_ready_sends_no_command(self):
        t = PIOTransport()
        t._ready(0)
        with self.assertRaisesRegex(OSError, "READY"):
            t.write(14, b"\x03")
        self.assertEqual(t._cs.value(), 1)
        self.assertEqual(t._sm.words, [])

    def test_interrupt_during_cs_selection(self):
        t = PIOTransport()
        original = t._begin
        def interrupted():
            original()
            raise KeyboardInterrupt
        with patch.object(t, "_begin", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                t.write(7, b"abc")
        self.assertFalse(t._active)
        self.assertEqual(t._cs.value(), 1)

    def test_long_writes_use_dma_with_the_same_words(self):
        data = bytes(range(0, 250, 3)) * 4  # 336 bytes: several DMA chunks
        for mode in ("spi", "qspi"):
            for offset, length in ((7, len(data)), (12, 16), (7, 15)):
                _owned_sms.clear()
                plain = PIOTransport(mode=mode)
                plain.write(offset, data[:length])
                _owned_sms.clear()
                with patch.object(rp2, "DMA", FakeDMA, create=True):
                    t = PIOTransport(mode=mode)
                    t.write(offset, data[:length])
                self.assertEqual(t._sm.words, plain._sm.words)
                self.assertEqual(t._cs.value(), 1)
                self.assertFalse(t._active)

    def test_dma_stall_times_out_and_aborts(self):
        with patch.object(rp2, "DMA", FakeDMA, create=True):
            t = PIOTransport(mode="qspi", timeout_us=20)
            channels = (t._dma_tx, t._dma_rx)
            FakeDMA.stall = True
            try:
                with self.assertRaises(TransferTimeout):
                    t.write(7, bytes(64))
            finally:
                FakeDMA.stall = False
            self.assertFalse(any(dma.active() for dma in channels))
            self.assertEqual(t._cs.value(), 1)
            self.assertFalse(t._active)
            self.assertEqual(t._sm.init_count, 2)
            t.write(7, bytes(64))
            t.deinit()
            self.assertTrue(all(dma.closed for dma in channels))


class TerminalTests(unittest.TestCase):
    def test_wrap_scroll(self):
        t = Terminal(22)
        t.feed(b"a" * 40)
        self.assertEqual((t.x, t.y), (40, 0))
        t.feed(b"b")
        self.assertEqual((t.x, t.y), (1, 1))
        for _ in range(22):
            t.feed(b"\r\nline")
        self.assertEqual(t.y, 21)
        self.assertEqual(t.cells[-40:-36], b"line")

    def test_repl_editing_split_sequences(self):
        t = Terminal(30)
        for data in (b">>> abc", b"\x1b[", b"2D", b"X", b"\x1b[K"):
            t.feed(data)
        self.assertEqual(t.cells[:9], b">>> aX   ")
        self.assertEqual((t.x, t.y), (6, 0))
        t.feed(b"\x1b[2J\x1b[Hnew")
        self.assertEqual(t.cells[:4], b"new ")

    def test_backspace_crlf_tab(self):
        t = Terminal(22)
        t.feed(b"abc\b \bX\r\n\tY")
        self.assertEqual(t.cells[:3], b"abX")
        self.assertEqual(t.cells[40:49], b"        Y")

    def test_utf8_and_unbounded_escape(self):
        t = Terminal(22)
        t.feed("あ".encode()[:1])
        t.feed("あ".encode()[1:] + b"!")
        self.assertEqual(t.cells[:2], b"?!")
        t.feed(b"\x1b[" + b"1" * 1000 + b"m")
        self.assertTrue(t.escape is None or len(t.escape) <= 32)

    def test_malformed_negative_cursor(self):
        t = Terminal(22)
        t.feed(b"\x1b[-100;-100HX")
        self.assertGreaterEqual(t.x, 0)
        self.assertGreaterEqual(t.y, 0)


class FrameBuffer:
    def __init__(self, *args):
        self.pixels = [0] * 64
    def fill(self, value):
        self.pixels[:] = [value] * 64
    def text(self, text, x, y, value):
        if text != " ":
            self.pixels[0] = value
            self.pixels[7] = value
    def pixel(self, x, y):
        return self.pixels[y * 8 + x]


class TileScreenTests(unittest.TestCase):
    def test_font_packing_map_stride_and_720p_padding(self):
        model = RegisterModel()
        model.memory[:32] = bytes([255] * 32)  # prior application tile zero
        d = Kagura(model).probe()
        screen = TileScreen(d)
        framebuf = types.SimpleNamespace(FrameBuffer=FrameBuffer, MONO_HLSB=3)
        with patch.dict(sys.modules, {"framebuf": framebuf}):
            screen.initialize()
        self.assertEqual(model.memory[:32], bytes(32))
        self.assertEqual(model.memory[65 * 32:65 * 32 + 4], b"\x10\x00\x00\x01")
        self.assertEqual(model.memory[0x9400:0x9404], b"\x00\x00\xff\x0f")
        self.assertEqual(model.memory[0x8000:0x8050], b"\x20\x00" * 40)
        self.assertEqual(model.memory[0x8050:0x8080], bytes(48))
        self.assertEqual(model.memory[0x8000 + 22 * 128:0x8000 + 23 * 128], bytes(128))
        screen.feed(b"A\nB")
        screen.flush()
        d.fence()
        self.assertEqual(model.memory[0x8000], 65)
        self.assertEqual(model.memory[0x8080], 66)
        self.assertEqual(model.memory[0xA000:0xA004], b"\x08\x00\x08\x04")
        self.assertEqual(d.busy, 0)


class UART:
    def __init__(self, data=b""):
        self.data = bytearray(data)
    def any(self):
        return len(self.data)
    def deinit(self):
        pass
    def readinto(self, buffer):
        n = min(len(buffer), len(self.data))
        buffer[:n] = self.data[:n]
        del self.data[:n]
        return n or None


class Screen:
    def __init__(self, device=None):
        self.device = device or types.SimpleNamespace(busy=0, deinit=lambda: None)
        self.received = bytearray()
        self.flushes = 0
    def feed(self, data):
        self.received.extend(data)
    def flush(self):
        self.flushes += 1
    def initialize(self):
        self.received.clear()


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.screen = Screen()
        self.s = ConsoleStream(UART(), self.screen, buffer_size=16)
        self.notify = patch.object(os, "dupterm_notify", create=True)
        self.notify_mock = self.notify.start()
    def tearDown(self):
        self.notify.stop()

    def test_uart_nonblocking_and_controls(self):
        buf = bytearray(1)
        self.assertIsNone(self.s.readinto(buf))
        self.s.uart.data.extend(b"\x03\x04\x7f\r")
        result = bytearray()
        while self.s.readinto(buf):
            result.extend(buf)
        self.assertEqual(result, b"\x03\x04\x7f\r")

    def test_output_deferred_until_idle(self):
        self.assertEqual(self.s.write(b">>> 1+1\n2\n"), 10)
        self.assertEqual(self.screen.received, b"")
        self.screen.device.busy = 1
        self.s._tick(None)
        self.assertEqual(self.screen.received, b"")
        self.screen.device.busy = 0
        self.s._tick(None)
        self.assertEqual(self.screen.received, b">>> 1+1\n2\n")

    def test_buffer_overflow_is_bounded_and_counted(self):
        self.s.write(bytes(40))
        self.assertEqual(self.s.dropped, 25)
        self.s._tick(None)
        self.assertEqual(len(self.screen.received), 15)

    def test_input_notification_even_when_display_failed(self):
        self.s.last_error = OSError("display disconnected")
        self.s.uart.data.extend(b"\x03")
        self.s._tick(None)
        self.notify_mock.assert_called_once_with(self.s)

    def test_pause_and_resume(self):
        self.s.write(b"old")
        self.s.pause()
        self.s.write(b"application")
        self.s.resume()
        self.s.write(b"new")
        self.s._tick(None)
        self.assertEqual(self.screen.received, b"new")

    def test_display_error_keeps_stream_alive(self):
        self.s.write(b"text")
        with patch.object(self.screen, "flush", side_effect=OSError("unplugged")):
            self.s._tick(None)
        self.assertIsInstance(self.s.last_error, OSError)
        self.s.uart.data.extend(b"x")
        self.assertEqual(self.s.readinto(bytearray(1)), 1)


class FakeTimer:
    PERIODIC = 1
    def __init__(self, **config):
        self.config = config
        self.closed = False
    def deinit(self):
        self.closed = True


class BootTests(unittest.TestCase):
    def setUp(self):
        self.previous = object()
        self.slot = self.previous
        def dupterm(stream, index):
            previous, self.slot = self.slot, stream
            return previous
        self.patches = [patch.object(os, "dupterm", side_effect=dupterm, create=True),
                        patch.object(os, "dupterm_notify", create=True),
                        patch.object(machine, "UART", return_value=UART(), create=True),
                        patch.object(machine, "Timer", FakeTimer, create=True),
                        patch("kagura.terminal.TileScreen", Screen)]
        for item in self.patches:
            item.start()
    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_boot_attaches_detected_display_and_restores_slot(self):
        d = Kagura(RegisterModel()).probe()
        with patch("kagura.connect", return_value=d), redirect_stdout(io.StringIO()):
            stream = start()
        self.assertIs(self.slot, stream)
        self.assertIs(stream.screen.device, d)
        self.assertFalse(stream._timer.config["hard"])
        timer = stream._timer
        stream.close()
        self.assertIs(self.slot, self.previous)
        self.assertTrue(timer.closed)
        self.assertTrue(d.transport.closed)

    def test_missing_fpga_still_attaches_uart(self):
        with patch("kagura.connect", side_effect=OSError("not detected")), redirect_stdout(io.StringIO()):
            stream = start()
        self.assertIs(self.slot, stream)
        self.assertIsNone(stream.screen)
        self.assertIsInstance(stream.last_error, OSError)
        stream.uart.data.extend(b"1+1\r")
        buffer = bytearray(4)
        self.assertEqual(stream.readinto(buffer), 4)
        self.assertEqual(buffer, b"1+1\r")
        stream.close()

    def test_display_initialization_failure_releases_device(self):
        d = Kagura(RegisterModel()).probe()
        with patch("kagura.connect", return_value=d), patch.object(Screen, "initialize", side_effect=OSError("screen")), redirect_stdout(io.StringIO()):
            stream = start()
        self.assertTrue(d.transport.closed)
        self.assertIsNone(stream.screen)
        self.assertIs(self.slot, stream)
        stream.close()

    def test_timer_failure_restores_previous_stream(self):
        stream = ConsoleStream(UART())
        with patch.object(machine, "Timer", side_effect=OSError("timer")):
            with self.assertRaises(OSError):
                stream.attach()
        self.assertIs(self.slot, self.previous)


@unittest.skipUnless(rp2_arg, "provide --rp2 for upstream PIO assembler/timing checks")
class AssemblerTests(unittest.TestCase):
    def test_real_assembler_and_existing_cycle_model(self):
        # Feed actual Python-assembled opcodes to the existing FPGA timing
        # model, including 50 delay draws, BUSY gating and QSPI turnaround.
        text = ""
        for lanes, name in ((1, "kagura_spi"), (4, "kagura_qspi")):
            program = _program(lanes, 8)
            code = program[0]
            self.assertEqual(code[3], 0x2008)
            self.assertEqual(len(code), 9 if lanes == 1 else 13)
            ctrl = program[4]
            text += "#define %s_wrap_target %d\n" % (name, (ctrl >> 7) & 31)
            text += "#define %s_wrap %d\n" % (name, (ctrl >> 12) & 31)
            text += "static const uint16_t %s_program_instructions[] = {\n" % name
            text += "".join("0x%04x,\n" % word for word in code) + "};\n"
        spec = importlib.util.spec_from_file_location("pio_model", ROOT / "software/pico/tests/test_pio_timing.py")
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        directory = ROOT / "build/micropython-check"
        directory.mkdir(parents=True, exist_ok=True)
        header = directory / "python-host.pio.h"
        header.write_text(text)
        self.assertEqual(model.main(str(header)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
