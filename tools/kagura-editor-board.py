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
import gc, time, micropython, machine
from kagura.desktop import Desktop
# Stack high-water: paint the unused part of core 0's C stack (8 KB below
# 0x20042000; core 1 is idle) and find the deepest overwritten word afterwards.
STACK_BOTTOM, STACK_TOP = 0x20040000, 0x20042000
_sp = STACK_TOP - micropython.stack_use()
for _a in range(STACK_BOTTOM + 64, _sp - 512, 4):
    machine.mem32[_a] = 0x5AA5C33C
gc.collect()
print('HEAP free_before_desktop', gc.mem_free())
desk = Desktop(menus=MENUS, cursor=False)
try:
    app = Editor(desk, ram_docs(blocks=16), 'ベンチ')   # saves nothing: a small disk
    w, ed = app.win, app.ed
    desk.present()
    gc.collect()
    print('HEAP free_with_editor', gc.mem_free())
    # The session's run sink, timed: FPGA write and FENCE per run of tiles.
    link = [0, 0, 0]
    lw, lf, dev = desk._lwrite, desk._lfence, desk.device
    def timed_sink(first, data):
        t0 = time.ticks_us()
        lw(first * 32, data, dev.timeout_us)
        t1 = time.ticks_us()
        lf(dev.timeout_us)
        t2 = time.ticks_us()
        link[0] += time.ticks_diff(t1, t0)
        link[1] += time.ticks_diff(t2, t1)
        link[2] += 1
    if lw is not None:
        desk._sink = timed_sink
    def p(v, q):
        return v[min(len(v) - 1, len(v) * q // 100)]
    def run(name, fn, n):
        times, parts, tiles = [], [[], [], [], [], [], []], 0
        gc.collect()
        a0 = gc.mem_alloc()
        for i in range(n):
            w0, f0 = link[0], link[1]
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
            wr, fe = link[0] - w0, link[1] - f0
            send = time.ticks_diff(t4, t3)
            for k, v in enumerate((time.ticks_diff(t1, t0), time.ticks_diff(t2, t1), time.ticks_diff(t3, t2),
                                   send - wr - fe, wr, fe)):
                parts[k].append(v)
        a1 = gc.mem_alloc()
        times.sort()
        for q in parts:
            q.sort()
        print('KEY %-26s n %3d p50 %6d p95 %6d max %6d us  tiles/key %5.1f  heap/key %6.1f' % (
            name, n, p(times, 50), p(times, 95), times[-1], tiles / n, (a1 - a0) / n))
        print('    p50 key %d  app %d  compose %d  pack %d  write %d  fence %d us;  p95 compose %d  write %d' % (
            tuple(p(q, 50) for q in parts) + (p(parts[2], 95), p(parts[4], 95))))
    def view(name, text, n=15):
        w.set_text(ed, text)
        desk.present()
        x, y, ww, hh = w.work()
        def redraw(i):
            desk.invalidate(x + 2, y + 2, ww - 4, 154)
        run(name, redraw, n)
    # 8 KB of text, inserted a line at a time (one 8 KB str rarely fits the heap).
    w.set_text(ed, '')
    line = 'x' * 79 + '\n'
    for _ in range(102):
        desk.text(line)
    desk.key(kd.KEY_HOME, 0, kd.MOD_CTRL)
    app.handle(); desk.present()
    print('DOC bytes', w.length(ed))
    run('8 KB doc: insert at start', lambda i: desk.key(kd.KEY_CHAR, 'y') if i % 2 == 0 else desk.key(kd.KEY_BACKSPACE), 40)
    gc.collect()
    doc = ''.join('%03d 行目 神楽メモ帳のテキスト\n' % i for i in range(100))
    view('VIEW Japanese 38/line', ('漢字仮名交じり文の表示' * 4 + '\n') * 20)
    view('VIEW ASCII 38/line', ('The quick brown fox jumps over a dog' + '\n') * 20)
    view('VIEW mixed document', doc)
    w.set_text(ed, doc)
    for _ in range(40):
        desk.key(kd.KEY_DOWN)
    desk.key(kd.KEY_END)
    app.handle(); desk.present()
    run('type ASCII (line end)', lambda i: desk.key(kd.KEY_CHAR, 97 + i % 26), 80)
    run('type Japanese (text)', lambda i: desk.text('漢'), 60)
    run('caret left', lambda i: desk.key(kd.KEY_LEFT), 60)
    w.select(ed, 41 * 18 + 5)                 # back to a short line, column 5, in view
    app.handle(); desk.present()
    run('caret up/down', lambda i: desk.key(kd.KEY_UP if i % 2 else kd.KEY_DOWN), 60)
    run('Enter (lines below move)', lambda i: desk.key(kd.KEY_ENTER), 30)
    run('Backspace joining lines', lambda i: desk.key(kd.KEY_BACKSPACE), 30)
    run('PgDn / PgUp', lambda i: desk.key(kd.KEY_PGDN if i % 2 == 0 else kd.KEY_PGUP), 30)
    run('idle frame', lambda i: None, 40)
    gc.collect()
    print('HEAP free_after_bench', gc.mem_free())
finally:
    desk.close()
_low = _sp
for _a in range(STACK_BOTTOM + 64, _sp - 512, 4):
    if machine.mem32[_a] != 0x5AA5C33C:
        _low = _a
        break
print('STACK deepest_use %d B of %d (free below: %d B)' % (STACK_TOP - _low, STACK_TOP - STACK_BOTTOM,
                                                          _low - STACK_BOTTOM))
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

SKK = r'''
print('\n' * 30)
import gc
gc.collect()
print('FREE before', gc.mem_free())
main(key_ms=%d, step_ms=%d)
gc.collect()
print('SKK done; free', gc.mem_free(), 'console paused', kagura_console.paused)
'''

SKK_LIVE = r'''
import gc
from kagura.desktop import Desktop
from kagura import skk
desk = Desktop(menus=de.MENUS, cursor=False)
try:
    app = de.Editor(desk, de.Documents('/docs'), 'キーボード', ime=skk.SkkEngine(skk.test_dictionary()))
    desk.present()
    print('READY')
    keyboard(app)
    print('TEXT', 'ok' if app.win.get_text(app.ed) == FINAL_TEXT else 'MISMATCH', repr(app.win.get_text(app.ed)))
finally:
    desk.close()
gc.collect()
print('CLOSED free', gc.mem_free(), 'console_paused', kagura_console.paused)
'''

# Continuous SKK typing on the board for a time, fed through the decoder:
# per-key time (in a fixed array, so measuring allocates nothing), heap after
# GC, a full recomposition that must change nothing, and ERROR_CODE.
SKK_SOAK = r'''
import gc, time
from array import array
from kagura.desktop import Desktop
from kagura import skk, regs as R
desk = Desktop(menus=de.MENUS, cursor=False)
try:
    app = de.Editor(desk, de.Documents('/docs'), 'ソーク', ime=skk.SkkEngine(skk.test_dictionary()))
    keys = de.input_chain(app, clock=FakeClock())
    w, ed = app.win, app.ed
    desk.present()
    rotation = [d for d, _ in SCRIPT] + [b'\r', b'Kanji      s', b'ToKu', b'\x1b\x1b', b'\r']
    hist = array('I', [0] * 200)                     # 0.5 ms buckets: no allocation while measuring
    worst = 0
    n = keys_total = checks = bad = 0
    lo = 10 ** 9
    end = time.ticks_add(time.ticks_ms(), %d * 1000)
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        for chunk in rotation:
            for b in chunk:
                t0 = time.ticks_us()
                keys.feed(bytes((b,)))
                keys.expire()
                app.handle()
                desk.present()
                dt = time.ticks_diff(time.ticks_us(), t0)
                hist[min(199, dt // 500)] += 1
                worst = max(worst, dt)
                keys_total += 1
        n += 1
        if w.length(ed) > 6000:                      # keep the document bounded
            w.set_text(ed, '')
        if n %% 5 == 0:
            desk.invalidate(0, 0, 320, 200)
            ok = desk.present() == 0 and desk.device.read_reg(R.REG_ERROR_CODE) == 0 and not app.ime.active()
            checks += 1
            bad += not ok
            gc.collect()
            lo = min(lo, gc.mem_free())
            if checks %% 10 == 0:
                print('SOAK progress %%d rounds, %%d keys, %%d failed, free %%d' %% (n, keys_total, bad, gc.mem_free()))
    def pct(q):
        need, acc = keys_total * q // 100, 0
        for i in range(200):
            acc += hist[i]
            if acc > need:
                return (i + 1) * 500
        return worst
    print('SOAK %%d rounds, %%d keys, %%d checks, %%d failed, lowest free heap %%d B' %% (n, keys_total, checks, bad, lo))
    print('KEYS p50 <%%d p95 <%%d max %%d us (all %%d keys, 0.5 ms buckets)' %% (pct(50), pct(95), worst, keys_total))
    print('STATS', desk.stats())
finally:
    desk.close()
gc.collect()
print('CLOSED free', gc.mem_free(), 'console paused', kagura_console.paused)
'''

TEXT = ('神楽メモ帳でキーボードから入力しています。\n'
        'RP2040とFPGAの小さなコンピュータ、KAGURA-9です。\n'
        'Shift+矢印で選択、Ctrl+Sで保存します。\n')


def skk_script_bytes():
    """The byte chunks of desktop_skk.SCRIPT, read as a literal (not executed)."""
    import ast
    tree = ast.parse((ROOT / 'software/micropython/examples/desktop_skk.py').read_text(encoding='utf8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'SCRIPT':
            return [data for data, _ in ast.literal_eval(node.value)]
    raise SystemExit('SCRIPT not found in desktop_skk.py')


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
    p.add_argument('phase', choices=('bench', 'live', 'showcase', 'skk', 'skk-live', 'skk-soak'))
    p.add_argument('--seconds', type=int, default=300, help='skk-soak duration')
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
        # One exec per module: compiling everything at once needs the source,
        # parse and code together and fragments the heap.
        free = "import gc\ngc.collect()\nprint('FREE', gc.mem_free())\n"
        if args.phase == 'bench':
            b.run(lib)
            b.run(free)
            b.run(BENCH, timeout=300)
        elif args.phase.startswith('skk'):
            # desktop_skk imports desktop_editor; from RAM, the editor's globals
            # stand in for it (kagura.skk is frozen in the firmware).
            demo = example('desktop_skk.py').replace('import desktop_editor as de\n', SHOWCASE_NS)
            b.run(free)
            b.run(lib)
            b.run(free)
            b.run(demo)
            b.run(free)
            if args.phase == 'skk':
                b.run(SKK % (int(70 * args.pace), int(1500 * args.pace)), timeout=900)
            elif args.phase == 'skk-soak':
                b.run(SKK_SOAK % args.seconds, timeout=args.seconds + 300)
            else:
                b.start(SKK_LIVE)
                b.lines('READY', timeout=30)
                time.sleep(2)
                for data in skk_script_bytes():
                    send(b, [bytes((c,)) for c in data], args.cps)
                    time.sleep(0.6)
                send(b, [b'\x1b[21~'] + [b'\x1b[B'] * 4 + [b'\r'], 3)      # F10 > 終了
                time.sleep(1)
                send(b, [b'\t', b'\r'], 2)                                    # 破棄 (the text is modified)
                b.lines('CLOSED', timeout=60)
                out, err = b.finish()
                if err.strip():
                    raise SystemExit('device error: ' + err.strip().splitlines()[-1])
            time.sleep(4)
        elif args.phase == 'showcase':
            # desktop_showcase imports desktop_editor; from RAM, the editor's
            # globals (sent just before) stand in for that module.
            show = example('desktop_showcase.py').replace('import desktop_editor as de\n', SHOWCASE_NS)
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
