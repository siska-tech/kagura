# SPDX-License-Identifier: Apache-2.0
"""Keyboard input for the native desktop: terminal bytes -> normalized keys.

Two parts, kept apart so that another input device can replace either:

* TerminalKeys decodes the bytes of a VT/xterm-style terminal (a USB or UART
  terminal, or a USB HID-to-UART bridge that speaks the same sequences) into
  two calls on a sink, normally kagura_desktop.Desktop:
      sink.key(KEY_*, ch, MOD_*)      physical keys
      sink.text(buffer)               UTF-8 text, never through ch
  A bridge with its own protocol needs only a decoder making the same calls.
* StdinSource reads what is available on sys.stdin without blocking. On the
  board that is the console's stream: UART RX (dupterm) and USB CDC. The
  console stays the only reader of the UART, and Ctrl+C stays MicroPython's
  KeyboardInterrupt (it never reaches this code; nothing here changes
  kbd_intr).

Terminals send presses only: there are no key releases, and auto-repeat
arrives as repeated bytes, so there is no repeat logic here. A lone Escape is
reported after esc_ms without a following byte. feed() and expire()
allocate nothing.

Decoded keys:
  printable ASCII            KEY_CHAR + ch
  UTF-8 (2..4 bytes)         text()
  CR, LF, CRLF               KEY_ENTER (CRLF once); with lone_lf_ctrl_j, a lone LF
                             is Ctrl+J (KEY_CHAR + j, MOD_CTRL) for SKK
  Tab, BS or DEL             KEY_TAB, KEY_BACKSPACE
  Ctrl+letter (0x01..0x1A)   KEY_CHAR + letter, MOD_CTRL (e.g. Ctrl+A, Ctrl+W)
  ESC [ A B C D / H F        arrows / Home End, with ;mod (1;2A is Shift+Up)
  ESC O A B C D / H F        the same in application mode
  ESC [ 1~ 7~ / 4~ 8~        Home / End
  ESC [ 2~ / 3~              Insert / Delete (2;5~ Ctrl+Insert, 2;2~ Shift+Insert,
                             3;2~ Shift+Delete)
  ESC [ 5~ / 6~              PgUp / PgDn
  ESC [ 17~ / 21~            F6 / F10
  ESC [ Z                    Shift+Tab
  ESC x                      x with MOD_ALT
Anything else (other F keys, bracketed-paste markers, SGR mouse reports) is
consumed and counted in `ignored`. X10 mouse reports (ESC [ M + 3 raw bytes) are
not recognised; terminals send them only when asked to.
"""
import time

import kagura_desktop as kd

_NORMAL, _ESC, _CSI, _SS3 = 0, 1, 2, 3
_FINAL = {ord('A'): kd.KEY_UP, ord('B'): kd.KEY_DOWN, ord('C'): kd.KEY_RIGHT,
          ord('D'): kd.KEY_LEFT, ord('H'): kd.KEY_HOME, ord('F'): kd.KEY_END}
_TILDE = {1: kd.KEY_HOME, 7: kd.KEY_HOME, 4: kd.KEY_END, 8: kd.KEY_END,
          2: kd.KEY_INSERT, 3: kd.KEY_DELETE, 5: kd.KEY_PGUP, 6: kd.KEY_PGDN, 17: kd.KEY_F6, 21: kd.KEY_F10}


def _ms():
    return time.ticks_ms() if hasattr(time, 'ticks_ms') else int(time.time() * 1000)


def _diff(a, b):
    return time.ticks_diff(a, b) if hasattr(time, 'ticks_diff') else a - b


