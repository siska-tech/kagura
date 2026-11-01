# SPDX-License-Identifier: Apache-2.0
"""Explicit RP2040 hardware acceptance using mpremote and a read-only RAM VFS.

Requires staged v1.26 ARM mpy files; never writes files or firmware on the Pico.
--interactive hands the running USB GUI to a user terminal, without holding COM.
"""
from pathlib import Path
import argparse
import sys, time
from mpremote.transport_serial import SerialTransport
from serial.tools.list_ports import comports

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port',required=True)
parser.add_argument('--expected-serial',required=True)
parser.add_argument('--stage',type=Path,default=Path('build/ui-live'))
parser.add_argument('--log',type=Path,default=Path('build/ui-validation/device-run.txt'))
parser.add_argument('--bench',action='store_true')
parser.add_argument('--accelerate',action='store_true')
parser.add_argument('--cycles',type=int,default=2)
parser.add_argument('--hold-seconds',type=int,default=20)
parser.add_argument('--interactive',action='store_true')
args=parser.parse_args()
if not 1<=args.cycles<=1000 or not 0<=args.hold_seconds<=120:
    parser.error('cycles must be 1..1000; hold-seconds 0..120')
match=[p for p in comports() if p.device.lower()==args.port.lower()]
if len(match)!=1 or match[0].vid!=0x2e8a or (match[0].serial_number or '').lower()!=args.expected_serial.lower():
    parser.error('port/USB vendor/serial mismatch; no device action taken')
sys.stdout.reconfigure(encoding='utf8')
root=Path(__file__).resolve().parents[1]
stage=args.stage.resolve()
log=args.log.resolve()
log.parent.mkdir(parents=True,exist_ok=True)
log.write_bytes(b'')
t=SerialTransport(args.port,timeout=0.2)
t.serial.write_timeout=5
handed_off=False
def run(code,timeout=30,stream=False):
    if stream:
        with log.open('ab') as output:
            def consume(data):
                if data==b'\x04': return
                sys.stdout.buffer.write(data); output.write(data)
                if data==b'\n':
                    sys.stdout.buffer.flush(); output.flush()
            out,err=t.exec_raw(code,timeout=timeout,data_consumer=consume)
    else:
        out,err=t.exec_raw(code,timeout=timeout)
    sys.stdout.write(out.decode('utf8','replace'));sys.stdout.flush()
    with log.open('ab') as f:f.write(out+err)
    if err:raise RuntimeError(err.decode('utf8','replace'))
