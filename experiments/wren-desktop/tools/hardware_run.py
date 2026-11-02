"""Authorized RP2040 flash validation with bounded prefix writes and restoration.

Requires successful read-only recovery_preflight.py, exact hashes and --approved.
Backups/readbacks stay in the ignored build tree, never in Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'c-gem-desktop/tools'))
import rp2040_sram_bench as base

def sha(data): return hashlib.sha256(data).hexdigest()
def fields(line): return dict(part.split('=',1) for part in line.split()[1:] if '=' in part)

def main():
    p=argparse.ArgumentParser()
    for name in ('backup','elf','layout','recovery-log','out'): p.add_argument('--'+name,type=Path,required=True)
    for name in ('picotool','expected-elf-sha256','expected-backup-sha256','firmware-commit'): p.add_argument('--'+name,required=True)
    p.add_argument('--approved',action='store_true'); p.add_argument('--port'); p.add_argument('--expected-serial')
    p.add_argument('--plan-only',action='store_true',help='Validate artifacts and write a plan, with no device access')
    a=p.parse_args()
    assert a.approved or a.plan_only,'Explicit authorized hardware flag required'
    if not a.plan_only: assert 'RECOVERY_PREFLIGHT_PASS no_flash_writes' in a.recovery_log.read_text()
    original=a.backup.read_bytes(); assert len(original)==base.FLASH_BYTES and sha(original)==a.expected_backup_sha256
    assert sha(a.elf.read_bytes())==a.expected_elf_sha256
    layout=json.loads(a.layout.read_text()); assert layout['elf_sha256']==a.expected_elf_sha256
    assert layout['stack_reserved']==49152 and layout['allocator_capacity']==135168 and layout['recovery_reserved']==8192
    image,entry=base.elf_load_image(a.elf)
    assert min(image)==0x10000000 and 0x10000000<=entry<0x10200000
    length=((max(image)+1-0x10000000+4095)//4096)*4096
    assert 0<length<=256*1024 and all(0x10000000<=n<0x10000000+length for n in image)
    prefix=bytearray(b'\xff'*length)
    for address,value in image.items():prefix[address-0x10000000]=value
    expected=bytes(prefix)+original[length:]
    a.out.mkdir(parents=True,exist_ok=False)
    def log(s):
        print(s,flush=True)
        with (a.out/'hardware.log').open('a',encoding='utf-8') as f:f.write(s+'\n')
    def tool(*args,timeout=90):
        r=subprocess.run([a.picotool,*map(str,args)],capture_output=True,text=True,timeout=timeout)
        log('PICOTOOL '+ ' '.join(map(str,args))+'\n'+r.stdout+r.stderr)
        assert r.returncode==0,'picotool command failed'
    def dump(name):
        path=a.out/name; assert not path.exists(); tool('save','-a',path,'-t','bin'); return path.read_bytes()
    def enter_bootsel():
        try:base.micropython_exec(a.port,'import machine\nmachine.bootloader()\n',timeout=2)
        except Exception:pass
        _,info=base.find_bootsel_drive(); assert 'RPI-RP2' in info
        tool('info','-a')
    manifest=dict(firmware_commit=a.firmware_commit,elf_sha256=a.expected_elf_sha256,backup_sha256=sha(original),
                  firmware_region=[hex(0x10000000),hex(0x10000000+length)],programmed_full_flash_sha256=sha(expected),layout=layout)
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    program=a.out/'firmware-prefix.bin'; program.write_bytes(prefix)
    restore=a.out/'original-prefix.bin'; restore.write_bytes(original[:length])
    if a.plan_only:
        log('PLAN_ONLY no_device_access '+json.dumps(manifest)); return
    base.resolve_device(a)
    digest,console=base.flash_hash(a.port,True)
    log('BEFORE sha256='+digest+' console='+console)
    assert digest==sha(original) and console in (base.CONSOLE_OK,"(True, True, True, 'None')")
    enter_bootsel()
    assert dump('before-bootsel.bin')==original,'ROM readback differs from original backup; no writes'
    programmed=False; passed=False
    try:
        # Never use load -x: verify the entire flash and unchanged tail first.
        programmed=True
        tool('load',program,'-t','bin','-o','0x10000000','-v')
        got=dump('programmed-full.bin'); assert got==expected,'programmed flash mismatch'
        log('PROGRAMMED_READBACK_SHA256 '+sha(got)+' unchanged_tail_start='+hex(length))
        tool('reboot')
        port=base.wait_port(a.expected_serial,seconds=30); assert port,'firmware serial did not enumerate'
        import serial
        refs=[0xbe72ff88,0xc91b4078,0x7017406d,0xe89d5ada,0xf07a198f,0xabb5deb8,0xbe72ff88]
        frames=[]; memories=[]; latencies=[]; guards=None; boot=None; abi=None
        with serial.Serial(port,115200,timeout=0.3) as s:
            time.sleep(0.2); s.write(b'g'); deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                line=s.readline().decode('utf-8','replace').strip()
                if not line:continue
                log(line)
                if '*** PANIC ***' in line: raise RuntimeError('Firmware panic: stop workloads and restore')
                if line.startswith('WD_BOOT '):
                    boot=fields(line); assert boot['watchdog']=='0' and boot['hz']=='125000000'
                    for k,v in (('heap_start','heap_start'),('heap_limit','heap_limit'),('stack_bottom','stack_bottom'),('stack_top','stack_top'),('recovery_start','recovery_start'),('recovery_end','recovery_end')): assert int(boot[k],16)==int(layout[v],16)
                elif line.startswith('WD_ABI '):
                    abi=fields(line); assert abi['id']=='4b39' and abi['abi']=='0.6' and abi['patterns']=='1200' and abi['height']=='240' and abi['error']=='00'
                elif line.startswith('WD_FRAME '):
                    f=fields(line); index=int(f['frame']); assert index==len(frames) and index<len(refs)
                    assert int(f['expected'],16)==int(f['actual'],16)==refs[index] and f['mismatch']=='0' and f['dirty']=='0'
                    frames.append(f)
                    # Frame zero is read back before display enable, so cannot
                    # be treated as a visible HDMI reference frame.
                    if index:
                        subprocess.run([os.environ.get('FFMPEG','ffmpeg'),'-hide_banner','-loglevel','error','-rtbufsize','512M','-f','dshow','-video_size','1280x960','-pixel_format','yuyv422','-framerate','60','-i','video=UGREEN 15390','-frames:v','20','-update','1',str(a.out/f'frame-{index}.png')],check=True,timeout=30)
                    s.write(b'n')
                elif line.startswith('WD_MEMORY '):
                    m=fields(line); memories.append(m)
                    assert m['live']=='0' and m['blocks']=='0' and m['owned']=='0' and m['allocs']==m['frees']
                elif line.startswith('WD_LATENCY '):latencies.append(fields(line))
                elif line.startswith('WD_GUARDS '):guards=fields(line)
                elif line.startswith('WD_STOP '):
                    assert line=='WD_STOP PASS recovery=BOOTSEL','firmware stopped with failure'
                    passed=True;break
        assert passed and len(frames)==7 and boot and abi and guards and len(latencies)==8
        assert guards['recovery_intact']=='1' and guards['bottom_canary_words']=='16' and int(guards['stack_peak_upper'])<49152 and int(guards['malloc_arena'])<=135168
        assert len(memories)==25 and sum(m['name']=='fresh' and m['status']=='0' for m in memories)==20
        for name,kind in (('limit','1'),('owned_oom','3'),('native_oom','2')):
            m=next(m for m in memories if m['name']==name); assert m['status']=='1' and m['oom']==kind
        (a.out/'measurements.json').write_text(json.dumps(dict(boot=boot,abi=abi,frames=frames,memories=memories,latencies=latencies,guards=guards),indent=2)+'\n')
    except BaseException as failure:
        log('HOST_FAILURE '+type(failure).__name__+': '+str(failure))
        raise
    finally:
        if programmed:
            # A normally completing harness enters ROM BOOTSEL itself. A
            # crashed image requires physical BOOTSEL; never claim restore
            # on timeout or failed readback.
            base.find_bootsel_drive(seconds=180)
            tool('info','-a')
            tool('load',restore,'-t','bin','-o','0x10000000','-v')
            got=dump('restored-full.bin'); assert got==original,'RESTORATION HASH MISMATCH'
            log('RESTORED_ROM_SHA256 '+sha(got)); tool('reboot')
            port=base.wait_port(a.expected_serial); assert port; time.sleep(4)
            h,c=base.flash_hash(port,True); assert h==sha(original) and c==base.CONSOLE_OK
            log('RESTORED_MICROPYTHON_SHA256 '+h+' console='+c)
            # Hash reading pauses HDMI. Resume the original console, with no
            # flash filesystem changes, after full readback verification.
            base.micropython_exec(port,'kagura_console.resume()\nprint("KAGURA Wren validation: MicroPython restored")\n')
    log('HARDWARE_VALIDATION_PASS restored_and_verified' if passed else 'HARDWARE_VALIDATION_INCOMPLETE')
if __name__=='__main__':main()
