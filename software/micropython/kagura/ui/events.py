# SPDX-License-Identifier: Apache-2.0
"""Bounded input queue and incremental terminal keyboard adapter."""
import time


def now_us():
    if hasattr(time, 'ticks_us'):
        return time.ticks_us()
    return time.monotonic_ns() // 1000


def elapsed(a, b):
    if hasattr(time, 'ticks_diff'):
        return time.ticks_diff(a, b)
    return a - b


class Event:
    def __init__(self, key, text='', shift=False, kind='press', repeat=False):
        self.key, self.text, self.shift = key, text, shift
        self.kind, self.repeat = kind, repeat
        self.timestamp = now_us()


class EventQueue:
    """Drop newest on overflow; post() returns False. No synthetic key-up state."""
    def __init__(self, capacity=32):
        if capacity < 1:
            raise ValueError('queue capacity')
        self._items = [None] * capacity
        self._head = self._tail = self._count = 0
        self.dropped = 0

    def post(self, event):
        if self._count == len(self._items):
            self.dropped += 1
            return False
        self._items[self._head] = event
        self._head = (self._head + 1) % len(self._items)
        self._count += 1
        return True

    def pop(self):
        if not self._count:
            return None
        event = self._items[self._tail]
        self._items[self._tail] = None
        self._tail = (self._tail + 1) % len(self._items)
        self._count -= 1
        return event


class TerminalInput:
    """Call feed(bytes), or poll(queue) with a nonblocking readinto stream.

    UART terminals supply repeated press bytes, not physical release events.
    Standalone Escape is emitted after 30ms, using the injected clock if given.
    Input must have exactly one reader: detach dupterm before using its UART.
    """
    _keys = {b'[A': 'up', b'[B': 'down', b'[C': 'right', b'[D': 'left',
             b'[Z': 'tab', b'[3~': 'delete', b'OA': 'up', b'OB': 'down',
             b'OC': 'right', b'OD': 'left'}

    def __init__(self, stream=None, clock=now_us):
        self.stream, self.clock = stream, clock
        self._buffer = bytearray(32)
        self._escape = None
        self._since = 0
        self._utf8 = bytearray()
        self._needed = 0
        self._cr = False

    def expire(self, queue):
        if self._escape is not None and elapsed(self.clock(), self._since) >= 30000:
            self._escape = None
            queue.post(Event('escape'))

    def feed(self, data, queue):
        for byte in data:
            if byte == 10 and self._cr:
                self._cr = False
                continue
            self._cr = byte == 13
            if byte == 27:
                if self._escape is not None:
                    queue.post(Event('escape'))
                self._utf8[:] = b''
                self._needed = 0
                self._escape = b''
                self._since = self.clock()
                continue
            if self._escape is not None:
                seq = self._escape + bytes((byte,))
                if seq in self._keys:
                    queue.post(Event(self._keys[seq], shift=seq == b'[Z'))
                    self._escape = None
                elif len(seq) > 16 or seq[:1] not in (b'[', b'O') or (len(seq) > 1 and 64 <= byte <= 126):
                    self._escape = None  # consume unsupported CSI/SS3 including parameters
                else:
                    self._escape = seq
                continue
            if byte in (8, 127, 9, 10, 13):
                self._utf8[:] = b''
                self._needed = 0
                queue.post(Event('backspace' if byte in (8, 127) else
                                 'tab' if byte == 9 else 'enter'))
            elif byte >= 32:
                if not self._needed:
                    if byte < 128:
                        queue.post(Event('text', chr(byte)))
                        continue
                    self._needed = 2 if 194 <= byte <= 223 else 3 if 224 <= byte <= 239 else 4 if 240 <= byte <= 244 else 0
                    self._utf8[:] = b''
                    if not self._needed:
                        continue
                elif not 128 <= byte <= 191:
                    self._utf8[:] = b''
                    self._needed = 0
                    continue
                self._utf8.append(byte)
                if len(self._utf8) == self._needed:
                    try:
                        value = self._utf8.decode('utf-8')
                    except UnicodeError:
                        value = '\ufffd'
                    queue.post(Event('text', value))
                    self._utf8[:] = b''
                    self._needed = 0

    def poll(self, queue):
        self.expire(queue)
        if self.stream is not None:
            n = self.stream.readinto(self._buffer)
            if n:
                self.feed(memoryview(self._buffer)[:n], queue)


class StdinInput(TerminalInput):
    """USB CDC / binary stdin, polled one available byte at a time.

    readinto(1) avoids blocking for a complete UTF-8 character or a full buffer.
    The caller must stop other stdin readers while the UI owns input.
    """
    def __init__(self, stream=None, poller=None, clock=now_us):
        super().__init__(clock=clock)
        if stream is None:
            import sys
            stream = getattr(sys.stdin, 'buffer', sys.stdin)
        if not hasattr(stream, 'readinto'):
            raise ValueError('stdin adapter requires a binary readinto stream')
        if poller is None:
            from select import poll
            poller = poll()
        self.stdin, self.poller = stream, poller
        self._byte = bytearray(1)
        self.poller.register(stream, 1)  # POLLIN / MP_STREAM_POLL_RD

    def poll(self, queue):
        self.expire(queue)
        for _ in range(32):
            if not self.poller.poll(0):
                break
            if not self.stdin.readinto(self._byte):
                break
            self.feed(self._byte, queue)
