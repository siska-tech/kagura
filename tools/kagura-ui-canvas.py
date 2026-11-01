# SPDX-License-Identifier: Apache-2.0
"""RP2040 RAM-only acceptance of Canvas/SpriteCanvas; no flash/filesystem writes.

run: the named Pico is soft-reset. kagura/ui/render.py, app.py and canvas.py
from this checkout (or --ref) are sent as source over raw REPL (as in
kagura-ui-damage.py); other UI modules and the SDK stay frozen. The HDMI
console is lent to the UI and restored; FPGA ERROR_CODE is read. Reports:
the sprite from the deterministic edit sequence of tests/ui_canvas_runtime.py
(must match the PC), incremental versus full-repaint CRC, native versus Python
blit CRC, and frame/cpu/flush times for full-canvas repaints, single-pixel
edits and cursor moves.
"""
import argparse
import codecs
import hashlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('kagura_ui_damage', ROOT / 'tools/kagura-ui-damage.py')
damage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(damage)

DEVICE = r'''
import gc,time,binascii
from kagura.ui import Theme, Screen, Event
gc.collect()
app=CanvasApp(d,console=kagura_console,theme=Theme())
root=Screen(color=2)
changes=[]
canvas=root.add(SpriteCanvas(x=96,y=56,zoom=8,on_change=lambda x,y:changes.append((x,y))))
app.set_root(root)
def frame():
    a=time.ticks_us();changed=app.step();t=time.ticks_diff(time.ticks_us(),a)
    f=app.last_flush['total_us'] if changed and app.last_flush else 0
    return t,f
def report(name,values):
    v=sorted(values);n=len(v)
    print('CANVAS_TIME %s n=%d frame_p50=%d p95=%d max=%d cpu_p50=%d flush_p50=%d'%(name,n,v[n//2][0],v[(n*95)//100][0],v[-1][0],
          sorted(x[0]-x[1] for x in values)[n//2],sorted(x[1] for x in values)[n//2]))
try:
    print('CANVAS_START',frame())
    # 1) deterministic edit sequence of tests/ui_canvas_runtime.py (sprite result is backend independent)
    seed=1
    for n in range(200):
        seed=(seed*1103515245+12345)&0x7fffffff
        key=('up','down','left','right','enter','delete','text')[seed%7]
        app.events.post(Event(key,'0123456789abcdef'[(seed>>8)&15] if key=='text' else ''))
        if n%5==4:frame()
    frame()
    data=canvas.sprite.export()
    print('CANVAS_SEQUENCE changes',len(changes),'cursor',canvas.cursor,'color',canvas.color,'sprite',len(data),binascii.crc32(data)&0xffffffff)
    fb=app.backend.fb
    inc=binascii.crc32(fb.buffer)
    app.damage((0,0,320,240));frame()
    print('CANVAS_INCREMENTAL_EQ_FULL',inc==binascii.crc32(fb.buffer))
    time.sleep(3)
    # 2) full-canvas repaint: blank (one fill per row) and checker (one fill per cell)
    for name,pattern in (('repaint_blank',bytes(128)),('repaint_stripes',bytes([0x1e]*128))):
        canvas.reload(pattern);frame()
        values=[]
        for i in range(16):
            canvas.invalidate();values.append(frame())
        report(name,values)
    time.sleep(3)
    # 3) single-pixel edit at the cursor, alternating colours; then cursor moves
    canvas.set_cursor(7,7);frame()
    values=[];gc.collect();free=gc.mem_free();low=free
    for i in range(32):
        canvas.set_color(3+(i&1));app.events.post(Event('enter'));values.append(frame())
        low=min(low,gc.mem_free())
    report('pixel_edit',values)
    print('CANVAS_HEAP pixel_edit start',free,'min',low)
    values=[]
    for i in range(32):
        app.events.post(Event('right' if i&1 else 'left'));values.append(frame())
    report('cursor_move',values)
    # 4) Sprite4.source() blit: native versus Python raster, the PC Python CRCs
    copy=Sprite4(data=data)
    def blits():
        fb.fill(7)
        for x,y in ((0,0),(37,21),(-5,231),(311,100)):
            fb.blit(copy.source(),x,y,key=0)
        return binascii.crc32(fb.buffer)&0xffffffff,binascii.crc32(fb.dirty)&0xffffffff
    fb.set_viper(False);python=blits()
    fb.set_viper(True);native=blits()
    print('CANVAS_BLIT python',python,'native',native,'equal',python==native)
    fb.flush();time.sleep(3)
finally:
    app.close()
'''


