# SPDX-License-Identifier: Apache-2.0
"""神楽メモ帳 on KAGURA-9: per-keystroke timing and a live typing session.

Needs firmware with the editor (Phase 4). Runs from the raw REPL: the
example sources are sent as code, documents go to ram_docs() (a littlefs in
RAM), so nothing is written to flash.

  bench   latency of one key, end to end on the RP2040 (desk.key/text ->
          app.handle -> desk.present over the link): p50 / p95 / max, tiles
          per key, heap per key, for typing, Japanese, motions, Enter in a
          long document, Backspace joining lines, PgDn, and the flat
          buffer's worst case (inserting at the start of an 8 KB document).
  live    desktop_editor.main loop with StdinSource: the host types a text
          over USB CDC (the same stdin a terminal uses), at --cps characters
          per second, saves with Ctrl+S, reopens it, and quits by F10. With
          --video it records the HDMI capture (UGREEN 15390) meanwhile.
          This is real input through the board's stdin, but sent by a script,
          not a physical keyboard.

  python tools/kagura-editor-board.py bench|live [--out FILE] [--video F --ffmpeg PATH]

Never prints the USB serial.
"""
import argparse
import importlib.util
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kbd', ROOT / 'tools/kagura-keyboard-device.py')
kbd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kbd)


def example(name):
    src = (ROOT / 'software/micropython/examples' / name).read_text(encoding='utf8')
    return src.split("\nif __name__ == '__main__':")[0] + '\n'


BENCH = r'''
import gc, time
from kagura.desktop import Desktop
desk = Desktop(menus=MENUS, cursor=False)
try:
    app = Editor(desk, ram_docs(blocks=40), 'ベンチ')
    w, ed = app.win, app.ed
    desk.present()
    def run(name, fn, n):
        times, parts, tiles = [], [[], [], [], []], 0
        gc.collect()
        a0 = gc.mem_alloc()
        for i in range(n):
            t0 = time.ticks_us()
            fn(i)
            t1 = time.ticks_us()
            app.handle()
            t2 = time.ticks_us()
            desk.render()
            t3 = time.ticks_us()
            tiles += desk.present()
            t4 = time.ticks_us()
            times.append(time.ticks_diff(t4, t0))
            for k, (a, b) in enumerate(((t0, t1), (t1, t2), (t2, t3), (t3, t4))):
                parts[k].append(time.ticks_diff(b, a))
        a1 = gc.mem_alloc()
        times.sort()
        for p in parts:
            p.sort()
        print('KEY %-26s n %3d p50 %6d p95 %6d max %6d us  tiles/key %5.1f  heap/key %6.1f' % (
            name, n, times[n // 2], times[n * 95 // 100], times[-1], tiles / n, (a1 - a0) / n))
        print('    p50 parts: key %d  app %d  compose %d  send %d us' % tuple(p[n // 2] for p in parts))
    doc = ''.join('%03d 行目 神楽メモ帳のテキスト\n' % i for i in range(100))
    w.set_text(ed, doc)
    for _ in range(40):
        desk.key(kd.KEY_DOWN)
    desk.key(kd.KEY_END)
    app.handle(); desk.present()
    run('type ASCII (line end)', lambda i: desk.key(kd.KEY_CHAR, 97 + i % 26), 60)
    run('type Japanese (text)', lambda i: desk.text('漢'), 40)
    run('caret left', lambda i: desk.key(kd.KEY_LEFT), 40)
    w.select(ed, 41 * 18 + 5)                 # back to a short line, column 5, in view
    app.handle(); desk.present()
    run('caret up/down', lambda i: desk.key(kd.KEY_UP if i % 2 else kd.KEY_DOWN), 40)
    run('Enter (lines below move)', lambda i: desk.key(kd.KEY_ENTER), 20)
    run('Backspace joining lines', lambda i: desk.key(kd.KEY_BACKSPACE), 20)
    run('PgDn / PgUp', lambda i: desk.key(kd.KEY_PGDN if i % 2 == 0 else kd.KEY_PGUP), 20)
    run('idle frame', lambda i: None, 40)
    w.set_text(ed, ('x' * 79 + '\n') * 102)
    desk.key(kd.KEY_HOME, 0, kd.MOD_CTRL)
    app.handle(); desk.present()
    print('DOC bytes', w.length(ed))
    run('8 KB doc: insert at start', lambda i: desk.key(kd.KEY_CHAR, 'y') if i % 2 == 0 else desk.key(kd.KEY_BACKSPACE), 40)
    gc.collect()
    print('HEAP free_with_editor', gc.mem_free())
finally:
    desk.close()
print('CONSOLE paused', kagura_console.paused, 'error', kagura_console.last_error)
'''

LIVE = r'''
import gc
from kagura.desktop import Desktop
desk = Desktop(menus=MENUS, cursor=False)
try:
    app = Editor(desk, ram_docs(blocks=40), 'キーボード')
    desk.present()
    print('READY')
    keyboard(app)
    print('SAVED', app.docs.names(), 'NAME', app.name, 'TEXT_BYTES', app.win.length(app.ed))
finally:
    desk.close()
gc.collect()
print('CLOSED free', gc.mem_free(), 'console_paused', kagura_console.paused)
'''

SHOWCASE_NS = '''
class _NS:
    pass
de = _NS()
for _k, _v in list(globals().items()):
    setattr(de, _k, _v)
'''

