# SPDX-License-Identifier: Apache-2.0
"""Audio HAL, KSNG player and 神楽トラッカー on KAGURA-9 (firmware with kagura_audio).

Code runs from the raw REPL (RAM). Songs go to a littlefs in RAM; nothing is
written to flash. With --wav, the HDMI audio is recorded (UGREEN 15390, 48 kHz
PCM) and tools/kagura-audio-timing.py measures the note timing on it.

  bench    send cost per frame; then the click song (software/audio/songs,
           150 BPM, a click every 100 ms) under each kind of desktop load:
           pump only, desktop idle, window moves, sprite editing, Japanese
           typing, the SKK candidate popup, RAM filesystem I/O, forced GC.
           Each phase prints the player's lateness, the loop and present()
           times, heap and the FPGA error state; 2.5 s of silence separate
           the phases, so the recording splits into one section per phase.
  tracker  desktop_tracker's scripted session (compose, edit, play two loops
           while the desktop works, save, reopen, export) with SCENE CRCs to
           compare with the host run; --video records it. The tracker is too
           big to compile on the board: --mpy gives it cross-compiled
           (mpy-cross -march=armv6m), installed on a littlefs in RAM,
           imported, and the RAM disk freed again.
  soak     the demo song for --seconds with window moves and typing: ticks
           against the exact tempo, heap low-water mark, FPGA errors.
  reset    soft reset (kagura_audio state dropped, init works again, the
           console returns) and hard reset (machine.reset).

  python tools/kagura-audio-board.py bench|tracker|soak|reset --out LOG [--wav F] [--video F]

Never prints the USB serial.
"""
import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kbd', ROOT / 'tools/kagura-keyboard-device.py')
kbd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kbd)
AUDIO_DEVICE = r'@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}\wave_{50C95F8D-70A1-4A19-A8F2-2D397E31A086}'


def example(name):
    src = (ROOT / 'software/micropython/examples' / name).read_text(encoding='utf8')
    return src.split("\nif __name__ == '__main__':")[0] + '\n'


def song(name):
    return (ROOT / 'software/audio/songs' / name).read_bytes().hex()


COMMON = r'''
import gc, time, os, micropython, machine
import kagura_audio as ka
from kagura.music import AudioSession
d = kagura_console.screen.device
CLICK = bytes.fromhex('%(click)s')
DEMO = bytes.fromhex('%(demo)s')

def pct(v):
    v = sorted(v)
    n = len(v)
    return (v[n // 2], v[n * 95 // 100], v[-1]) if n else (0, 0, 0)

def fpga():
    try:
        d.check_errors()
        e = 0
    except OSError as x:
        e = x.args[0] if x.args else -1
    return e, d.audio_read(0xE1)
'''

