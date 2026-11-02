# SPDX-License-Identifier: Apache-2.0
"""RP2040 damage_limit=1 versus 4 on the installed firmware; no flash/filesystem writes.

run: the named Pico is soft-reset. kagura/ui/render.py, app.py, fonts.py and
widgets.py from this checkout (or from --ref) are sent as source over raw REPL
into one namespace (relative imports made absolute, app.py using the sent render
names; widgets.py after the benchmark so its Scene uses those classes) and used
for BOTH limits, so frozen-versus-RAM bytecode does not bias the comparison.
Other UI modules and the SDK stay frozen and must match except the
data-only Widget/Panel.opaque attributes, which are set on older frozen classes
and logged. --font-cache selects the BitmapFont8 glyph cache (0 disables);
cache sizes and refs are compared in separate sessions. --framebuffer also sends
kagura/framebuffer.py (same ref) and hands the UI an instance of that RAM class
before start(); the native Viper kernels stay frozen. The HDMI console is
lent to the UI and restored; FPGA ERROR_CODE is read.
summarize: offline table from a run log (also used by the PC tests).
"""
import argparse
import codecs
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_source(path, ref=None):
    """Working-tree file, or the file at git ref (A/B runs with one tool version)."""
    if ref is None:
        return (ROOT / path).read_text(encoding='utf8')
    return subprocess.run(['git', '-C', str(ROOT), 'show', '%s:%s' % (ref, path)],
                          capture_output=True, check=True).stdout.decode('utf8')


def branch_source(name, min_imports=0, ref=None):
    source = read_source('software/micropython/kagura/ui/' + name, ref)
    rewritten, count = re.subn(r'^from \.(\w+) import', r'from kagura.ui.\1 import', source, flags=re.M)
    if count < min_imports or '\nfrom .' in rewritten:
        raise SystemExit('unexpected imports in kagura/ui/' + name)
    return rewritten


def framebuffer_source(ref=None):
    source = read_source('software/micropython/kagura/framebuffer.py', ref)
    source, count = re.subn(r'^(\s*)from \.(\w*) import', lambda m: '%sfrom kagura%s import' % (
        m.group(1), '.' + m.group(2) if m.group(2) else ''), source, flags=re.M)
    if count < 4 or re.search(r'^\s*from \.', source, flags=re.M):
        raise SystemExit('unexpected imports in kagura/framebuffer.py')
    return source


def branch_app_source(with_render=False, ref=None):
    source = branch_source('app.py', 3, ref)
    if with_render:
        # render.py was executed in the same raw-REPL globals; use those names
        # instead of the frozen kagura.ui.render.
        source, count = re.subn(r'^from kagura\.ui\.render import [^\n]*\n', '', source, flags=re.M)
        if count != 1:
            raise SystemExit('unexpected render import in kagura/ui/app.py')
    return source


def git_identity(ref=None):
    if ref is not None:
        out = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', ref], capture_output=True, text=True)
        return 'ref:%s=%s' % (ref, out.stdout.strip())
    try:
        head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'software', 'tools'],
                               capture_output=True, text=True).stdout.strip()
        return head + ('+dirty' if dirty else '')
    except OSError:
        return 'unknown'


