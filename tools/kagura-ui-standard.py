# SPDX-License-Identifier: Apache-2.0
"""Measure the normally installed UI; no mount, firmware or filesystem writes.

Requires mpremote/pyserial and a matching frozen SDK/UI with glyph8. The named
RP2040 is soft-reset, the HDMI console is lent to the UI, and finally restored.
Application source is sent through ordinary raw REPL, as with mpremote run.
"""
import argparse
import codecs
from datetime import datetime, timezone
from pathlib import Path
import sys
import time


def main():
    from mpremote.transport_serial import SerialTransport
    from serial.tools.list_ports import comports

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--expected-serial', required=True)
    parser.add_argument('--samples', type=int, default=32)
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--seconds', type=int, default=0)
    parser.add_argument('--log', type=Path, default=Path('build/ui-phase2/standard.txt'))
    args = parser.parse_args()
    if not 2 <= args.samples <= 512 or not 1 <= args.cycles <= 1000 or not 0 <= args.seconds <= 86400:
        parser.error('samples 2..512; cycles 1..1000; seconds 0..86400')
    ports = [p for p in comports() if p.device.lower() == args.port.lower()]
    if (len(ports) != 1 or ports[0].vid != 0x2e8a or
            (ports[0].serial_number or '').lower() != args.expected_serial.lower()):
        parser.error('port/USB vendor/serial mismatch; no device action taken')
    root = Path(__file__).resolve().parents[1]
    args.log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding='utf8')
    with args.log.open('w', encoding='utf8', newline='\n') as log:
        def emit(value):
            value = value.replace('\r','')
            print(value, end='', flush=True)
            log.write(value)
            log.flush()

        emit('HOST_START ' + datetime.now(timezone.utc).isoformat() + '\n')
        transport = SerialTransport(args.port, timeout=0.2)
        transport.serial.write_timeout = 5
        entered = False
        failed = True

        def run(source, timeout=60):
            # Decode incremental bytes only for display. Bytewise consumption
            # avoids retaining an hour of telemetry in mpremote's output buffer.
            decoder = codecs.getincrementaldecoder('utf8')('replace')
            pending = bytearray()
            def consume(data):
                if data != b'\x04':
                    pending.extend(data)
                    if b'\n' in data or len(pending) >= 1024:
                        emit(decoder.decode(pending))
                        pending.clear()
            output, error = transport.exec_raw(source, timeout=timeout, data_consumer=consume)
            emit(decoder.decode(pending,final=True))
            if output:
                emit(output.decode('utf8', 'replace'))
            if error:
                emit(error.decode('utf8', 'replace'))
                raise RuntimeError('device exception; see log')

        try:
            transport.enter_raw_repl(soft_reset=True)
            entered = True
            run("import sys,kagura,kagura.ui,gc,time,binascii,json; from kagura.ui import App,Theme,BitmapFont8; from kagura_ja import Font; from kagura.framebuffer import TileFramebuffer; assert sys.implementation.version[:3]==(1,26,0); assert 'RP2040' in sys.implementation._machine; assert kagura.ui.__path__=='.frozen/kagura/ui'; assert callable(getattr(TileFramebuffer,'glyph8',None)); assert kagura_console.screen.device.__class__.__module__=='kagura.device'; print('STANDARD_RUNTIME',sys.implementation); print('STANDARD_PROFILE',kagura_console.screen.device.abi,kagura_console.screen.device.caps,kagura_console.screen.device.transport.link,kagura_console.screen.device.transport.acceleration.enabled)")
            run((root / 'software/micropython/examples/ui_gallery.py').read_bytes())
            run("font=Font('/fonts/misaki8.kfnt'); app=App(kagura_console.screen.device,console=kagura_console,theme=Theme(BitmapFont8(font))); build(app); app.step(); native_crc=binascii.crc32(app.backend.fb.buffer); print('STANDARD_NATIVE_CRC',native_crc); app.backend.glyph8=None; app.damage((0,0,320,240)); app.step(); print('STANDARD_RUNS_CRC',binascii.crc32(app.backend.fb.buffer)); assert binascii.crc32(app.backend.fb.buffer)==native_crc; del app.backend.glyph8; app.backend.fb.set_viper(False); app.damage((0,0,320,240)); app.step(); assert binascii.crc32(app.backend.fb.buffer)==native_crc; print('STANDARD_PYTHON_CRC',native_crc); app.close(); del app; gc.collect()")
            run((root / 'software/micropython/examples/ui_benchmark.py').read_bytes())
            # Same font, native SDK, app workload and transport in both profiles.
            run("app,widgets=make(kagura_console.screen.device,font,console=kagura_console); app.start(); assert app.backend.fb.viper_enabled; app.backend.glyph8=None; run(app,widgets,samples=%d,cycles=1,profile='runs'); del app.backend.glyph8; app.close(); del widgets,app; gc.collect()" % args.samples, timeout=600)
            begin = time.monotonic()
            run("app,widgets=make(kagura_console.screen.device,font,console=kagura_console)\ntry:run(app,widgets,samples=%d,cycles=%d,seconds=%d,profile='glyph8')\nfinally:app.close()" % (args.samples,args.cycles,args.seconds), timeout=max(600,args.seconds+600))
            emit('HOST_NATIVE_ELAPSED_SECONDS %.3f\n' % (time.monotonic()-begin))
            run("kagura_console.screen.device.check_errors(); print('STANDARD_RESTORED',kagura_console.paused,kagura_console._attached); assert not kagura_console.paused and kagura_console._attached")
            failed = False
        finally:
            try:
                if entered:
                    if failed:
                        # A host timeout can leave the bounded device loop
                        # running. Interrupt it before sending cleanup code;
                        # preserve its globals so app.close can restore video.
                        transport.enter_raw_repl(soft_reset=False)
                    run("\nif 'app' in globals(): app.close()\nif 'font' in globals(): font.close()\nprint('STANDARD_CLEANUP')")
                    transport.exit_raw_repl()
            finally:
                transport.close()
                emit('HOST_END ' + datetime.now(timezone.utc).isoformat() + '\n')


if __name__ == '__main__':
    main()