try:
    t.enter_raw_repl(soft_reset=True)
    run("import sys; assert sys.implementation.name=='micropython' and sys.implementation.version[:2]==(1,26); assert 'RP2040' in sys.implementation._machine; assert kagura_console.screen is not None; print('UI_RUNTIME',sys.implementation)")
    if args.accelerate:
        run("_ui_accel_old_console=kagura_console; _ui_accel_old_console.pause(); _ui_accel_raw=_ui_accel_old_console.screen.device.transport; _ui_accel_before=getattr(_ui_accel_raw,'acceleration',None); _ui_accel_session=_ui_accel_raw.accelerate(); _ui_accel_owned=_ui_accel_session is not _ui_accel_before; print('UI_TRANSPORT_ACCEL',getattr(_ui_accel_session,'enabled',None),getattr(_ui_accel_session,'reason',None),'LINK',getattr(_ui_accel_raw,'link',None),'API',dir(_ui_accel_session)); assert callable(getattr(_ui_accel_session,'close',None))")
    run((root/'software/micropython/tests/ui_ramfs.py').read_bytes())
    sdk_files=[stage/'kagura'/name for name in ('__init__.mpy','regs.mpy','device.mpy','video.mpy','framebuffer.mpy','framebuffer_viper.mpy')]
    files=sdk_files+list((stage/'kagura/ui').glob('*.mpy'))+list(stage.glob('ui_*.mpy'))
    files.sort(key=lambda p:p.stat().st_size,reverse=True)
    for path in files:
        relative=('/_kagura_ui_sdk/'+path.name) if path in sdk_files else '/'+path.relative_to(stage).as_posix()
        payload=path.read_bytes()
        run('_ui_fs.files[%r]=(%d,[]); gc.collect()'%(relative,len(payload)))
        for offset in range(0,len(payload),512):
            part=payload[offset:offset+512]
            run('_ui_fs.files[%r][1].append(%r); gc.collect()'%(relative,part))
        print('LOADED',relative,flush=True)
    run("_ui_old_console=kagura_console; _ui_old_device=_ui_old_console.screen.device; _ui_raw=_ui_old_device.transport; _ui_old_console.pause(); _ui_old_console.detach(); import _kagura_ui_sdk; import _kagura_ui_sdk.framebuffer as _ui_fbm; sys.modules['kagura.framebuffer']=_ui_fbm; kagura.framebuffer=_ui_fbm; import ui_gallery,ui_demo_common,ui_monitor,ui_studio_mock,ui_benchmark; from kagura.ui import App,Theme,BitmapFont8,Event,StdinInput; from kagura_ja import Font; _ui_fs.files.clear(); gc.collect(); print('UI_IMPORTED_CURRENT_SDK',gc.mem_free())")
    run("import time; _ui_font=Font('/fonts/misaki8.kfnt'); _ui_d=_kagura_ui_sdk.Kagura(_ui_raw).probe(); _ui_console=_ui_old_console; _ui_console.screen.device=_ui_d; gc.collect(); _ui_heap=gc.mem_free(); _ui_app=App(_ui_d,console=_ui_console,theme=Theme(BitmapFont8(_ui_font))); ui_gallery.build(_ui_app); gc.collect(); print('UI_CONSTRUCTED',gc.mem_free(),'DELTA',_ui_heap-gc.mem_free()); del _ui_reserve; gc.collect(); _ui_fb_heap=gc.mem_free(); _ui_app.backend.fb=_ui_fbm.TileFramebuffer(_ui_d); gc.collect(); print('UI_FRAMEBUFFER_HEAP',_ui_fb_heap-gc.mem_free()); _ui_console.attach(); _ui_console.paused=False; _ui_start=time.ticks_us(); _ui_app.step(); _ui_initial_total=time.ticks_diff(time.ticks_us(),_ui_start); gc.collect(); print('UI_GALLERY_STARTED',_ui_app.last_flush, 'FRAME_US',_ui_app.last_frame_us, 'INITIAL_TOTAL_US',_ui_initial_total,'FREE',gc.mem_free())",timeout=60)
    run("import machine,binascii; print('UI_PROFILE',machine.freq(),_ui_d.abi,_ui_d.caps,_ui_d.height,'LANES',getattr(_ui_raw,'lanes',None),'SCK',getattr(_ui_raw,'baudrate',None),'VIPER',_ui_app.backend.fb.viper_enabled); _ui_crc=binascii.crc32(_ui_app.backend.fb.buffer); print('GALLERY_NATIVE_CRC',_ui_crc); _ui_app.backend.fb.set_viper(False); _ui_app.damage((0,0,320,240)); _ui_app.step(); print('GALLERY_PYTHON_CRC',binascii.crc32(_ui_app.backend.fb.buffer)); assert binascii.crc32(_ui_app.backend.fb.buffer)==_ui_crc; _ui_app.backend.fb.set_viper(True)",timeout=60)
    print('GALLERY_HOLD',flush=True)
    run("import time; _ui_app.running=True; _ui_until=time.ticks_add(time.ticks_ms(),5000)\nwhile _ui_app.running and time.ticks_diff(_ui_until,time.ticks_ms())>0:\n _ui_app.step(); time.sleep_ms(10)\nprint('UI_INPUT_WINDOW_COMPLETE',_ui_app.root.children[0].children[2].text if len(_ui_app.root.children)>0 and len(_ui_app.root.children[0].children)>2 else 'second screen')",timeout=60)
    if args.bench:
        run("_ui_saved_fb=_ui_app.backend.fb; _ui_console.screen.device=_ui_old_device; _ui_app.close(); _ui_console.screen.device=_ui_d; _ui_bench_app,_ui_widgets=ui_benchmark.make(_ui_d,_ui_font,console=_ui_console); _ui_bench_app.backend.fb=_ui_saved_fb; _ui_app.backend.fb=None; del _ui_app; _ui_app=_ui_bench_app; gc.collect(); print('UI_BENCH_HEAP',gc.mem_free()); _ui_app.step(); ui_benchmark.baseline(_ui_app,samples=32); ui_benchmark.run(_ui_app,_ui_widgets,samples=32,cycles=%d)"%args.cycles,timeout=600,stream=True)
    run("ui_gallery.build(_ui_app); _ui_app.input=ui_demo_common.USBInput(); _ui_app.running=True; _ui_app.step(); print('UI_USB_READY')",timeout=60)
    t.exec_raw_no_follow("_ui_usb_end=time.ticks_add(time.ticks_ms(),5000)\nwhile _ui_app.running and time.ticks_diff(_ui_usb_end,time.ticks_ms())>0:\n _ui_app.step(); time.sleep_ms(10)\nprint('UI_USB_RESULT',_ui_app.root.children[0].children[2].text,_ui_app.events.dropped,_ui_app.running)\nassert _ui_app.root.children[0].children[2].text=='Count: 2'\nassert not _ui_app.running")
    time.sleep(0.5)
    t.serial.write(b'\r\t\x1b[Z\r\x1b')
    out,err=t.follow(timeout=30)
    print(out.decode('utf8','replace'),flush=True)
    with log.open('ab') as f:f.write(out+err)
    if err:raise RuntimeError(err.decode())
    if args.interactive:
        run("ui_gallery.build(_ui_app); _ui_app.input=StdinInput(); _ui_app.running=True; _ui_app.step(); print('UI_INTERACTIVE_READY')",timeout=60)
        t.exec_raw_no_follow("try:\n while _ui_app.running:\n  _ui_app.step(); time.sleep_ms(10)\nfinally:\n _ui_console.screen.device=_ui_old_device\n _ui_app.close()\n _ui_font.close()\n if globals().get('_ui_accel_owned',False):\n  _ui_old_device.busy+=1\n  try: _ui_accel_session.close()\n  finally: _ui_old_device.busy-=1\n kagura.__path__=_ui_old_path\n vfs.umount('/ui_ram')\n sys.path.remove('/ui_ram')\n print('UI_INTERACTIVE_RESTORED')")
        handed_off=True
        print('COM port released to your USB terminal. Tab/arrows/Enter; Escape exits. Ctrl+B returns from raw REPL.',flush=True)
        raise SystemExit(0)
    run("_ui_app.input=None; ui_studio_mock.build(_ui_app); _ui_app.step(); print('UI_STUDIO_SHOWN')",timeout=60)
    print('STUDIO_HOLD',flush=True); time.sleep(args.hold_seconds)
    run("_ui_update=ui_monitor.build(_ui_app); _ui_app.step(); time.sleep_ms(1100); _ui_update(); _ui_app.step(); print('UI_MONITOR_SHOWN')",timeout=60)
    print('MONITOR_HOLD',flush=True); time.sleep(args.hold_seconds)
    run("ui_gallery.build(_ui_app); _ui_app.step(); _ui_gallery_root=_ui_app.root; _ui_app.focus.set(_ui_app.root.children[0].children[6]); _ui_app.events.post(Event('enter')); _ui_app.step(); print('UI_SCREEN2',_ui_app.root.children[0].text); assert _ui_app.root is not _ui_gallery_root; _ui_app.events.post(Event('enter')); _ui_app.step(); assert _ui_app.root is _ui_gallery_root; _ui_app.step(); print('UI_IDLE',_ui_app.step()); _ui_console.screen.device=_ui_old_device; _ui_app.close(); _ui_font.close(); print('UI_ORIGINAL_CONSOLE_RESTORED',_ui_old_console.paused,_ui_old_console._attached); print('KAGURA-UI restored / 日本語'); _ui_old_console._flush_display(); print('UI_FPGA_ERROR',_ui_d.read_reg(_kagura_ui_sdk.regs.REG_ERROR_CODE)); kagura.__path__=_ui_old_path; vfs.umount('/ui_ram'); sys.path.remove('/ui_ram')",timeout=60)
finally:
    try:
        if not handed_off:
            try:run("\nif '_ui_old_device' in globals(): _ui_old_console.screen.device=_ui_old_device\nif '_ui_app' in globals(): _ui_app.close()\nif '_ui_old_console' in globals():\n if _ui_old_console.paused: _ui_old_console.resume()\n if not _ui_old_console._attached: _ui_old_console.attach()\nprint('UI_SESSION_FINALLY')",timeout=60)
            finally:
                t.exit_raw_repl()
                t.enter_raw_repl(soft_reset=True)
                run("import gc; gc.collect(); print('UI_CLEAN_BOOT',kagura_console.paused,kagura_console._attached,gc.mem_free()); kagura_console._flush_display()")
                t.exit_raw_repl()
    finally:t.close()