def run_device(args):
    from mpremote.transport_serial import SerialTransport
    from serial.tools.list_ports import comports

    ports = [p for p in comports() if p.device.lower() == args.port.lower()]
    if (len(ports) != 1 or ports[0].vid != 0x2e8a or
            (ports[0].serial_number or '').lower() != args.expected_serial.lower()):
        raise SystemExit('port/USB vendor/serial mismatch; no device action taken')
    render_source = branch_source('render.py', ref=args.ref)
    app_source = branch_app_source(with_render=True, ref=args.ref)
    font_source = branch_source('fonts.py', ref=args.ref)
    widgets_source = branch_source('widgets.py', 1, ref=args.ref)
    fb_source = framebuffer_source(args.ref) if args.framebuffer else ''
    # The benchmark itself always comes from this working tree.
    bench_source = (ROOT / 'software/micropython/examples/ui_damage_benchmark.py').read_bytes()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding='utf8')
    with args.log.open('w', encoding='utf8', newline='\n') as log:
        def emit(value):
            value = value.replace('\r', '')
            print(value, end='', flush=True)
            log.write(value)
            log.flush()

        emit('HOST_START %s\n' % datetime.now(timezone.utc).isoformat())
        emit('HOST_SOURCE git=%s render_sha256=%s app_sha256=%s fonts_sha256=%s widgets_sha256=%s bench_sha256=%s font_cache=%s\n' % (
            git_identity(args.ref), hashlib.sha256(render_source.encode('utf8')).hexdigest(),
            hashlib.sha256(app_source.encode('utf8')).hexdigest(),
            hashlib.sha256(font_source.encode('utf8')).hexdigest(),
            hashlib.sha256(widgets_source.encode('utf8')).hexdigest(),
            hashlib.sha256(bench_source).hexdigest(),
            'default' if args.font_cache is None else args.font_cache))
        emit('HOST_FRAMEBUFFER %s\n' % ('ram sha256=' + hashlib.sha256(fb_source.encode('utf8')).hexdigest()
                                        if args.framebuffer else 'frozen'))
        transport = SerialTransport(args.port, timeout=0.2)
        transport.serial.write_timeout = 5
        entered = False
        failed = True

        def run(source, timeout=60):
            decoder = codecs.getincrementaldecoder('utf8')('replace')
            pending = bytearray()

            def consume(data):
                if data != b'\x04':
                    pending.extend(data)
                    if b'\n' in data or len(pending) >= 1024:
                        emit(decoder.decode(pending))
                        pending.clear()
            output, error = transport.exec_raw(source, timeout=timeout, data_consumer=consume)
            emit(decoder.decode(pending, final=True))
            if output:
                emit(output.decode('utf8', 'replace'))
            if error:
                emit(error.decode('utf8', 'replace'))
                raise RuntimeError('device exception; see log')

        try:
            transport.enter_raw_repl(soft_reset=True)
            entered = True
            run("import sys,gc,machine,binascii,kagura,kagura.ui; from kagura.framebuffer import TileFramebuffer; from kagura_ja import Font; "
                "assert sys.implementation.version[:3]==(1,26,0); assert 'RP2040' in sys.implementation._machine; "
                "assert kagura.ui.__path__=='.frozen/kagura/ui'; assert callable(getattr(TileFramebuffer,'glyph8',None)); "
                "d=kagura_console.screen.device; t=d.transport; "
                "print('DAMAGE_RUNTIME',sys.implementation); "
                "print('DAMAGE_PROFILE',machine.freq(),d.abi,d.caps,t.link,getattr(t,'lanes',None),getattr(t,'baudrate',None),t.acceleration.enabled); "
                "gc.collect(); _reserve=bytearray(40000)")
            # Branch render.py and App in RAM; frozen kagura.ui modules are not replaced.
            run(render_source + "\ngc.collect()\nprint('DAMAGE_RENDER_LOADED',gc.mem_free())")
            run(app_source +"\nDamageApp=App\nassert hasattr(DamageApp,'_add_damage')\ndel App\ngc.collect()\nprint('DAMAGE_APP_LOADED',gc.mem_free())")
            # Branch widget.py adds data-only class attributes; mirror them on older frozen
            # UI classes (never on SDK classes) and log it.
            run("from kagura.ui.widget import Widget as _W, Panel as _P\n"
                "if not hasattr(_W,'opaque'):\n _W.opaque=False; _P.opaque=True; print('DAMAGE_FROZEN_ATTR opaque set')\n"
                "assert _P.opaque and not _W.opaque")
            run(font_source + "\nDamageFont=BitmapFont8\ndel BitmapFont8\ngc.collect()\nprint('DAMAGE_FONT_LOADED',gc.mem_free())")
            run(bench_source + b"\ngc.collect()\nprint('DAMAGE_BENCH_LOADED',gc.mem_free())")
            # After the benchmark: its Scene resolves Label/Button/ListView from these globals.
            run(widgets_source + "\ngc.collect()\nprint('DAMAGE_WIDGETS_LOADED',gc.mem_free())")
            if args.framebuffer:
                # Its own module globals, so SDK helper names cannot shadow UI ones.
                run("_fbns={'__name__':'damage_framebuffer'}\nexec(%r,_fbns)\nDamageFramebuffer=_fbns['TileFramebuffer']\n"
                    "assert DamageFramebuffer is not TileFramebuffer\ngc.collect()\nprint('DAMAGE_FRAMEBUFFER_LOADED',gc.mem_free())" % fb_source)
            font_class = 'DamageFont' if args.font_cache is None else 'lambda s:DamageFont(s,cache=%d)' % args.font_cache
            run("font=Font('/fonts/misaki8.kfnt'); del _reserve; gc.collect(); "
                "app,scene=make(DamageApp,d,font,console=kagura_console,font_class=%s); "
                "%s"
                "print('DAMAGE_APP_READY',gc.mem_free(),'FONT_CACHE',len(getattr(app.theme.font,'_keys',None) or ()),"
                "'FB',type(app.backend.fb).__name__ if app.backend.fb else 'frozen')" % (
                    font_class, "app.backend.fb=DamageFramebuffer(d); assert app.backend.fb.viper_enabled; " if args.framebuffer else ''))
            begin = time.monotonic()
            run("try:\n run(app,scene,limits=(1,4),samples=%d,rounds=%d)\n"
                " full=(0,0,320,240); app.step(); c=binascii.crc32(app.backend.fb.buffer)\n"
                " app.backend.fb.set_viper(False); app.damage(full); app.step(); p=binascii.crc32(app.backend.fb.buffer)\n"
                " app.backend.fb.set_viper(True); print('DAMAGE_VIPER_PYTHON_CRC',c,p); assert c==p\n"
                "finally:\n app.close()" % (args.samples, args.rounds), timeout=args.timeout)
            emit('HOST_RUN_SECONDS %.3f\n' % (time.monotonic() - begin))
            run("from kagura import regs as R; code=d.read_reg(R.REG_ERROR_CODE); print('DAMAGE_FPGA_ERROR_CODE',code); "
                "d.check_errors(); print('DAMAGE_RESTORED',kagura_console.paused,kagura_console._attached); "
                "assert not kagura_console.paused and kagura_console._attached; font.close()")
            failed = False
        finally:
            try:
                if entered:
                    if failed:
                        # Interrupt a still-running bounded loop; keep globals so app.close restores video.
                        transport.enter_raw_repl(soft_reset=False)
                    run("\nif 'app' in globals(): app.close()\nif 'font' in globals(): font.close()\nprint('DAMAGE_CLEANUP')")
                    transport.exit_raw_repl()
            finally:
                transport.close()
                emit('HOST_END %s %s\n' % (datetime.now(timezone.utc).isoformat(), 'FAILED' if failed else 'OK'))


