# SPDX-License-Identifier: Apache-2.0
"""RP2040 RAM-only acceptance of the sprite editor example; no flash/filesystem writes.

The named Pico is soft-reset. kagura/ui/render.py, app.py, canvas.py and
examples/ui_sprite_editor.py from this checkout (or --ref) are sent as source
over raw REPL (as in kagura-ui-canvas.py); other UI modules and the SDK stay
frozen. The HDMI console is lent to the UI and restored; ERROR_CODE is read.
Reports: the sprite from the event sequence of tests/ui_sprite_editor_runtime.py
(must match the PC), incremental versus full-repaint CRC, grid and 1:1 preview
pixels against the TILE4 data, the hex round trip, and frame/cpu/flush times.
"""
import argparse
import codecs
import hashlib
import importlib.util
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('kagura_ui_damage', ROOT / 'tools/kagura-ui-damage.py')
damage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(damage)

DEVICE = r'''
import gc,time,binascii
from kagura.ui import Theme, Event
gc.collect()
app=EditorApp(d,console=kagura_console,theme=Theme())
build(app)
e=editor
fb=None
def frame():
    a=time.ticks_us();changed=app.step();t=time.ticks_diff(time.ticks_us(),a)
    f=app.last_flush['total_us'] if changed and app.last_flush else 0
    return t,f
def report(name,values):
    v=sorted(values);n=len(v)
    print('EDITOR_TIME %s n=%d frame_p50=%d p95=%d max=%d cpu_p50=%d flush_p50=%d'%(name,n,v[n//2][0],v[(n*95)//100][0],v[-1][0],
          sorted(x[0]-x[1] for x in values)[n//2],sorted(x[1] for x in values)[n//2]))
def key(k,t=''):
    app.events.post(Event(k,t));return frame()
def check_pixels():
    bad=0
    for y in range(16):
        for x in range(16):
            v=e.sprite.get(x,y) or 0
            if fb.pixel(152+x,20+y)!=v:bad+=1
            if (x,y)!=e.grid.cursor and fb.pixel(8+x*8+4,20+y*8+4)!=v:bad+=1
    return bad
try:
    print('EDITOR_START',frame())
    fb=app.backend.fb
    # 1) event sequence of tests/ui_sprite_editor_runtime.py
    keys=('up','down','left','right','enter','delete','text','text','tab')
    seed=3
    for n in range(300):
        seed=(seed*1103515245+12345)&0x7fffffff
        k=keys[seed%len(keys)]
        app.events.post(Event(k,'0123456789abcdefu'[(seed>>8)%17] if k=='text' else ''))
        if n%3==2:frame()
    frame()
    text=e.export_hex()
    print('EDITOR_SEQUENCE cursor',e.grid.cursor,'color',e.grid.color,'sprite',binascii.crc32(e.sprite.export())&0xffffffff,text[:32])
    inc=binascii.crc32(fb.buffer)
    app.damage((0,0,320,240));frame()
    print('EDITOR_INCREMENTAL_EQ_FULL',inc==binascii.crc32(fb.buffer),'PIXEL_MISMATCH',check_pixels())
    e.import_hex(text[2:]+text[:2]);frame();e.undo();frame()
    print('EDITOR_HEX_ROUNDTRIP',e.export_hex()==text,'PIXEL_MISMATCH',check_pixels())
    time.sleep(3)
    # 2) timings; focus on the grid, cursor in the middle
    app.focus.set(e.grid);e.grid.set_cursor(7,7);e.select(5);frame()
    gc.collect();free=gc.mem_free();low=free
    paint=[];erase=[]
    for i in range(16):
        paint.append(key('enter'));erase.append(key('delete'));low=min(low,gc.mem_free())
    report('paint',paint);report('erase',erase)
    report('cursor_move',[key('right' if i&1 else 'left') for i in range(32)])
    report('select_hex',[key('text','34'[i&1]) for i in range(32)])
    key('enter')
    report('undo',[key('text','u') for i in range(32)])
    values=[]
    for i in range(16):
        e.preview.invalidate_cell(i,i);values.append(frame())
    report('preview_pixel',values)
    values=[]
    for i in range(16):
        e.preview.invalidate();values.append(frame())
    report('preview_full',values)
    a=text;b=binascii.hexlify(bytes((k*73)&0xff for k in range(128))).decode()
    values=[]
    for i in range(8):
        e.import_hex(b if i&1==0 else a);values.append(frame())
    report('import_all_pixels',values)
    print('EDITOR_IMPORT_PIXEL_MISMATCH',check_pixels())
    values=[]
    for i in range(16):
        t=e.export_hex();e.import_hex(t[:-1]+('0' if t[-1]!='0' else 'f'));values.append(frame())
    report('import_one_pixel',values)
    values=[]
    for i in range(8):
        app.damage((0,0,320,240));values.append(frame())
    report('full_redraw',values)
    print('EDITOR_HEAP start',free,'min',low)
    key('tab')
    report('palette_move',[key('right' if i&1 else 'left') for i in range(16)])
    report('palette_select',[key('enter') for i in range(16)])
    print('EDITOR_FINAL_PIXEL_MISMATCH',check_pixels())
    time.sleep(3)
finally:
    app.close()
'''


