# SPDX-License-Identifier: Apache-2.0
"""Stage 2 HDMI acceptance run of the C desktop (pico/README.md, stage 2).

  run --approved --expected-flash SHA --uf2 F --elf F --out DIR

Same safety sequence as stage 1 (rp2040_sram_bench.py): UF2 verified against
the RAM-only rules and the ELF, flash hash equal to the verified backup, a
control reboot that must keep the hash and bring the console back, BOOTSEL,
copy of the verified RAM-only UF2. Then:

  * the program's preflight (register reads only) is checked here as well
    before 'w' allows any FPGA write;
  * for every scene a settled full-resolution HDMI still is captured
    (1280x960 YUYV, the 640x480p60 output scaled 2x, 4x4 per logical pixel);
    scenes marked for recording also get a 320x240 point-sampled video
    taken while the scene is applied, for intermediate-frame analysis;
  * timing lines are logged;
  * with --video FILE, the stills and per-scene recordings are replaced by one
    continuous 640x480 H.264 recording from the first FPGA write to KDHD_DONE,
    with a pause before each scene so every state stays on screen;
  * after the program reboots into flash, the MicroPython console is
    captured, the flash hash and console state are checked, and a final
    normal reboot leaves the device as found.

Never prints the USB serial. Uses ffmpeg (FFMPEG env var or PATH).
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rp2040_sram_bench as stage1  # noqa: E402

FFMPEG = os.environ.get('FFMPEG', 'ffmpeg')
DEVICE = 'video=UGREEN 15390'
INPUT = ['-hide_banner', '-loglevel', 'error', '-rtbufsize', '512M', '-f', 'dshow',
         '-video_size', '1280x960', '-pixel_format', 'yuyv422', '-framerate', '60', '-i', DEVICE]


def capture_still(path):
    """The last of 20 frames (about 0.3 s): a settled frame."""
    subprocess.run([FFMPEG, '-y'] + INPUT + ['-frames:v', '20', '-update', '1', str(path)],
                   check=True, timeout=60)


def start_recording(folder, seconds=4):
    """320x240 point samples (block interiors) of every frame, as PNGs."""
    folder.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([FFMPEG, '-y'] + INPUT + ['-t', str(seconds), '-vf', 'scale=320:240:flags=neighbor',
                            str(folder / '%04d.png')], stdin=subprocess.DEVNULL)


def start_video(path):
    """The whole run as one viewable 640x480 H.264 file (2x2 blocks per logical pixel)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([FFMPEG, '-y'] + INPUT + ['-vf', 'scale=640:480:flags=neighbor', '-c:v', 'libx264',
                            '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p', str(path)],
                            stdin=subprocess.PIPE)


def stop_video(proc):
    if proc and proc.poll() is None:
        proc.stdin.write(b'q')
        proc.stdin.flush()
        proc.wait(timeout=30)


def preflight_ok(line):
    f = line.split()
    v = {f[i]: f[i + 1] for i in range(1, len(f) - 1, 2)}
    return (v.get('status_call') == '0' and v.get('id') == '4b39' and v.get('abi') == '0.6' and
            v.get('height') == '240' and v.get('patterns') == '1200' and v.get('error_code') == '0x00')