BENCH = r'''
print('BUILD', os.uname().version)
print('SIZES', sorted(ka.sizes().items()))
gc.collect()
import vfs
class RAMBlocks:
    def __init__(self, n=64, bs=512):
        self.data, self.n, self.bs = bytearray(n * bs), n, bs
    def readblocks(self, b, buf, off=0):
        a = b * self.bs + off
        buf[:] = self.data[a:a + len(buf)]
    def writeblocks(self, b, buf, off=None):
        a = b * self.bs + (off or 0)
        self.data[a:a + len(buf)] = buf
    def ioctl(self, op, arg):
        return {4: self.n, 5: self.bs, 6: 0}.get(op)
try:
    vfs.umount('/ramtest')
except OSError:
    pass
blk = RAMBlocks()
vfs.VfsLfs2.mkfs(blk)
vfs.mount(vfs.VfsLfs2(blk), '/ramtest')
gc.collect()
h0 = gc.mem_free()
audio = AudioSession(d)
gc.collect()
print('HEAP before_session', h0, 'after_session', gc.mem_free())
# Do send() and pump() allocate? Under heap_lock any allocation raises.
for what in ('send', 'pump'):
    try:
        micropython.heap_lock()
        for i in range(100):
            ka.gain(0, i, i)
            if what == 'send':
                audio.send()
            else:
                audio.pump()
        micropython.heap_unlock()
        print('NO_ALLOC', what, 'yes')
    except MemoryError:
        micropython.heap_unlock()
        print('NO_ALLOC', what, 'NO')
# Send cost: frames with the gains of 1 or 6 voices changing (2, 12 pairs), and
# the pitches of the three pulse voices too (up to 21 pairs).
for voices, pitch in ((1, False), (6, False), (6, True)):
    t = []
    ka.reset_stats()
    for i in range(300):
        for v in range(voices):
            ka.gain(v, (i + v) & 255, (i * 3 + v) & 255)
        if pitch:
            for v in range(3):
                ka.pitch(v, 40 + (i * 7 + v * 13) % 60, i % 64)
        a = time.ticks_us()
        audio.send()
        t.append(time.ticks_diff(time.ticks_us(), a))
    s = ka.stats()
    print('SEND voices %d pitch %s pairs_per_frame %d p50 %d p95 %d max %d' % (
        (voices, pitch, s['pairs'] // max(1, s['frames'])) + pct(t)))
ka.silence()
audio.send()
from kagura.desktop import Desktop
import kagura_desktop as kd
desk = Desktop(menus=(('ファイル', ('終了',)),), cursor=False)
desk.audio = audio
audio.load(CLICK)
win = desk.create_window('負荷', 40, 40, 200, 110)
for i in range(6):
    win.text(4, 4 + 12 * i, 'テキスト %d 日本語の表示' % i, 1)
spr = desk.sprite()
sw = desk.create_window('スプライト', 230, 30, 80, 80)
sw.sprite(4, 4, spr, 4)
ew = desk.create_window('日本語', 20, 120, 280, 70)
ed = ew.editor(2, 2, 270, 50, '')
desk.present()
payload = bytes(range(256)) * 16
CHUNK = bytearray(512)
for _i in range(4):                 # the files phase reads what it wrote
    with open('/ramtest/f%d.bin' % _i, 'wb') as _f:
        _f.write(payload)
cands = ('音楽', '温楽', '恩学', '御楽', '音学')

def load(kind, i):
    if kind == 'move':
        x = 20 + (i * 3) % 100
        win.move(x, 30 + (i * 2) % 60)
    elif kind == 'sprite':
        buf = bytearray(3 * 16)
        for k in range(16):
            buf[3 * k], buf[3 * k + 1], buf[3 * k + 2] = (i + k) & 15, (i * 7 + k * 3) & 15, (i + k) & 15
        spr.set_pixels(buf)
    elif kind == 'typing':
        if i % 40 == 39:
            ew.set_text(ed, '')
        desk.text('音')
    elif kind == 'popup':
        ew.focus(ed)
        if i % 2 == 0:
            ew.set_candidates(ed, cands, i % 5, '%d/5' % (i % 5 + 1))
        else:
            ew.set_candidates(ed, ())              # hidden
    elif kind == 'files':
        with open('/ramtest/f%d.bin' % (i % 4), 'wb') as f:
            f.write(payload)
        with open('/ramtest/f%d.bin' % ((i + 1) % 4), 'rb') as f:
            f.read()
    elif kind == 'files-chunked':
        # As 神楽トラッカー saves and loads: 512-byte pieces, the audio pumped between.
        view = memoryview(payload)
        with open('/ramtest/f%d.bin' % (i % 4), 'wb') as f:
            for at in range(0, len(payload), 512):
                f.write(view[at:at + 512])
                audio.pump()
        with open('/ramtest/f%d.bin' % ((i + 1) % 4), 'rb') as f:
            while f.readinto(CHUNK):
                audio.pump()
    elif kind == 'gc':
        gc.collect()

from array import array
HIST = array('I', bytes(4 * 257))   # present() times: 250 us buckets to 64 ms, no allocation in the loop

def hist_pct(n, top):
    out, acc, want = [], 0, [n // 2, n * 95 // 100]
    for b in range(257):
        acc += HIST[b]
        while want and acc > want[0]:
            out.append(b * 250 + 125)
            want.pop(0)
    while len(out) < 2:
        out.append(0)
    return out[0], out[1], top

def phase(name, kind, seconds, desktop=True):
    ka.reset_stats()
    gc.collect()
    low = gc.mem_free()
    audio.send_max_us = 0
    audio.play()
    t0 = time.ticks_ms()
    loops, n_pres, top = 0, 0, 0
    for b in range(257):
        HIST[b] = 0
    while time.ticks_diff(time.ticks_ms(), t0) < seconds * 1000:
        if desktop:
            load(kind, loops)
            a = time.ticks_us()
            desk.present()
            dt = time.ticks_diff(time.ticks_us(), a)
            HIST[min(256, dt // 250)] += 1
            if dt > top:
                top = dt
            n_pres += 1
            while desk.poll() is not None:
                pass
        audio.pump()
        loops += 1
        if loops % 32 == 0:
            low = min(low, gc.mem_free())
        if not desktop:
            time.sleep_us(300)
    elapsed = time.ticks_diff(time.ticks_ms(), t0)
    s = ka.stats()
    audio.stop()
    err, ast = fpga()
    print('PHASE %s ticks %d late_max_us %d late_mean_us %d folded %d resyncs %d loops %d '
          'present_us p50 %d p95 %d max %d send_max_us %d heap_low %d error_code %d audio_status 0x%02x'
          % ((name, s['ticks'], s['late_max_us'], s['late_sum_us'] // max(1, s['calls']), s['folded'],
              s['resyncs'], loops) + hist_pct(n_pres, top) + (audio.send_max_us, low, err, ast)))
    time.sleep_ms(2500)            # silence: the recording splits here

time.sleep_ms(2500)
phase('pump', None, 15, False)
for name, kind in (('desk-idle', None), ('window-move', 'move'), ('sprite-edit', 'sprite'),
                   ('ja-typing', 'typing'), ('skk-popup', 'popup'), ('files-ram', 'files'),
                   ('files-chunked', 'files-chunked'), ('gc', 'gc')):
    phase(name, kind, 15)
desk.audio = None
desk.close()
vfs.umount('/ramtest')
audio.close()
err, ast = fpga()
print('CLOSED error_code', err, 'audio_status 0x%02x' % ast)
# The older API still works on this firmware, after the session.
from kagura.audio import Audio
legacy = Audio(d)
legacy.tone(0, 440, 40, 40)
d.audio_commit()
time.sleep_ms(300)
legacy.stop(0)
d.audio_commit()
err, ast = fpga()
print('LEGACY tone ok error_code', err, 'audio_status 0x%02x' % ast)
gc.collect()
print('HEAP end', gc.mem_free())
'''