def run_device(args):
    from mpremote.transport_serial import SerialTransport
    from serial.tools.list_ports import comports

    ports = [p for p in comports() if p.device.lower() == args.port.lower()]
    if (len(ports) != 1 or ports[0].vid != 0x2e8a or
            (ports[0].serial_number or '').lower() != args.expected_serial.lower()):
        raise SystemExit('port/USB vendor/serial mismatch; no device action taken')
    render_source = damage.branch_source('render.py', ref=args.ref)
    app_source = damage.branch_app_source(with_render=True, ref=args.ref)
    canvas_source = damage.branch_source('canvas.py', 1, ref=args.ref)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding='utf8')
    with args.log.open('w', encoding='utf8', newline='\n') as log:
        def emit(value):
            value = value.replace('\r', '')
            print(value, end='', flush=True)
            log.write(value)
            log.flush()

        emit('HOST_START %s\n' % datetime.now(timezone.utc).isoformat())
        emit('HOST_SOURCE git=%s render_sha256=%s app_sha256=%s canvas_sha256=%s\n' % (
            damage.git_identity(args.ref), *(hashlib.sha256(s.encode('utf8')).hexdigest()
                                            for s in (render_source, app_source, canvas_source))))
        transport = SerialTransport(args.port, timeout=0.2)
        transport.serial.write_timeout = 5
        entered = failed = False

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
                "print('CANVAS_RUNTIME',sys.implementation._machine,machine.freq(),d.abi,kagura.ui.__path__)\n"
                "gc.collect(); _reserve=bytearray(30000)")
            run(render_source + "\ngc.collect()\nprint('CANVAS_RENDER_LOADED',gc.mem_free())")
            run(app_source + "\nCanvasApp=App\ndel App\ngc.collect()\nprint('CANVAS_APP_LOADED',gc.mem_free())")
            run("from kagura.ui.widget import Widget as _W, Panel as _P\n"
                "if not hasattr(_W,'opaque'):\n _W.opaque=False; _P.opaque=True; print('CANVAS_FROZEN_ATTR opaque set')")
            run(canvas_source + "\ndel _reserve\ngc.collect()\nprint('CANVAS_LOADED',gc.mem_free())")
            run(DEVICE, timeout=args.timeout)
            run("from kagura import regs as R; print('CANVAS_FPGA_ERROR_CODE',d.read_reg(R.REG_ERROR_CODE)); d.check_errors(); "
                "print('CANVAS_RESTORED',kagura_console.paused,kagura_console._attached); "
                "assert not kagura_console.paused and kagura_console._attached")
            failed = False
        finally:
            try:
                if entered:
                    if failed:
                        transport.enter_raw_repl(soft_reset=False)
                    run("\nif 'app' in globals(): app.close()\nprint('CANVAS_CLEANUP')")
                    transport.exit_raw_repl()
            finally:
                transport.close()
                emit('HOST_END %s %s\n' % (datetime.now(timezone.utc).isoformat(), 'FAILED' if failed else 'OK'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', required=True)
    parser.add_argument('--expected-serial', required=True)
    parser.add_argument('--ref', default=None, help='send kagura/ui sources from this git ref')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--log', type=Path, default=Path('build/ui-canvas/device.txt'))
    run_device(parser.parse_args())


if __name__ == '__main__':
    main()