def run(args):
    import serial
    if not args.approved:
        raise SystemExit('refusing to touch the device without --approved')
    out = args.out
    stills, videos = out / 'stills', out / 'video'
    stills.mkdir(parents=True, exist_ok=True)
    stage1.resolve_device(args)
    checks = stage1.verify_uf2(args.uf2, args.elf)
    with (out / 'device.txt').open('w', encoding='utf8', newline='\n') as log:
        def emit(line):
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()

        emit('HOST_START %s' % datetime.now(timezone.utc).isoformat())
        for c in checks:
            emit('HOST_UF2 ' + c)
        h0, c0 = stage1.flash_hash(args.port, True)
        emit('HOST_FLASH_BEFORE %s console %s' % (h0, c0))
        if h0 != args.expected_flash:
            raise SystemExit('flash does not match the verified backup; no BOOTSEL entry')
        try:
            stage1.micropython_exec(args.port, "import machine\nmachine.reset()\n", timeout=5)
        except Exception:
            pass
        if not stage1.wait_gone(args.expected_serial):
            raise SystemExit('the control reset did not take place')
        port = stage1.wait_port(args.expected_serial)
        if not port:
            raise SystemExit('MicroPython did not come back after the control reset')
        time.sleep(4)
        capture_still(stills / '00-console-before.png')
        h1, c1 = stage1.flash_hash(port, True)
        emit('HOST_FLASH_CONTROL %s console %s' % (h1, c1))
        if h1 != h0 or c1 != stage1.CONSOLE_OK:
            raise SystemExit('control reboot check failed; stopping before BOOTSEL')
        try:
            stage1.micropython_exec(port, "import machine\nmachine.bootloader()\n", timeout=5)
        except Exception:
            pass
        drive, info = stage1.find_bootsel_drive()
        emit('HOST_BOOTSEL %s' % ' | '.join(l.strip() for l in info.splitlines() if l.strip()))
        stage1.verify_uf2(args.uf2, args.elf)
        with open(args.uf2, 'rb') as src, open(drive / Path(args.uf2).name, 'wb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
        emit('HOST_COPIED %s' % Path(args.uf2).name)
        bench = stage1.wait_port(args.expected_serial, stage1.NO_FLASH_SERIAL, seconds=30)
        if not bench:
            raise SystemExit('the RAM program did not enumerate (watchdog returns the Pico to MicroPython)')
        done = failed = False
        with serial.Serial(bench, 115200, timeout=0.5) as s:
            time.sleep(0.5)
            s.write(b'g')
            deadline = time.time() + args.timeout
            recorder = video = None
            while time.time() < deadline and not done and not failed:
                line = s.readline().decode('utf8', 'replace').rstrip()
                if not line:
                    continue
                emit(line)
                if line.startswith('KDHD_PREFLIGHT'):
                    good = preflight_ok(line)
                    emit('HOST_PREFLIGHT %s' % ('accepted' if good else 'REJECTED'))
                    if good and args.video:
                        video = start_video(args.video)
                        time.sleep(2)   # recording running before the first write
                        emit('HOST_VIDEO started %s' % args.video.name)
                    s.write(b'w' if good else b'x')
                    failed = not good
                elif line.startswith('KDHD_READY'):
                    _, index, name, record = line.split()
                    if video:
                        time.sleep(args.scene_pause)
                    elif record == '1':
                        recorder = start_recording(videos / name)
                        for _ in range(40):   # wait for the first recorded frame
                            if any((videos / name).glob('*.png')):
                                break
                            time.sleep(0.1)
                        time.sleep(0.5)
                    s.write(b'g')
                elif line.startswith('KDHD_SCENE'):
                    name = line.split()[1]
                    failed = not line.endswith(' OK')
                    time.sleep(1.0)   # settle: several frames after the last transfer
                    if recorder:
                        recorder.wait(timeout=30)
                        recorder = None
                    if not video:
                        capture_still(stills / ('%s.png' % name))
                        emit('HOST_CAPTURED %s' % name)
                    if not failed:
                        s.write(b'n')
                elif line.startswith(('KDHD_ERROR', 'KDHD_VERIFY')) and not line.endswith(' OK'):
                    failed = True
                elif line == 'KDHD_DONE':
                    done = True
                    if video:
                        time.sleep(2)
                        stop_video(video)
                        video = None
                        emit('HOST_VIDEO stopped')
                    s.write(b'r')
            if recorder:
                recorder.wait(timeout=30)
            stop_video(video)
            if failed:
                emit('HOST_STOP device reported an error or mismatch')
                s.write(b'x')
        stage1.wait_gone(args.expected_serial, stage1.NO_FLASH_SERIAL, seconds=20)
        port = stage1.wait_port(args.expected_serial, seconds=60)
        if not port:
            raise SystemExit('MicroPython did not come back; unplug/replug USB (RAM image is lost on power-off)')
        time.sleep(4)
        capture_still(stills / '14-console-after.png')
        emit('HOST_CAPTURED 14-console-after')
        h2, c2 = stage1.flash_hash(port, True)
        emit('HOST_FLASH_AFTER %s console %s' % (h2, c2))
        emit('HOST_FLASH_UNCHANGED %s' % ('yes' if h2 == h0 else 'NO'))
        emit('HOST_CONSOLE_RESTORED %s' % ('yes' if c2 == stage1.CONSOLE_OK else 'NO'))
        try:
            stage1.micropython_exec(port, "import machine\nmachine.reset()\n", timeout=5)
        except Exception:
            pass
        back = stage1.wait_gone(args.expected_serial) and stage1.wait_port(args.expected_serial)
        time.sleep(4)
        capture_still(stills / '15-console-final.png')
        emit('HOST_FINAL_REBOOT %s' % ('ok' if back else 'MicroPython did not re-enumerate'))
        ok = done and not failed and h2 == h0 and c2 == stage1.CONSOLE_OK and bool(back)
        emit('HOST_END %s %s' % (datetime.now(timezone.utc).isoformat(), 'OK' if ok else 'FAILED'))
        if not ok:
            sys.exit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--port')
    r.add_argument('--expected-serial')
    r.add_argument('--expected-flash', required=True)
    r.add_argument('--uf2', required=True)
    r.add_argument('--elf', required=True)
    r.add_argument('--approved', action='store_true')
    r.add_argument('--timeout', type=int, default=1200)
    r.add_argument('--out', type=Path, default=Path('build/c-gem-hdmi/run'))
    r.add_argument('--video', type=Path, help='record the whole run as one MP4 instead of stills')
    r.add_argument('--scene-pause', type=float, default=2.0, help='seconds before each scene (--video)')
    args = p.parse_args()
    run(args)


if __name__ == '__main__':
    main()
