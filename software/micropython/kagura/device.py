# SPDX-License-Identifier: Apache-2.0
"""Register ABI 0.6. One owner/task; callbacks must check busy before use."""
from time import ticks_us, ticks_diff
from . import regs as R


class DeviceError(OSError):
    def __init__(self, code):
        self.code = code
        super().__init__("KAGURA ERROR_CODE=0x%02x" % code)


def operation(method):
    # Keeps the soft console timer out of compound INDEX/ADDR operations.
    def run(self, *args, **kwargs):
        self.busy += 1
        try:
            return method(self, *args, **kwargs)
        finally:
            self.busy -= 1
    return run


_LINK_PATTERNS = (b"\x00\xff\x00\xff", b"\xff\x00\xff\x00", b"\x55\xaa\x55\xaa",
                  b"\xaa\x55\xaa\x55", b"\x0f\xf0\x3c\xc3", b"\x01\x02\x04\x08",
                  b"\x10\x20\x40\x80", b"\xfe\xfd\xfb\xf7")


def _range(value, lo, hi, name):
    if not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(name)


def _le(value, size):
    return bytes((value >> (8 * i)) & 255 for i in range(size))


class Kagura:
    def __init__(self, transport, timeout_us=100_000):
        _range(timeout_us, 1, 10_000_000, "timeout_us")
        self.transport = transport
        self.timeout_us = timeout_us
        self.busy = 0
        self.caps = 0
        self.height = 0
        self.abi = None
        self._one = bytearray(1)
        self._read_pending = False

    @operation
    def probe(self, ready_timeout_us=None):
        self._wait(self.transport.idle, "READY", ready_timeout_us)
        ids = bytearray(5)
        self.transport.readinto(R.REG_ID0, ids, True)
        if ids[0] != R.ID0 or ids[1] != R.ID1:
            raise OSError("KAGURA ID mismatch")
        # ABI major zero has no compatibility promise between minors.
        if tuple(ids[2:4]) != (R.ABI_MAJOR, R.ABI_MINOR):
            raise OSError("unsupported KAGURA ABI %d.%d" % (ids[2], ids[3]))
        self.abi = tuple(ids[2:4])
        self.caps = ids[4]
        self.wait_status(R.STATUS_INIT_DONE, R.STATUS_INIT_DONE)
        self.height = self.ext_read(R.EXT_SCREEN_HEIGHT)
        if self.height not in (180, 240):
            raise OSError("unexpected screen height")
        return self

    @operation
    def check_link(self):
        """Raise OSError unless repeated reads and writes arrive intact.

        The patterns go to LENGTH_L..FENCE_TAG, which FILL, COPY and FENCE
        always rewrite first, so no device state changes.
        """
        expected = bytes((R.ID0, R.ID1) + self.abi + (self.caps,))
        ids = bytearray(5)
        back = bytearray(4)
        self.clear_errors()
        for pattern in _LINK_PATTERNS:
            self.transport.readinto(R.REG_ID0, ids, True)
            self.transport.write(R.REG_LENGTH_L, pattern, True)
            self.transport.readinto(R.REG_LENGTH_L, back, True)
            if ids != expected or back != pattern:
                raise OSError("KAGURA link check failed")
        self.check_errors()

    def _wait(self, predicate, name, timeout_us=None):
        if timeout_us is None:
            timeout_us = self.timeout_us
        _range(timeout_us, 1, 10_000_000, "timeout_us")
        start = ticks_us()
        while not predicate():
            if ticks_diff(ticks_us(), start) >= timeout_us:
                raise OSError("KAGURA timeout: " + name)

    @operation
    def write_reg(self, offset, value):
        _range(value, 0, 255, "register value")
        self.transport.write(offset, bytes((value,)))

    @operation
    def read_reg(self, offset):
        self.transport.readinto(offset, self._one)
        return self._one[0]

    @operation
    def ext_write(self, index, value):
        _range(index, 0, 255, "EXT index")
        _range(value, 0, 255, "EXT value")
        self.transport.write(R.REG_EXT_REG_INDEX, bytes((index, value)), True)

    @operation
    def ext_read(self, index):
        self.write_reg(R.REG_EXT_REG_INDEX, index)
        return self.read_reg(R.REG_EXT_REG_DATA)

    @operation
    def audio_write(self, index, value):
        _range(index, 0, 255, "audio index")
        _range(value, 0, 255, "audio value")
        self.transport.write(R.REG_AUDIO_REG_INDEX, bytes((index, value)), True)

    @operation
    def audio_read(self, index):
        self.write_reg(R.REG_AUDIO_REG_INDEX, index)
        return self.read_reg(R.REG_AUDIO_REG_DATA)

    @operation
    def check_errors(self):
        code = self.read_reg(R.REG_ERROR_CODE)
        if code:
            raise DeviceError(code)

    @operation
    def clear_errors(self):
        self.write_reg(R.REG_ERROR_CODE, 255)
        self.write_reg(R.REG_IRQ_STATUS, R.IRQ_STATUS_ERROR)

    def require(self, mask):
        if self.caps & mask != mask:
            raise NotImplementedError("KAGURA capability 0x%02x required" % mask)

    def _memory_range(self, address, length):
        _range(address, 0, 0xFFFFFF, "address")
        _range(length, 0, 0x400000, "length")
        regions = ((0, 0x8000), (0x8000, 0x9000), (0x9000, 0x9100), (0x9400, 0x9600),
                   (0x9800, 0x9A00), (0xA000, 0xA800), (0xB000, 0xC600),
                   (0x400000, 0x800000))
        for start, end in regions:
            if start <= address < end and address + length <= end:
                if start == 0x400000:
                    self.require(R.CAPS_PSRAM)
                return
        raise ValueError("memory range must stay inside one public region")

    def _address(self, address):
        self.transport.write(R.REG_VRAM_ADDR_L, _le(address, 3), True)

    @operation
    def write_memory(self, address, data):
        data = memoryview(data)
        self._memory_range(address, len(data))
        if not data:
            return
        self.transport.write(R.REG_INC_L, b"\x01\x00", True)
        self._address(address)
        self.transport.write(R.REG_VRAM_WRITE, data)
        self.check_errors()

    @operation
    def read_memory_into(self, address, buffer):
        self._memory_range(address, len(buffer))
        if self._read_pending:
            # An interrupted read left its result unread; a new READ_REQUEST
            # would be rejected as READ_COLLISION and return that stale byte.
            self.wait_status(R.STATUS_READ_BUSY, 0)
            if self.read_reg(R.REG_STATUS) & R.STATUS_READ_READY:
                self.read_reg(R.REG_VRAM_READ_RESULT)
            self._read_pending = False
        self.transport.write(R.REG_INC_L, b"\x01\x00", True)
        self._address(address)
        for i in range(len(buffer)):
            self._read_pending = True
            self.write_reg(R.REG_VRAM_READ_REQUEST, 0)
            self.wait_status(R.STATUS_READ_READY, R.STATUS_READ_READY)
            buffer[i] = self.read_reg(R.REG_VRAM_READ_RESULT)
            self._read_pending = False
        self.write_reg(R.REG_IRQ_STATUS, R.IRQ_STATUS_READ_DONE)
        self.check_errors()
        return len(buffer)

    @operation
    def wait_status(self, mask, value):
        self._wait(lambda: self.read_reg(R.REG_STATUS) & mask == value, "STATUS")

    @operation
    def fill(self, address, length, value=0):
        _range(length, 1, 65535, "fill length")
        _range(value, 0, 255, "fill value")
        self._memory_range(address, length)
        self._address(address)
        self.transport.write(R.REG_LENGTH_L, _le(length, 2) + bytes((value,)), True)
        self.write_reg(R.REG_COMMAND, R.CMD_FILL)
        self.check_errors()

    @operation
    def copy(self, source, destination, length):
        self.require(R.CAPS_PSRAM)
        _range(length, 1, 65535, "copy length")
        if not 0x400000 <= source < source + length <= 0x800000 or destination >= 0x400000:
            raise ValueError("COPY requires PSRAM source and VRAM destination")
        self._memory_range(destination, length)
        for i in range(3):
            self.ext_write(R.EXT_COPY_SRC_L + i, (source >> (8 * i)) & 255)
        self._address(destination)
        self.transport.write(R.REG_LENGTH_L, _le(length, 2), True)
        self.write_reg(R.REG_COMMAND, R.CMD_COPY)
        self.check_errors()

    @operation
    def fence(self):
        # Choose a tag different from the *current* DONE_TAG, including reset
        # and wrap. A cached local counter could match a stale completion.
        tag = (self.read_reg(R.REG_DONE_TAG) + 1) & 255
        self.write_reg(R.REG_FENCE_TAG, tag)
        self.write_reg(R.REG_COMMAND, R.CMD_FENCE)
        self.check_errors()
        self._wait(lambda: self.read_reg(R.REG_DONE_TAG) == tag, "FENCE")
        self.check_errors()

    @operation
    def commit(self, wait=True):
        # wait=False returns before the next frame applies the shadows; the
        # next commit still waits first, so shadows are never overwritten early.
        self.wait_status(R.STATUS_COMMIT_BUSY, 0)
        self.write_reg(R.REG_COMMAND, R.CMD_COMMIT)
        self.check_errors()
        if wait:
            self.wait_status(R.STATUS_COMMIT_BUSY, 0)

    @operation
    def audio_commit(self):
        self._wait(lambda: not self.audio_read(R.AUDIO_STATUS) & R.AUDIO_STATUS_APPLY_BUSY,
                   "AUDIO_COMMIT")
        self.write_reg(R.REG_COMMAND, R.CMD_AUDIO_COMMIT)
        self.check_errors()
        self._wait(lambda: not self.audio_read(R.AUDIO_STATUS) & R.AUDIO_STATUS_APPLY_BUSY,
                   "AUDIO_COMMIT")

    def deinit(self):
        self.transport.deinit()
