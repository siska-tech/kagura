"""Publish whitelisted test evidence, never device flash/filesystem images."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
p=argparse.ArgumentParser(); p.add_argument('backup',type=Path); p.add_argument('run',type=Path); p.add_argument('out',type=Path); a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
original=a.backup.read_bytes(); manifest=json.loads((a.run/'manifest.json').read_text())
assert len(original)==2097152 and sha(original)==manifest['backup_sha256']
length=int(manifest['firmware_region'][1],16)-0x10000000
program=(a.run/'firmware-prefix.bin').read_bytes(); assert len(program)==length
expected=program+original[length:]
verification=dict(region=manifest['firmware_region'],backup_sha256=sha(original),bytes=2097152,stages={})
for name,want in (('before-bootsel.bin',original),('programmed-full.bin',expected),('restored-full.bin',original)):
    data=(a.run/name).read_bytes(); assert data==want
    verification['stages'][name]=dict(sha256=sha(data),matches_expected=True,unchanged_tail_sha256=sha(data[length:]))
raw=(a.run/'hardware.log').read_text(encoding='utf-8')
assert 'HARDWARE_VALIDATION_PASS restored_and_verified' in raw
assert 'RESTORED_MICROPYTHON_SHA256 '+sha(original) in raw
verification['micropython_rehash_and_console_pass']=True
(a.out/'flash-verification.json').write_text(json.dumps(verification,indent=2)+'\n')
raw=re.sub(r'flash id:\s*0x[0-9a-fA-F]+','flash id: [redacted]',raw)
(a.out/'device-log.txt').write_text('\n'.join(s.rstrip() for s in raw.splitlines()).rstrip()+'\n',encoding='utf-8')
for name in ('manifest.json','measurements.json'):
    shutil.copyfile(a.run/name,a.out/name)
for name in ('compare.md',):
    s=(a.run/name).read_text(encoding='utf-8'); (a.out/'hdmi-compare.md').write_text(s.rstrip()+'\n',encoding='utf-8')
for i in range(1,7):shutil.copyfile(a.run/f'frame-{i}.png',a.out/f'frame-{i}.png')
print('Published complete hardware results; all 2 MiB restoration checks passed; flash images excluded')