def summarize(lines):
    """Per limit/workload over rounds: min..max of per-round p50, max of p95/p99, total tiles/bytes."""
    rows, done, checks = {}, None, {}
    for line in lines:
        for tag in ('UI_DAMAGE_DONE ', 'UI_DAMAGE ', 'DAMAGE_FPGA_ERROR_CODE ', 'DAMAGE_RESTORED ', 'DAMAGE_VIPER_PYTHON_CRC '):
            if line.startswith(tag):
                body = line[len(tag):].strip()
                if tag == 'UI_DAMAGE ':
                    value = json.loads(body)
                    rows.setdefault((value['workload'], value['limit']), []).append(value)
                elif tag == 'UI_DAMAGE_DONE ':
                    done = json.loads(body)
                else:
                    checks[tag.strip()] = body
                break
    if done is None:
        raise SystemExit('UI_DAMAGE_DONE missing: incomplete run')
    for key, values in rows.items():
        if len(values) != done['rounds']:
            raise SystemExit('incomplete rounds for %r' % (key,))
    out = ['| workload | limit | frame p50 (min..max) | frame p95/p99 max | cpu p50 | flush p50 | tiles | payload B | heap/step p50 | GC seen |',
           '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for workload in done['workloads']:
        for limit in done['limits']:
            v = rows[(workload, limit)]
            p50 = [r['frame_us_p50_p95_p99'][0] for r in v]
            heap = [r['heap_step_delta_p50_max'][0] for r in v if r['heap_step_delta_p50_max']]
            gcs = [r['gc_observed_steps'] for r in v if r['gc_observed_steps'] is not None]
            out.append('| %s | %d | %d..%d | %d/%d | %d..%d | %d..%d | %d | %d | %s | %s |' % (
                workload, limit, min(p50), max(p50),
                max(r['frame_us_p50_p95_p99'][1] for r in v), max(r['frame_us_p50_p95_p99'][2] for r in v),
                min(r['cpu_us_p50_p95_p99'][0] for r in v), max(r['cpu_us_p50_p95_p99'][0] for r in v),
                min(r['flush_us_p50_p95_p99'][0] for r in v), max(r['flush_us_p50_p95_p99'][0] for r in v),
                sum(r['tiles'] for r in v), sum(r['pattern_payload_bytes'] for r in v),
                ('%d..%d' % (min(heap), max(heap))) if heap else 'n/a',
                sum(gcs) if gcs else 'n/a'))
    out.append('')
    out.append('percentiles are per round of %d samples (floor((N-1)*p/100)); not whole-run percentiles.' % done['samples'])
    for name, body in checks.items():
        out.append('%s %s' % (name, body))
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    device = sub.add_parser('run')
    device.add_argument('--port', required=True)
    device.add_argument('--expected-serial', required=True)
    device.add_argument('--samples', type=int, default=32)
    device.add_argument('--rounds', type=int, default=4)
    device.add_argument('--timeout', type=int, default=1800)
    device.add_argument('--log', type=Path, default=Path('build/ui-damage/device.txt'))
    device.add_argument('--ref', default=None,
                        help='send kagura/ui sources from this git ref instead of the working tree')
    device.add_argument('--font-cache', type=int, default=None,
                        help='BitmapFont8 glyph cache slots (0 or a power of two); default: the branch default')
    device.add_argument('--framebuffer', action='store_true',
                        help='also send kagura/framebuffer.py from the same ref and use it for the UI')
    offline = sub.add_parser('summarize')
    offline.add_argument('log', type=Path)
    args = parser.parse_args()
    if args.command == 'run':
        if not 2 <= args.samples <= 512 or not 2 <= args.rounds <= 64 or args.rounds % 2:
            parser.error('samples 2..512; rounds even 2..64 (ABBA order)')
        run_device(args)
    else:
        sys.stdout.reconfigure(encoding='utf8')
        print(summarize(args.log.read_text(encoding='utf8').splitlines()))


if __name__ == '__main__':
    main()
