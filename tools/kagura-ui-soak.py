# SPDX-License-Identifier: Apache-2.0
"""Run a bounded UI soak on the Pico with USB closed; collect retained results.

Requires the normally installed frozen SDK/UI. Does not write device files or
firmware. Pico power must remain on; a reset loses the completion flag and fails
collection. PC standby may delay collection, but cannot produce a false pass.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time


def validate_result(result, seconds, samples):
    finish = result['finish']
    if (not result['done'] or result['error'] is not None or not finish or
            finish['elapsed_ms'] < seconds*1000 or result['console_paused'] or
            not result['console_attached']):
        raise RuntimeError('soak did not complete or restore console')
    expected = {'idle','label','button','focus','move','scroll','screen'}
    if set(result['workloads']) != expected or result['heap']['groups'] != finish['cycles']:
        raise RuntimeError('incomplete workload telemetry')
    for work in result['workloads'].values():
        if work['groups'] != finish['cycles'] or work['samples'] != samples*finish['cycles']:
            raise RuntimeError('missing sample group')
    idle = result['workloads']['idle']
    if idle['tiles'] or idle['pattern_payload_bytes']:
        raise RuntimeError('idle transferred graphics')


def main():
    from mpremote.transport_serial import SerialTransport
    from serial.tools.list_ports import comports
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--expected-serial',required=True)
    parser.add_argument('--seconds',type=int,default=3600)
    parser.add_argument('--samples',type=int,default=32)
    parser.add_argument('--log',type=Path,default=Path('build/ui-phase2/quiet-soak.txt'))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 86400 or not 2 <= args.samples <= 512:
        parser.error('seconds 1..86400; samples 2..512')
    def check_port():
        ports = [p for p in comports() if p.device.lower()==args.port.lower()]
        if (len(ports)!=1 or ports[0].vid!=0x2e8a or
                (ports[0].serial_number or '').lower()!=args.expected_serial.lower()):
            raise RuntimeError('port/USB vendor/serial mismatch; no device action taken')
    check_port()
    sys.stdout.reconfigure(encoding='utf8')
    args.log.parent.mkdir(parents=True,exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    transport = None
    owns_app = False
    completed = False
    with args.log.open('w',encoding='utf8',newline='\n') as log:
        def emit(value):
            value = value.replace('\r','')
            print(value,end='',flush=True); log.write(value); log.flush()
        def connect(reset):
            check_port()
            link = SerialTransport(args.port,timeout=.2)
            link.serial.write_timeout = 5
            try:
                link.enter_raw_repl(soft_reset=reset)
                return link
            except BaseException:
                link.close()
                raise
        def run(source):
            output,error = transport.exec_raw(source,timeout=60)
            emit(output.decode('utf8','replace'))
            if error:
                emit(error.decode('utf8','replace'))
                raise RuntimeError('device exception; see log')
            return output.decode('utf8')
        emit('SOAK_HOST_START '+datetime.now(timezone.utc).isoformat()+'\n')
        try:
            transport = connect(True)
            run("import sys,machine,kagura,kagura.ui,json; from kagura.framebuffer import TileFramebuffer; from kagura_ja import Font; assert sys.implementation.version[:3]==(1,26,0) and 'RP2040' in sys.implementation._machine; assert kagura.ui.__path__=='.frozen/kagura/ui'; assert callable(getattr(TileFramebuffer,'glyph8',None)); raw=kagura_console.screen.device.transport; print('SOAK_PROFILE',json.dumps(dict(cpu_hz=machine.freq(),sck_hz=raw.baudrate,lanes=raw.lanes,abi=kagura_console.screen.device.abi,caps=kagura_console.screen.device.caps,acceleration=raw.acceleration.enabled)))")
            run((root/'software/micropython/examples/ui_benchmark.py').read_bytes())
            owns_app = True
            run("font=Font('/fonts/misaki8.kfnt'); app,widgets=make(kagura_console.screen.device,font,console=kagura_console); app.start(); assert app.backend.fb.viper_enabled; soak_summary=Summary(); soak_done=False; soak_error=None")
            program = """try:
 try:
  run(app,widgets,samples=%d,cycles=1,seconds=%d,profile='glyph8-quiet',report=soak_summary.report)
 finally:
  try:app.close()
  finally:font.close()
 kagura_console.screen.device.check_errors()
 soak_done=True
except BaseException as error:
 soak_error=repr(error)
 raise
""" % (args.samples,args.seconds)
            transport.exec_raw_no_follow(program)
            transport.close(); transport = None
            emit('SOAK_USB_CLOSED '+datetime.now(timezone.utc).isoformat()+'\n')
            # The program checks elapsed time itself. The grace interval allows
            # its final complete sample group and console restoration to finish.
            deadline = time.monotonic()+args.seconds+max(30,args.samples//2)
            while True:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1,remaining))
            transport = connect(False)
            output = run("print('SOAK_RESULT '+json.dumps(dict(done=soak_done,error=soak_error,heap=soak_summary.heap,workloads=soak_summary.workloads,finish=soak_summary.finish,console_paused=kagura_console.paused,console_attached=kagura_console._attached)))")
            result = json.loads(next(line[12:] for line in output.splitlines() if line.startswith('SOAK_RESULT ')))
            args.log.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf8')
            validate_result(result,args.seconds,args.samples)
            emit('SOAK_PASS\n')
            completed = True
        finally:
            try:
                if owns_app:
                    if transport is None:
                        transport = connect(False)
                    elif not completed:
                        transport.enter_raw_repl(soft_reset=False)
                    run("\nif 'app' in globals():app.close()\nif 'font' in globals():font.close()\nprint('SOAK_CLEANUP')")
                if transport is not None:
                    transport.exit_raw_repl()
            finally:
                if transport is not None:transport.close()
                emit('SOAK_HOST_END '+datetime.now(timezone.utc).isoformat()+'\n')


if __name__ == '__main__':
    main()
