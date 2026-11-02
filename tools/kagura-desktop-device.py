# SPDX-License-Identifier: Apache-2.0
"""Hardware acceptance of the native desktop firmware on KAGURA-9.

Runs software/micropython/examples/desktop_ja.py on the board from the raw
REPL (code in RAM, no filesystem writes) through kagura.desktop, the
firmware's frozen hardware session, and checks every scene three ways:
  * framebuffer CRC32 equal to the host run (unix port, same native code);
  * the patterns read back from the FPGA have the CRC32 of the host run's
    TILE4 image (the transport delivered every byte);
  * an HDMI still (UGREEN 15390, 1280x960) for tools' hdmi_compare.py.
Then it measures the binding on the RP2040 (heap, call cost, update latency,
GC, a long update loop), closes the desktop, checks that the console came
back, and does a soft reset and a hard reset (machine.reset).

  python tools/kagura-desktop-device.py --out DIR [--ffmpeg PATH] [--loops 2000] [--soak 600]

Uses mpremote/pyserial (Windows: uv CPython with
build/transport-analysis/python-deps). Never prints the USB serial.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/c-gem-desktop/tools'))
import rp2040_sram_bench as dev  # noqa: E402

DEVICE = 'video=UGREEN 15390'
INPUT = ['-hide_banner', '-loglevel', 'error', '-rtbufsize', '512M', '-f', 'dshow',
         '-video_size', '1280x960', '-pixel_format', 'yuyv422', '-framerate', '60', '-i', DEVICE]

DRIVER = r'''
import time, gc, binascii
from kagura.desktop import Desktop
from kagura import regs as _R
gc.collect()
_h0 = gc.mem_free()
desk = Desktop(menus=MENUS)
gc.collect()
print('HEAP before', _h0, 'after_desktop', gc.mem_free(), 'alloc', gc.mem_alloc())
app = App(desk)
gc.collect()
print('HEAP after_app', gc.mem_free())
_c = bytearray(1000)   # VRAM readback in chunks: no 32 KB heap block needed
_n = [0]
def step(name):
    _n[0] += 1
    t0 = time.ticks_us()
    tiles = desk.present()
    dt = time.ticks_diff(time.ticks_us(), t0)
    vcrc = 0
    for off in range(0, 32000, 1000):
        desk.device.read_memory_into(off, _c)
        vcrc = binascii.crc32(_c, vcrc)
    print('SCENE %d %s %08x %d %d %08x %d %d' % (_n[0], name, desk.crc(), tiles, dt, vcrc,
          desk.device.read_reg(_R.REG_ERROR_CODE), gc.mem_free()))
    time.sleep_ms(%(hold)d)
tour(app, step)

# ---- measurements on the RP2040 ----
def us(f, n):
    t0 = time.ticks_us()
    for i in range(n):
        f(i)
    return time.ticks_diff(time.ticks_us(), t0) / n
w = app.welcome
st = app.status
nop = us(lambda i: None, 200)
print('CALL lambda %.1f us' % nop)
print('CALL is_open %.1f us' % (us(lambda i: w.is_open(), 500) - nop))
print('CALL set_text_same %.1f us' % (us(lambda i: w.set_text(st, '状態: 窓を閉じた'), 500) - nop))
fr = w.fill_rect(150, 4, 4, 4, 12)
print('CALL set_color_same %.1f us' % (us(lambda i: w.set_color(fr, 12), 500) - nop))
labels = ['状態: %d回目' % k for k in range(10)]
print('FRAME label %.0f us' % us(lambda i: (w.set_text(st, labels[i % 10]), desk.present()), 50))
print('FRAME sprite_pixel %.0f us' % us(lambda i: (app.sprite.set(1, 1, i & 15), desk.present()), 50))
print('FRAME window_activate %.0f us' % us(lambda i: ((app.files if i & 1 else app.welcome).activate(), desk.present()), 20))
print('FRAME window_move %.0f us' % us(lambda i: (app.files.move(10 + (i & 1) * 8, 110), desk.present()), 20))
print('FRAME full_redraw %.0f us' % us(lambda i: (desk.invalidate(0, 0, 320, 200), desk.present()), 5))
# GC and allocation in a steady update loop
gc.collect()
a0 = gc.mem_alloc()
t0 = time.ticks_ms()
lst = [None] * 8
for i in range(%(loops)d):
    w.set_text(st, labels[i % 10])
    app.sprite.set(i & 15, (i >> 4) & 15, i & 15)
    if i %% 50 == 0:
        app.files.move(10 + (i & 8), 110 - (i & 16))
    while desk.poll_into(lst):
        pass
    desk.present()
t1 = time.ticks_ms()
print('LOOP %d updates in %d ms, heap growth %d B, free %d' % (%(loops)d, time.ticks_diff(t1, t0),
      gc.mem_alloc() - a0, gc.mem_free()))
t0 = time.ticks_us(); gc.collect(); print('GC collect %d us' % time.ticks_diff(time.ticks_us(), t0))
# Soak: mixed updates for %(soak)d s; every 200 updates a full recomposition must
# change nothing and ERROR_CODE must be 0.
end = time.ticks_add(time.ticks_ms(), %(soak)d * 1000)
n = checks = bad = 0
lo = gc.mem_free()
while time.ticks_diff(end, time.ticks_ms()) > 0:
    k = n %% 7
    if k == 0:
        w.set_text(st, labels[n %% 10])
    elif k == 1:
        app.sprite.set(n & 15, (n >> 4) & 15, (n >> 8) & 15)
    elif k == 2:
        (app.files if n & 8 else app.welcome).activate()
    elif k == 3:
        app.files.move(10 + (n & 24), 100 + (n & 16))
    elif k == 4:
        app.ev(2, 12, 4); app.ev(3, 12, 4)          # open and close ファイル by a click
    elif k == 5:
        app.ev(1, 40 + (n & 127), 30 + (n & 63))    # pointer move: the cursor
    else:
        app.handle()
    while desk.poll_into(lst):
        pass
    desk.present()
    n += 1
    if n %% 200 == 0:
        desk.invalidate(0, 0, 320, 200)
        ok = desk.present() == 0 and desk.device.read_reg(_R.REG_ERROR_CODE) == 0
        checks += 1
        bad += not ok
        gc.collect()
        lo = min(lo, gc.mem_free())
        if checks %% 10 == 0:
            print('SOAK progress %d updates, %d failed, free %d' % (n, bad, gc.mem_free()))
print('SOAK %d updates, %d checks, %d failed, lowest free heap %d B' % (n, checks, bad, lo))
desk.invalidate(0, 0, 320, 200)
print('CONSISTENT', desk.present() == 0, 'error_code', desk.device.read_reg(_R.REG_ERROR_CODE))
print('STATS', desk.stats())
desk.close()
print('CLOSED console paused', kagura_console.paused, 'last_error', kagura_console.last_error)
print('DONE')
'''


def capture(ffmpeg, path):
    subprocess.run([ffmpeg, '-y'] + INPUT + ['-frames:v', '20', '-update', '1', str(path)], check=True, timeout=60)


def stream(port, source, on_line, timeout=3600):
    from mpremote.transport_serial import SerialTransport
    t = SerialTransport(port, timeout=0.2)
    try:
        t.enter_raw_repl(soft_reset=False)
        t.exec_raw_no_follow(source)
        buf, out, err = b'', [], b''
        start = last = time.monotonic()
        while True:
            part = t.serial.read(max(t.serial.in_waiting, 1))
            if part:
                last = time.monotonic()
                buf += part
                if b'\x04' in buf:
                    head, rest = buf.split(b'\x04', 1)
                    for line in head.split(b'\n'):
                        if line.strip():
                            out.append(line.decode('utf8', 'replace').rstrip())
                            on_line(out[-1])
                    while rest.count(b'\x04') < 1:
                        rest += t.serial.read(max(t.serial.in_waiting, 1))
                    err = rest.split(b'\x04', 1)[0]
                    break
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    out.append(line.decode('utf8', 'replace').rstrip())
                    on_line(out[-1])
            if time.monotonic() - start > timeout or time.monotonic() - last > 60:
                raise SystemExit('device output stalled')
        t.serial.read(max(t.serial.in_waiting, 1))
        t.exit_raw_repl()
        return out, err.decode('utf8', 'replace')
    finally:
        t.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ffmpeg', default='ffmpeg')
    p.add_argument('--no-capture', action='store_true')
    p.add_argument('--hold', type=int, default=2500, help='ms each scene stays on screen')
    p.add_argument('--loops', type=int, default=2000)
    p.add_argument('--soak', type=int, default=600, help='seconds of mixed updates')
    p.add_argument('--port')
    p.add_argument('--expected-serial')
    args = p.parse_args()
    stills = args.out / 'stills'
    stills.mkdir(parents=True, exist_ok=True)
    dev.resolve_device(args)
    log = (args.out / 'device.txt').open('w', encoding='utf8', newline='\n')

    def emit(line):
        print(line, flush=True)
        log.write(line + '\n')
        log.flush()

    emit('HOST_START %s' % time.strftime('%Y-%m-%dT%H:%M:%S'))
    info = dev.micropython_exec(args.port, "import os\nprint('BUILD', os.uname().version)\n"
                                "import kagura_desktop\nprint('SIZES', sorted(kagura_desktop.sizes().items()))\n")
    for line in info.splitlines():
        emit(line)
    if not args.no_capture:
        capture(args.ffmpeg, stills / '00-console-before.png')

    def on_line(line):
        emit(line)
        if line.startswith('SCENE') and not args.no_capture:
            time.sleep(0.3)   # the scene was presented before it was printed
            f = line.split()
            capture(args.ffmpeg, stills / ('%02d-%s.png' % (int(f[1]), f[2])))

    demo = (ROOT / 'software/micropython/examples/desktop_ja.py').read_text(encoding='utf8')
    demo = demo.split("\nif __name__ == '__main__':")[0]
    source = demo + (DRIVER.replace('%(hold)d', str(args.hold)).replace('%(loops)d', str(args.loops))
                     .replace('%(soak)d', str(args.soak)).replace('%%', '%'))
    out, err = stream(args.port, source.encode('utf8'), on_line)
    if err:
        emit('DEVICE_EXCEPTION ' + err.replace('\n', ' | '))
    time.sleep(1)
    if not args.no_capture:
        capture(args.ffmpeg, stills / '15-console-final.png')
    # Soft reset (Ctrl-D) and hard reset: the REPL, the console and the module must come back.
    for kind, code in (('soft', 'import machine\nmachine.soft_reset()\n'), ('hard', 'import machine\nmachine.reset()\n')):
        try:
            dev.micropython_exec(args.port, code, timeout=5)
        except BaseException:
            pass
        if kind == 'hard':
            dev.wait_gone(args.expected_serial, seconds=15)
        port = dev.wait_port(args.expected_serial, seconds=60)
        time.sleep(4)
        try:
            r = dev.micropython_exec(port, "import kagura_desktop, gc\nprint('ALIVE', kagura_console.screen is not None, "
                                     "kagura_console.last_error, gc.mem_free())\n", timeout=30)
            emit('%s_RESET %s' % (kind.upper(), r.strip()))
        except BaseException as e:
            emit('%s_RESET FAILED %r' % (kind.upper(), e))
        args.port = port
    if not args.no_capture:
        capture(args.ffmpeg, stills / '16-console-after-reset.png')
    emit('HOST_END %s' % time.strftime('%Y-%m-%dT%H:%M:%S'))


if __name__ == '__main__':
    main()
