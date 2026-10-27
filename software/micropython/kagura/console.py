# SPDX-License-Identifier: Apache-2.0
"""Nonblocking dupterm stream: UART RX -> REPL, output -> buffered HDMI.

Only the soft timer touches display hardware. UART notification also enables
Ctrl-C during a running Python program, rather than just while at the prompt.
"""
from io import IOBase


class ConsoleStream(IOBase):
    def __init__(self, uart, screen=None, buffer_size=8192):
        if buffer_size < 2:
            raise ValueError("console buffer size")
        self.uart, self.screen = uart, screen
        self._buffer = bytearray(buffer_size)
        self._head = self._tail = 0
        self.dropped = 0
        self.last_error = None
        self.paused = False
        self._updating = False
        self._timer = None
        self._previous = None
        self._attached = False

    def readinto(self, buffer):
        if not self.uart.any():
            return None  # nonblocking stream: no input, not EOF
        return self.uart.readinto(buffer)

    def write(self, data):
        if self.screen is None or self.paused:
            return len(data)
        for c in data:
            next_head = (self._head + 1) % len(self._buffer)
            if next_head == self._tail:
                self.dropped += 1
            else:
                self._buffer[self._head] = c
                self._head = next_head
        return len(data)

    def ioctl(self, request, flags):
        if request == 3:  # MP_STREAM_POLL
            return ((1 if self.uart.any() else 0) | 4) & flags
        return 0

    def _tick(self, timer):
        import os
        self._flush_display()
        # No register access in UART IRQ. Poll at 20ms from a soft timer so
        # RX_IDLE and continuous input both work, including interrupt chars.
        # This MUST be the last call: dupterm_notify may pend KeyboardInterrupt.
        # A subsequent Python branch could raise it inside the protected timer
        # callback (especially on the threaded RP2 build), swallowing Ctrl-C
        # instead of interrupting the foreground program.
        if self.uart.any():
            return os.dupterm_notify(self)

    def _flush_display(self):
        if (self._updating or self.paused or self.screen is None
                or self.screen.device.busy or self.last_error is not None):
            return
        self._updating = True
        try:
            # Bound each update; large output cannot monopolise the VM.
            data = bytearray()
            for _ in range(256):
                if self._tail == self._head:
                    break
                data.append(self._buffer[self._tail])
                self._tail = (self._tail + 1) % len(self._buffer)
            if data:
                self.screen.feed(data)
                self.screen.flush()
        except Exception as error:
            # Preserve UART/USB access after unplug/reset; no print recursion.
            self.last_error = error
        finally:
            self._updating = False

    def attach(self):
        import os
        from machine import Timer
        if not hasattr(os, "dupterm") or not hasattr(os, "dupterm_notify"):
            raise RuntimeError("firmware needs os.dupterm and os.dupterm_notify; see README")
        if self._attached:
            return self
        self._previous = os.dupterm(self, 0)
        self._attached = True
        try:
            self._timer = Timer(period=20, mode=Timer.PERIODIC,
                                callback=self._tick, hard=False)
        except BaseException:
            self.detach()
            raise
        return self

    def detach(self):
        import os
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None
        if self._attached:
            os.dupterm(self._previous, 0)
            self._attached = False

    def pause(self):
        self.paused = True
        self._tail = self._head

    def resume(self):
        # Reclaims console tiles, map, palette and OAM after an application.
        if self.screen is not None:
            self.screen.initialize()
        self.last_error = None
        self.paused = False

    def close(self):
        self.detach()
        self.uart.deinit()
        if self.screen is not None:
            self.screen.device.deinit()


def start(mode="spi", baudrate=1_000_000, uart_id=0, tx=0, rx=1,
          uart_baudrate=115200, ready_timeout_us=2_000_000, **transport_config):
    """Auto-detect once at boot. Missing FPGA leaves UART + USB REPL usable.

    Return a ConsoleStream. Inspect .screen/.last_error for detection status.
    UART TX is reserved but output stays on HDMI/USB (RX-only keyboard).
    """
    import os
    from machine import Pin, UART
    if not hasattr(os, "dupterm") or not hasattr(os, "dupterm_notify"):
        raise RuntimeError("KAGURA console requires dupterm-enabled firmware")
    uart = UART(uart_id, baudrate=uart_baudrate, bits=8, parity=None, stop=1,
                tx=Pin(tx), rx=Pin(rx), timeout=0, timeout_char=0, rxbuf=1024)
    stream = ConsoleStream(uart)
    device = None
    try:
        from . import connect
        from .terminal import TileScreen
        try:
            device = connect(mode=mode, baudrate=baudrate,
                             ready_timeout_us=ready_timeout_us, **transport_config)
            device.clear_errors()
            stream.screen = TileScreen(device)
            stream.screen.initialize()
        except Exception as error:
            if device is not None:
                device.deinit()
            stream.screen = None
            stream.last_error = error
        stream.attach()
    except BaseException:
        if device is not None:
            device.deinit()
        uart.deinit()
        raise
    if stream.screen is not None:
        print("KAGURA-9 HDMI console; UART%d RX GP%d %d baud" % (uart_id, rx, uart_baudrate))
    else:
        print("KAGURA unavailable; UART keyboard + USB REPL active:", stream.last_error)
    return stream