SOAK = r'''
from kagura.desktop import Desktop
gc.collect()
audio = AudioSession(d)
desk = Desktop(menus=(('ファイル', ('終了',)),), cursor=False)
desk.audio = audio
win = desk.create_window('ソーク', 40, 40, 200, 80)
win.text(4, 4, '長時間の再生', 1)
ew = desk.create_window('日本語', 20, 120, 280, 70)
ed = ew.editor(2, 2, 270, 50, '')
audio.load(DEMO)
gc.collect()
low = high = gc.mem_free()
start = time.ticks_ms()
audio.play()
t0 = ka.position()
i = 0
last = start
while time.ticks_diff(time.ticks_ms(), start) < %(seconds)d * 1000:
    win.move(20 + (i * 3) %% 100, 30 + (i * 2) %% 60)
    if i %% 50 == 49:
        ew.set_text(ed, '')
    desk.text('楽')
    desk.present()
    while desk.poll() is not None:
        pass
    audio.pump()
    i += 1
    if time.ticks_diff(time.ticks_ms(), last) >= 10000:
        last = time.ticks_ms()
        f = gc.mem_free()
        low, high = min(low, f), max(high, f)
        s = ka.stats()
        print('SOAK t %%d ticks %%d late_max_us %%d resyncs %%d heap %%d' %% (
            time.ticks_diff(last, start) // 1000, s['ticks'], s['late_max_us'], s['resyncs'], f))
s = ka.stats()
elapsed_us = time.ticks_diff(time.ticks_ms(), start) * 1000
expect = elapsed_us * 140 // 2500000
audio.stop()
err, ast = fpga()
print('SOAK_END seconds %%d loops %%d ticks %%d expected_about %%d late_max_us %%d folded %%d resyncs %%d '
      'heap_low %%d heap_high %%d error_code %%d audio_status 0x%%02x' %% (
          %(seconds)d, i, s['ticks'], expect, s['late_max_us'], s['folded'], s['resyncs'], low, high, err, ast))
desk.audio = None
desk.close()
audio.close()
'''