SHOWCASE = r'''
print('\n' * 30)                     # a clean console before the desktop opens
main(pace=%r, music=%r)
print('SHOWCASE done; console paused', kagura_console.paused)
'''

TEXT = ('神楽メモ帳でキーボードから入力しています。\n'
        'RP2040とFPGAの小さなコンピュータ、KAGURA-9です。\n'
        'Shift+矢印で選択、Ctrl+Sで保存します。\n')


def send(board, data, cps):
    """Writes a character (or an escape sequence) at a time, like typing."""
    for unit in data:
        board.t.serial.write(unit)
        board.t.serial.flush()
        time.sleep(1.0 / cps)


def units(text):
    out = []
    for c in text:
        out.append(b'\r' if c == '\n' else c.encode())
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('phase', choices=('bench', 'live', 'showcase'))
    p.add_argument('--pace', type=float, default=1.0, help='showcase pacing (1.0: about 2 minutes)')
    p.add_argument('--reset', action='store_true', help='soft reset first: a clean heap and console')
    p.add_argument('--music', action='store_true', help='showcase with PSG background music')
    p.add_argument('--audio', help='dshow audio device to record with --video (HDMI audio of the capture)')
    p.add_argument('--out', type=Path)
    p.add_argument('--cps', type=float, default=8.0, help='characters per second (live)')
    p.add_argument('--video', type=Path)
    p.add_argument('--ffmpeg', default='ffmpeg')
    p.add_argument('--port')
    p.add_argument('--expected-serial')
    args = p.parse_args()
    kbd.dev.resolve_device(args)
    if args.reset:                      # the console starts again after a soft reset
        try:
            kbd.dev.micropython_exec(args.port, 'import machine\nmachine.soft_reset()\n', timeout=5)
        except BaseException:           # the reset ends the session on purpose
            pass
        time.sleep(5)
    logf = args.out.open('w', encoding='utf8', newline='\n') if args.out else None

    def log(line):
        print(line, flush=True)
        if logf:
            logf.write(line + '\n')

    lib = example('desktop_editor.py')
    b = kbd.Board(args.port, log)
    rec = None
    try:
        if args.video and args.phase != 'bench':
            audio = ['-c:a', 'aac', '-b:a', '192k'] if args.audio else []
            rec = subprocess.Popen([args.ffmpeg, '-y'] + kbd_input(args.audio) + ['-c:v', 'libx264', '-preset', 'veryfast',
                                   '-crf', '18', '-pix_fmt', 'yuv420p'] + audio + [str(args.video)],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
        if args.phase == 'bench':
            b.run(lib + BENCH, timeout=300)
        elif args.phase == 'showcase':
            # desktop_showcase imports desktop_editor; from RAM, the editor's
            # globals (sent just before) stand in for that module.
            show = example('desktop_showcase.py').replace('import desktop_editor as de\n', SHOWCASE_NS)
            # One exec per module: compiling everything at once needs the
            # source, parse and code together and fragments the heap.
            free = "import gc\ngc.collect()\nprint('FREE', gc.mem_free())\n"
            b.run(free)
            b.run(lib)
            b.run(free)
            if args.music:              # showcase_music's Music, defined before the show
                show = show.replace('        from showcase_music import Music\n', '')
                b.run(example('showcase_music.py'))
            b.run(show)
            b.run(free)
            b.run(SHOWCASE % (args.pace, args.music), timeout=900)
            time.sleep(4)
        else:
            b.start(lib + LIVE)
            b.lines('READY', timeout=30)
            time.sleep(2)
            send(b, units(TEXT), args.cps)
            time.sleep(1)
            seq = [b'\x1b[A'] * 2 + [b'\x1b[F'] + [b'\x1b[1;2D'] * 3      # select 'です。'
            send(b, seq, 4)
            time.sleep(1)
            send(b, units('でした。'), args.cps)
            time.sleep(1)
            send(b, [b'\x13'], 1)                                            # Ctrl+S: Save As
            time.sleep(1.5)
            send(b, [b'\x7f'] * 6 + units('kagura.txt'), args.cps)
            send(b, [b'\r'], 1)
            time.sleep(2)
            send(b, [b'\x0e'], 1)                                            # Ctrl+N: new
            time.sleep(1.5)
            send(b, [b'\x0f'], 1)                                            # Ctrl+O
            time.sleep(1)
            send(b, units('kagura.txt') + [b'\r'], args.cps)
            time.sleep(3)
            send(b, [b'\x1b[21~'] + [b'\x1b[B'] * 4 + [b'\r'], 3)            # F10 > 終了
            b.lines('CLOSED', timeout=30)
            out, err = b.finish()
            if err.strip():
                raise SystemExit('device error: ' + err.strip().splitlines()[-1])
            time.sleep(4)
    finally:
        if rec is not None:
            rec.communicate(b'q', timeout=30)
        b.close()
        if logf:
            logf.close()


def kbd_input(audio=None):
    # HDMI audio is 48 kHz stereo; the capture's audio device is opened with the video.
    source = 'video=UGREEN 15390' + (':audio=' + audio if audio else '')
    return (['-hide_banner', '-loglevel', 'error', '-rtbufsize', '512M', '-f', 'dshow', '-video_size', '1280x960',
             '-pixel_format', 'yuyv422', '-framerate', '60'] + (['-sample_rate', '48000'] if audio else []) +
            ['-i', source])


if __name__ == '__main__':
    main()
