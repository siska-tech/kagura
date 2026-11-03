# SPDX-License-Identifier: Apache-2.0
"""Keyboard input path on the RP2040, from RAM (no flashing, no file writes).

Runs software/micropython/kagura/keyinput.py on the board through the raw
REPL and drives it with real bytes over USB CDC, the same stdin a terminal
uses. Checks, in order:
  probe    firmware features (kagura_desktop text()/fields?), free heap, console
  decode   terminal sequences (split across USB packets, UTF-8, Ctrl keys,
           F6/F10, Shift/Ctrl+Insert, Shift+Delete, a lone Escape) decoded to
           exactly the expected key()/text() calls
  burst    2,000 bytes sent at once: none lost, throughput
  bench    decoder cost per byte, heap allocation (heap_lock), idle poll cost,
           memmove of 1..16 KB (the flat editor buffer's worst case per key)
  ctrl-c   Ctrl+C during a running input loop raises KeyboardInterrupt and
           the REPL answers afterwards (the interrupt is never disabled)

  python tools/kagura-keyboard-device.py [--out FILE] [--port P --expected-serial S]

Windows: uv CPython with build/transport-analysis/python-deps (mpremote,
pyserial). Never prints the USB serial. Stops at the first failure.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/c-gem-desktop/tools'))
import rp2040_sram_bench as dev  # noqa: E402

# kagura_desktop key codes (core/kd_app.h); the board's firmware may predate
# KEY_INSERT, so the RAM copy of keyinput gets it from here if missing.
KEY_CHAR, KEY_LEFT, KEY_ENTER, KEY_ESCAPE, KEY_TAB, KEY_BACKSPACE, KEY_DELETE = 1, 4, 6, 7, 8, 9, 10
KEY_F6, KEY_F10, KEY_INSERT = 13, 14, 15
SHIFT, CTRL, ALT = 1, 2, 4

SHIM = '''
import kagura_desktop as _kd0
class _KD:
    pass
kd = _KD()
for _n in dir(_kd0):
    setattr(kd, _n, getattr(_kd0, _n))
if not hasattr(kd, 'KEY_INSERT'):
    kd.KEY_INSERT = %d
''' % KEY_INSERT


def keyinput_source():
    src = (ROOT / 'software/micropython/kagura/keyinput.py').read_text(encoding='utf8')
    return SHIM + src.replace('import kagura_desktop as kd\n', '')


PROBE = '''
import gc, kagura_desktop
gc.collect()
import __main__
c = getattr(__main__, 'kagura_console', None)
print('PROBE text', hasattr(kagura_desktop.Desktop, 'text'), 'insert', hasattr(kagura_desktop, 'KEY_INSERT'),
      'free', gc.mem_free(), 'console', c is not None, 'paused', getattr(c, 'paused', None))
'''

DECODE = '''
import time
class Rec:
    stop = False
    def key(self, k, ch=0, mods=0):
        print('K', k, ch, mods)
        if k == kd.KEY_CHAR and ch == 113 and mods == kd.MOD_ALT:
            Rec.stop = True
    def text(self, b):
        print('T', bytes(b).hex())
keys = TerminalKeys(Rec())
src = StdinSource()
print('READY')
while not Rec.stop:
    if not src.pump(keys):
        time.sleep_ms(1)
src.close()
print('DECODED', keys.keys, keys.texts, keys.ignored, keys.invalid)
'''

BURST = '''
import time
class Count:
    n = 0
    stop = False
    t0 = 0
    def key(self, k, ch=0, mods=0):
        if Count.n == 0:
            Count.t0 = time.ticks_us()
        if k == kd.KEY_CHAR and ch == 113 and mods == kd.MOD_ALT:
            Count.stop = True
            Count.t1 = time.ticks_us()
        else:
            Count.n += 1
    def text(self, b):
        Count.n += 1
keys = TerminalKeys(Count())
src = StdinSource()
print('READY')
while not Count.stop:
    src.pump(keys, 256)
src.close()
print('BURST', Count.n, time.ticks_diff(Count.t1, Count.t0))
'''

BENCH = '''
import time, gc, micropython
class Null:
    def key(self, k, ch=0, mods=0):
        pass
    def text(self, b):
        pass
data = bytearray(('hello \\x1b[1;2D\\u795e\\u697d\\r\\n\\x1b[21~\\x1b[2;5~e\\u0301\\x01' * 25).encode())
keys = TerminalKeys(Null(), clock=lambda: 0)
keys.feed(data)
gc.collect()
a0 = gc.mem_alloc()
t0 = time.ticks_us()
for _ in range(10):
    keys.feed(data)
dt = time.ticks_diff(time.ticks_us(), t0)
a1 = gc.mem_alloc()
print('BENCH decode_us_per_byte %.2f bytes %d heap_delta %d' % (dt / (10 * len(data)), 10 * len(data), a1 - a0))
micropython.heap_lock()
try:
    keys.feed(data)
    locked = 'ok'
except MemoryError:
    locked = 'allocates'
micropython.heap_unlock()
print('BENCH heap_locked_feed', locked)
src = StdinSource()
t0 = time.ticks_us()
for _ in range(1000):
    src.pump(keys)
print('BENCH idle_pump_us %.1f' % (time.ticks_diff(time.ticks_us(), t0) / 1000))
src.close()
for n in (1, 1024, 4096, 8192, 16384):
    b = bytearray(n + 1)
    mv = memoryview(b)
    gc.collect()
    t0 = time.ticks_us()
    for _ in range(100):
        b[1:n + 1] = mv[0:n]
    print('BENCH memmove %d us %.1f' % (n, time.ticks_diff(time.ticks_us(), t0) / 100))
    del b, mv
gc.collect()
print('BENCH free', gc.mem_free())
'''

CTRLC = '''
import time
class Rec:
    def key(self, k, ch=0, mods=0):
        print('K', k, ch, mods)
    def text(self, b):
        pass
keys = TerminalKeys(Rec())
src = StdinSource()
print('READY')
try:
    while True:
        if not src.pump(keys):
            time.sleep_ms(1)
finally:
    src.close()
    print('LOOP_ENDED')
'''

# What each send is expected to produce (the decode phase).
SENDS = [
    (b'Hi', [('K', KEY_CHAR, 72, 0), ('K', KEY_CHAR, 105, 0)]),
    ('神楽'.encode()[:4], []),                      # split inside 楽
    ('神楽'.encode()[4:], [('T', 'e7a59e'), ('T', 'e6a5bd')]),
    (b'\x1b[1', []),                                # split inside a CSI sequence
    (b';2D', [('K', KEY_LEFT, 0, SHIFT)]),
    (b'\x1b[2;5~\x1b[2;2~\x1b[3;2~', [('K', KEY_INSERT, 0, CTRL), ('K', KEY_INSERT, 0, SHIFT),
                                       ('K', KEY_DELETE, 0, SHIFT)]),
    (b'\x1b[17~\x1b[21~\x1b[Z\t', [('K', KEY_F6, 0, 0), ('K', KEY_F10, 0, 0), ('K', KEY_TAB, 0, SHIFT),
                                   ('K', KEY_TAB, 0, 0)]),
    (b'\r\n\x7f\x01\x17', [('K', KEY_ENTER, 0, 0), ('K', KEY_BACKSPACE, 0, 0), ('K', KEY_CHAR, 97, CTRL),
                           ('K', KEY_CHAR, 119, CTRL)]),
    (b'\x1b', [('K', KEY_ESCAPE, 0, 0)]),           # lone: after 50 ms
    (b'\x1bq', [('K', KEY_CHAR, 113, ALT)]),        # ends the phase
]


class Board:
    def __init__(self, port, log):
        from mpremote.transport_serial import SerialTransport
        self.t = SerialTransport(port, timeout=0.2)
        self.log = log
        self.t.enter_raw_repl(soft_reset=False)

    def start(self, source):
        # finish() reads past the end of a program, prompt included, so the
        # handshake is done here: drain, then raw-paste the code.
        time.sleep(0.05)
        self.t.serial.read(self.t.serial.in_waiting)
        self.t.serial.write(b'\x05A\x01')
        if self.t.serial.read(2) != b'R\x01':
            raise SystemExit('raw-paste not accepted; stopping (no further device actions)')
        self.t.raw_paste_write(source.encode('utf8'))
        self.buf = b''

    def lines(self, until, timeout=10.0):
        """Device output lines until one starts with `until` (or the program ends)."""
        out, end = [], time.monotonic() + timeout
        while time.monotonic() < end:
            part = self.t.serial.read(max(self.t.serial.in_waiting, 1))
            self.buf += part
            while b'\n' in self.buf:
                line, self.buf = self.buf.split(b'\n', 1)
                text = line.decode('utf8', 'replace').strip().lstrip('\x04')
                if text:
                    self.log(text)
                    out.append(text)
                    if text.startswith(until):
                        return out
            if b'\x04' in self.buf and until == '\x04':
                return out
        raise SystemExit('timeout waiting for %r; stopping (no further device actions)' % until)

    def finish(self, timeout=10.0):
        """Reads to the end of a raw-REPL exec: returns (stdout tail, error text)."""
        end = time.monotonic() + timeout
        while self.buf.count(b'\x04') < 2 and time.monotonic() < end:
            self.buf += self.t.serial.read(max(self.t.serial.in_waiting, 1))
        if self.buf.count(b'\x04') < 2:
            raise SystemExit('program did not end; stopping (no further device actions)')
        out, err = self.buf.split(b'\x04')[:2]
        self.buf = b''
        for line in out.decode('utf8', 'replace').splitlines():
            if line.strip():
                self.log(line.strip())
        return out.decode('utf8', 'replace'), err.decode('utf8', 'replace')

    def run(self, source, timeout=60.0):
        self.start(source)
        out, err = self.finish(timeout)
        if err.strip():
            raise SystemExit('device error: ' + err.strip().splitlines()[-1])
        return out

    def close(self):
        try:
            self.t.exit_raw_repl()
        finally:
            self.t.close()


def parse(line):
    p = line.split()
    return (p[0], int(p[1]), int(p[2]), int(p[3])) if p[0] == 'K' else (p[0], p[1])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path)
    p.add_argument('--port')
    p.add_argument('--expected-serial')
    args = p.parse_args()
    dev.resolve_device(args)
    logf = args.out.open('w', encoding='utf8', newline='\n') if args.out else None

    def log(line):
        print(line, flush=True)
        if logf:
            logf.write(line + '\n')

    lib = keyinput_source()
    b = Board(args.port, log)
    try:
        log('== probe')
        b.run(PROBE)

        log('== decode')
        b.start(lib + DECODE)
        b.lines('READY')
        got = []
        for data, expect in SENDS:
            b.t.serial.write(data)
            b.t.serial.flush()
            time.sleep(0.2 if data == b'\x1b' else 0.03)
            if expect:
                for _ in expect:
                    got.append(parse(b.lines(('K', 'T'))[-1]))
        want = [e for _, exp in SENDS for e in exp]
        b.lines('DECODED')
        _, err = b.finish()
        if err.strip() or got != want:
            log('DECODE MISMATCH got %r' % got)
            raise SystemExit('decode phase failed; stopping')
        log('DECODE ok %d events' % len(got))

        log('== burst')
        b.start(lib + BURST)
        b.lines('READY')
        payload = bytes(97 + i % 26 for i in range(2000))
        t0 = time.monotonic()
        b.t.serial.write(payload + b'\x1bq')
        b.t.serial.flush()
        line = b.lines('BURST', timeout=30)[-1]
        host_s = time.monotonic() - t0
        b.finish()
        n = int(line.split()[1])
        log('BURST received %d of %d, host %.0f ms' % (n, len(payload), host_s * 1000))
        if n != len(payload):
            raise SystemExit('bytes lost; stopping')

        log('== bench')
        b.run(lib + BENCH, timeout=120)

        log('== ctrl-c')
        b.start(lib + CTRLC)
        b.lines('READY')
        b.t.serial.write(b'ab')
        b.lines('K 1 98')
        b.t.serial.write(b'\x03')
        _, err = b.finish()
        interrupted = 'KeyboardInterrupt' in err
        log('CTRLC interrupted %s' % interrupted)
        if not interrupted:
            raise SystemExit('Ctrl+C did not interrupt the input loop; stopping')
        out = b.run("print('ALIVE', 6 * 7)")
        if 'ALIVE 42' not in out:
            raise SystemExit('REPL did not answer after Ctrl+C')
        b.run(PROBE)
        log('ALL OK')
    finally:
        b.close()
        if logf:
            logf.close()


if __name__ == '__main__':
    main()