LIBDISK = r'''
import vfs, sys
class LibBlocks:
    def __init__(self, n, bs=512):
        self.data, self.n, self.bs = bytearray(n * bs), n, bs
    def readblocks(self, b, buf, off=0):
        a = b * self.bs + off
        buf[:] = self.data[a:a + len(buf)]
    def writeblocks(self, b, buf, off=None):
        a = b * self.bs + (off or 0)
        self.data[a:a + len(buf)] = buf
    def ioctl(self, op, arg):
        return {4: self.n, 5: self.bs, 6: 0}.get(op)
try:
    vfs.umount('/ramlib')
except OSError:
    pass
_lib = LibBlocks(%(blocks)d)
vfs.VfsLfs2.mkfs(_lib)
vfs.mount(vfs.VfsLfs2(_lib), '/ramlib')
open('/ramlib/desktop_tracker.mpy', 'wb').close()
'''

LIBPART = "with open('/ramlib/desktop_tracker.mpy', 'ab') as _f:\n    _f.write(bytes.fromhex('%s'))\n"

LIBLOAD = r'''
sys.path.insert(0, '/ramlib')
from desktop_tracker import main, ram_songs
sys.path.pop(0)
vfs.umount('/ramlib')
del _lib
gc.collect()
files = ram_songs()          # now, before the heap fragments further
gc.collect()
print('TRACKER_LOADED free', gc.mem_free())
'''

TRACKER = r'''
gc.collect()
print('FREE', gc.mem_free())
lines = []
app = main(script=True, files=files, key_ms=%(key_ms)d, step_ms=%(step_ms)d, loops=2)
s = ka.stats() if False else None
for n in files.names():
    print('FILE', n, len(files.load(n)))
err, ast = fpga()
print('TRACKER_END error_code', err, 'audio_status 0x%%02x' %% ast)
gc.collect()
print('FREE', gc.mem_free())
'''


def run(b, log, source, timeout=60.0):
    """Board.run, but a device error is logged whole (the traceback), then stops."""
    b.start(source)
    out, err = b.finish(timeout)
    if err.strip():
        for line in err.strip().splitlines():
            log('DEVICE_ERROR ' + line)
        raise SystemExit('device error: ' + err.strip().splitlines()[-1])
    return out