class TerminalKeys:
    def __init__(self, sink, esc_ms=50, clock=_ms, lone_lf_ctrl_j=False):
        self.sink, self.esc_ms, self.clock = sink, esc_ms, clock
        # Terminals send CR for Enter: a lone LF is then Ctrl+J (the SKK key).
        self.lone_lf_ctrl_j = lone_lf_ctrl_j
        self._state = _NORMAL
        self._since = 0
        self._p = [0, 0]          # CSI parameters
        self._np = 0
        self._cr = False
        self._utf = bytearray(4)
        self._views = (None, None, memoryview(self._utf)[:2], memoryview(self._utf)[:3],
                       memoryview(self._utf)[:4])
        self._need = self._have = 0
        self.keys = self.texts = self.ignored = self.invalid = 0

    def _key(self, k, ch=0, mods=0):
        self.keys += 1
        self.sink.key(k, ch, mods)

    def expire(self):
        """Reports a lone Escape once esc_ms passed without a following byte."""
        if self._state == _ESC and _diff(self.clock(), self._since) >= self.esc_ms:
            self._state = _NORMAL
            self._key(kd.KEY_ESCAPE)
        elif self._state != _NORMAL and _diff(self.clock(), self._since) >= 4 * self.esc_ms:
            self._state = _NORMAL       # a cut-off sequence: drop it
            self.ignored += 1

    def feed(self, data, n=None):
        """Decodes data[:n] (bytes, bytearray or memoryview)."""
        if n is None:
            n = len(data)
        for i in range(n):
            self._byte(data[i])

    def _byte(self, b):
        st = self._state
        if st == _CSI:
            if 0x30 <= b <= 0x39:
                if self._np == 0:
                    self._np = 1
                self._p[self._np - 1] = self._p[self._np - 1] * 10 + b - 0x30
                if self._p[self._np - 1] > 9999:
                    self._p[self._np - 1] = 9999
            elif b == 0x3B:             # ';'
                if self._np == 0:
                    self._np = 1
                if self._np < 2:
                    self._np += 1
            elif 0x40 <= b <= 0x7E:     # final byte
                self._state = _NORMAL
                self._csi(b)
            elif not 0x20 <= b <= 0x3F:  # not a parameter or intermediate: abandon
                self._state = _NORMAL
                self.ignored += 1
                self._byte(b)
            return
        if st == _SS3:
            self._state = _NORMAL
            k = _FINAL.get(b)
            if k is None:
                self.ignored += 1
            else:
                self._key(k)
            return
        if st == _ESC:
            self._state = _NORMAL
            if b == 0x5B:               # '['
                self._state = _CSI
                self._p[0] = self._p[1] = 0
                self._np = 0
                return
            if b == 0x4F:               # 'O'
                self._state = _SS3
                return
            if b == 0x1B:               # ESC ESC: the first was a lone Escape
                self._key(kd.KEY_ESCAPE)
                self._state = _ESC
                self._since = self.clock()
                return
            if 0x20 <= b <= 0x7E:
                self._key(kd.KEY_CHAR, b, kd.MOD_ALT)
                return
            self._key(kd.KEY_ESCAPE)    # then the byte on its own
        if self._need:
            if 0x80 <= b <= 0xBF:
                self._utf[self._have] = b
                self._have += 1
                if self._have == self._need:
                    self._need = 0
                    self.texts += 1
                    try:
                        self.sink.text(self._views[self._have])
                    except ValueError:  # not a scalar value (overlong, surrogate)
                        self.invalid += 1
                return
            self._need = 0              # cut short: drop it, decode b afresh
            self.invalid += 1
        cr = self._cr
        self._cr = b == 0x0D
        if b >= 0x80:
            need = 2 if 0xC2 <= b <= 0xDF else 3 if 0xE0 <= b <= 0xEF else 4 if 0xF0 <= b <= 0xF4 else 0
            if need:
                self._utf[0] = b
                self._need, self._have = need, 1
            else:
                self.invalid += 1
        elif b >= 0x20:
            if b == 0x7F:
                self._key(kd.KEY_BACKSPACE)
            else:
                self._key(kd.KEY_CHAR, b)
        elif b == 0x0D:
            self._key(kd.KEY_ENTER)
        elif b == 0x0A:
            if not cr:
                if self.lone_lf_ctrl_j:
                    self._key(kd.KEY_CHAR, 0x6A, kd.MOD_CTRL)
                else:
                    self._key(kd.KEY_ENTER)
        elif b == 0x09:
            self._key(kd.KEY_TAB)
        elif b == 0x08:
            self._key(kd.KEY_BACKSPACE)
        elif b == 0x1B:
            self._state = _ESC
            self._since = self.clock()
        elif 0x01 <= b <= 0x1A:
            self._key(kd.KEY_CHAR, 0x60 + b, kd.MOD_CTRL)
        else:
            self.ignored += 1

    def _csi(self, final):
        p0, p1 = self._p[0], self._p[1]
        m = p1 - 1 if self._np >= 2 and p1 >= 2 else 0
        mods = (kd.MOD_SHIFT if m & 1 else 0) | (kd.MOD_ALT if m & 2 else 0) | (kd.MOD_CTRL if m & 4 else 0)
        if final == 0x7E:               # '~'
            k = _TILDE.get(p0)
        elif final == 0x5A:             # 'Z': Shift+Tab
            k, mods = kd.KEY_TAB, kd.MOD_SHIFT
        else:
            k = _FINAL.get(final)
        if k is None:
            self.ignored += 1
        else:
            self._key(k, 0, mods)


class StdinSource:
    """Nonblocking reads from sys.stdin (console UART and USB CDC on the
    board). pump() reads at most limit bytes, so a burst of input cannot
    starve the frame loop; the rest waits in the input buffers."""
    def __init__(self, stream=None, poller=None):
        if stream is None:
            import sys
            stream = getattr(sys.stdin, 'buffer', sys.stdin)
        if poller is None:
            import select
            poller = select.poll()
        self.stream, self.poller = stream, poller
        self._byte = bytearray(1)
        poller.register(stream, 1)      # POLLIN

    def pump(self, keys, limit=64, each=False):
        """Feeds available bytes to keys; returns how many were read.

        each=True returns as soon as a key or text was decoded. An
        application then handles its events before the next key is routed:
        when Ctrl+S opens a dialog, the name typed right after it goes into
        the dialog, not into the document, however fast the bytes arrive."""
        n = 0
        seen = keys.keys + keys.texts
        while n < limit and self.poller.poll(0):
            if not self.stream.readinto(self._byte):
                break
            keys._byte(self._byte[0])
            n += 1
            if each and keys.keys + keys.texts != seen:
                break
        keys.expire()
        return n

    def close(self):
        try:
            self.poller.unregister(self.stream)
        except (OSError, ValueError, AttributeError):
            pass
