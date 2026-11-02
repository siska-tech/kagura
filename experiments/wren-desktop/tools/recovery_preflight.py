"""Control reboot, full hash, BOOTSEL readback, then return to MicroPython.
This script performs NO flash programming. Run only on the authorized Pico.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'c-gem-desktop/tools'))
import rp2040_sram_bench as base
p=argparse.ArgumentParser(); p.add_argument('--backup',type=Path,required=True); p.add_argument('--picotool',required=True); p.add_argument('--out',type=Path,required=True); p.add_argument('--port'); p.add_argument('--expected-serial'); a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=True)
image=a.backup.read_bytes(); digest=hashlib.sha256(image).hexdigest(); assert len(image)==base.FLASH_BYTES
base.resolve_device(a)
def log(s): print(s,flush=True); (a.out/'recovery-preflight.txt').open('a',encoding='utf-8').write(s+'\n')
assert base.flash_hash(a.port)==digest
try: base.micropython_exec(a.port,'import machine\nmachine.reset()\n',timeout=2)
except Exception: pass
port=base.wait_port(a.expected_serial); assert port
time.sleep(4)
h,console=base.flash_hash(port,True); log('CONTROL hash='+h+' console='+console)
assert h==digest and console==base.CONSOLE_OK
try: base.micropython_exec(port,'import machine\nmachine.bootloader()\n',timeout=2)
except Exception: pass
drive,info=base.find_bootsel_drive(); log('BOOTSEL '+' | '.join(info.splitlines()))
assert 'RPI-RP2' in info
def tool(*args):
    r=subprocess.run([a.picotool,*map(str,args)],capture_output=True,text=True,timeout=60)
    log(r.stdout+r.stderr); assert r.returncode==0
try:
    tool('info','-a')
    dump=a.out/'bootsel-preflight-full.bin'; assert not dump.exists()
    tool('save','-a',dump,'-t','bin')
    assert dump.read_bytes()==image
    log('BOOTSEL_BACKUP_READBACK_SHA256 '+digest)
finally:
    # A failed recovery prerequisite forbids flashing; return to original code.
    subprocess.run([a.picotool,'reboot'],capture_output=True,timeout=30)
port=base.wait_port(a.expected_serial); assert port; time.sleep(4)
h,console=base.flash_hash(port,True); log('RETURN hash='+h+' console='+console)
assert h==digest and console==base.CONSOLE_OK
log('RECOVERY_PREFLIGHT_PASS no_flash_writes')