def record(args, wav=None, video=None):
    src = 'video=UGREEN 15390:audio=' + AUDIO_DEVICE
    cmd = [args.ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-rtbufsize', '512M', '-f', 'dshow',
           '-video_size', '1280x960', '-pixel_format', 'yuyv422', '-framerate', '60', '-sample_rate', '48000',
           '-i', src]
    if wav:
        cmd += ['-map', '0:a', '-c:a', 'pcm_s16le', str(wav)]
    if video:
        cmd += ['-map', '0:v', '-map', '0:a', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', str(video)]
    else:
        cmd += ['-map', '0:v', '-vf', 'scale=320:240', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '35',
                '-f', 'null', '-']
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    return p


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('phase', choices=('bench', 'tracker', 'soak', 'reset'))
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--wav', type=Path)
    p.add_argument('--video', type=Path)
    p.add_argument('--seconds', type=int, default=600)
    p.add_argument('--mpy', type=Path, default=ROOT / 'build/phase6/desktop_tracker.mpy',
                   help='desktop_tracker cross-compiled for the board (tracker)')
    p.add_argument('--key-ms', type=int, default=40)
    p.add_argument('--step-ms', type=int, default=1200)
    p.add_argument('--reset', action='store_true', help='soft reset first: a clean heap and console')
    p.add_argument('--ffmpeg', default='ffmpeg')
    p.add_argument('--port')
    p.add_argument('--expected-serial')
    args = p.parse_args()
    kbd.dev.resolve_device(args)
    if args.reset:
        try:
            kbd.dev.micropython_exec(args.port, 'import machine\nmachine.soft_reset()\n', timeout=5)
        except BaseException:
            pass
        time.sleep(5)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    logf = args.out.open('w', encoding='utf8', newline='\n')

    def log(line):
        print(line, flush=True)
        logf.write(line + '\n')
        logf.flush()

    log('HOST_START %s %s' % (args.phase, time.strftime('%Y-%m-%dT%H:%M:%S')))
    common = COMMON % {'click': song('click.ksn'), 'demo': song('demo.ksn')}
    if args.phase == 'reset':
        reset(args, log)
        logf.close()
        return
    rec = record(args, args.wav, args.video) if (args.wav or args.video) else None
    b = kbd.Board(args.port, log)
    free = "import gc\ngc.collect()\nprint('FREE', gc.mem_free())\n"
    try:
        run(b, log, free)
        run(b, log, common if args.phase != 'tracker' else COMMON % {'click': '', 'demo': ''})
        if args.phase == 'bench':
            run(b, log, BENCH, timeout=600)
        elif args.phase == 'soak':
            run(b, log, SOAK % {'seconds': args.seconds}, timeout=args.seconds + 300)
        else:
            mpy = args.mpy.read_bytes()
            log('MPY %s %d bytes' % (args.mpy.name, len(mpy)))
            run(b, log, LIBDISK % {'blocks': len(mpy) // 512 + 12})
            for at in range(0, len(mpy), 2048):
                run(b, log, LIBPART % mpy[at:at + 2048].hex())
            run(b, log, LIBLOAD)
            run(b, log, TRACKER % {'key_ms': args.key_ms, 'step_ms': args.step_ms}, timeout=1800)
        time.sleep(3)
    finally:
        if rec is not None:
            rec.communicate(b'q', timeout=60)
        b.close()
    if args.wav:
        bpm = '150' if args.phase == 'bench' else '140'
        r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/kagura-audio-timing.py'), str(args.wav),
                            '--bpm', bpm, '--min-onsets', '50'], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            log(line)
    logf.close()


def reset(args, log):
    # Soft reset while a session is open: the module must drop its state.
    open_session = ("from kagura.music import AudioSession\nimport kagura_audio as ka\n"
                    "a = AudioSession(kagura_console.screen.device)\na.load(DEMO)\na.play()\n"
                    "for i in range(50):\n    a.pump()\n    time.sleep_ms(10)\nprint('PLAYING', ka.position() >> 24)\n")
    common = COMMON % {'click': song('click.ksn'), 'demo': song('demo.ksn')}
    log(kbd.dev.micropython_exec(args.port, common + open_session, timeout=60).strip())
    try:
        kbd.dev.micropython_exec(args.port, 'import machine\nmachine.soft_reset()\n', timeout=5)
    except BaseException:
        pass
    time.sleep(5)
    after = ("import kagura_audio as ka\ntry:\n    ka.advance()\n    print('SOFT_RESET state kept (WRONG)')\n"
             "except RuntimeError:\n    print('SOFT_RESET state dropped')\n"
             "d = kagura_console.screen.device\nka.init(d.caps)\nprint('SOFT_RESET init ok', d.caps)\n"
             "from kagura.music import AudioSession\na = AudioSession(d)\na.close()\n"
             "print('SOFT_RESET silenced, console', kagura_console.screen is not None)\n")
    log(kbd.dev.micropython_exec(args.port, after, timeout=60).strip())
    try:
        kbd.dev.micropython_exec(args.port, 'import machine\nmachine.reset()\n', timeout=5)
    except BaseException:
        pass
    kbd.dev.wait_gone(args.expected_serial, seconds=15)
    port = kbd.dev.wait_port(args.expected_serial, seconds=60)
    time.sleep(4)
    log(kbd.dev.micropython_exec(port, "import kagura_audio, os\nprint('HARD_RESET alive', os.uname().version, "
                                       "kagura_console.screen is not None)\n", timeout=60).strip())


if __name__ == '__main__':
    main()