def editor_source(ref=None):
    source = damage.read_source('software/micropython/examples/ui_sprite_editor.py', ref)
    # canvas.py was executed in the same raw-REPL globals; frozen kagura.ui has no canvas module.
    source, count = re.subn(r'^from kagura\.ui\.canvas import [^\n]*\n', '', source, flags=re.M)
    if count != 1:
        raise SystemExit('unexpected canvas import in examples/ui_sprite_editor.py')
    return source


def run_device(args):
    from mpremote.transport_serial import SerialTransport
    from serial.tools.list_ports import comports

    ports = [p for p in comports() if p.device.lower() == args.port.lower()]
    if (len(ports) != 1 or ports[0].vid != 0x2e8a or
            (ports[0].serial_number or '').lower() != args.expected_serial.lower()):
        raise SystemExit('port/USB vendor/serial mismatch; no device action taken')
    sources = (('render', damage.branch_source('render.py', ref=args.ref)),
               ('app', damage.branch_app_source(with_render=True, ref=args.ref)),
               ('canvas', damage.branch_source('canvas.py', 1, ref=args.ref)),
               ('editor', editor_source(args.ref)))
    args.log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding='utf8')
    with args.log.open('w', encoding='utf8', newline='\n') as log:
        def emit(value):
            value = value.replace('\r', '')
            print(value, end='', flush=True)
            log.write(value)
            log.flush()

        emit('HOST_START %s\n' % datetime.now(timezone.utc).isoformat())
        emit('HOST_SOURCE git=%s %s\n' % (damage.git_identity(args.ref), ' '.join(
            '%s_sha256=%s' % (name, hashlib.sha256(s.encode('utf8')).hexdigest()) for name, s in sources)))
        transport = SerialTransport(args.port, timeout=0.2)
        transport.serial.write_timeout = 5
        entered = False

        def run(source, timeout=120):
            decoder = codecs.getincrementaldecoder('utf8')('replace')
            output, error = transport.exec_raw(source, timeout=timeout,
                                               data_consumer=lambda b: emit(decoder.decode(b)) if b != b'\x04' else None)
            emit(decoder.decode(b'', final=True))
            if output:
                emit(output.decode('utf8', 'replace'))
            if error:
                emit(error.decode('utf8', 'replace'))
                raise RuntimeError('device exception; see log')

        failed = True
        try:
            transport.enter_raw_repl(soft_reset=True)
            entered = True
            run("import sys,gc,machine,kagura.ui\n"
                "assert sys.implementation.version[:3]==(1,26,0) and 'RP2040' in sys.implementation._machine\n"
                "d=kagura_console.screen.device\n"
                "print('EDITOR_RUNTIME',sys.implementation._machine,machine.freq(),d.abi,kagura.ui.__path__)\n"
                "gc.collect(); _reserve=bytearray(30000)")
            render, app_src, canvas, editor = (s for _, s in sources)
            run(render + "\ngc.collect()\nprint('EDITOR_RENDER_LOADED',gc.mem_free())")
            run(app_src + "\nEditorApp=App\ndel App\ngc.collect()\nprint('EDITOR_APP_LOADED',gc.mem_free())")
            run("from kagura.ui.widget import Widget as _W, Panel as _P\n"
                "if not hasattr(_W,'opaque'):\n _W.opaque=False; _P.opaque=True; print('EDITOR_FROZEN_ATTR opaque set')")
            run(canvas + "\ngc.collect()\nprint('EDITOR_CANVAS_LOADED',gc.mem_free())")
            run(editor + "\ndel _reserve\ngc.collect()\nprint('EDITOR_LOADED',gc.mem_free())")
            run(DEVICE, timeout=args.timeout)
            run("from kagura import regs as R; print('EDITOR_FPGA_ERROR_CODE',d.read_reg(R.REG_ERROR_CODE)); d.check_errors(); "
                "print('EDITOR_RESTORED',kagura_console.paused,kagura_console._attached); "
                "assert not kagura_console.paused and kagura_console._attached")
            failed = False
        finally:
            try:
                if entered:
                    if failed:
                        transport.enter_raw_repl(soft_reset=False)
                    run("\nif 'app' in globals(): app.close()\nprint('EDITOR_CLEANUP')")
                    transport.exit_raw_repl()
            finally:
                transport.close()
                emit('HOST_END %s %s\n' % (datetime.now(timezone.utc).isoformat(), 'FAILED' if failed else 'OK'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', required=True)
    parser.add_argument('--expected-serial', required=True)
    parser.add_argument('--ref', default=None, help='send sources from this git ref')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--log', type=Path, default=Path('build/ui-sprite-editor/device.txt'))
    run_device(parser.parse_args())


if __name__ == '__main__':
    main()
