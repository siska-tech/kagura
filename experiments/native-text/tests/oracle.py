"""Independent CPython strict-UTF8 oracle and every source KJ8F glyph."""
from pathlib import Path
import random
import struct
import subprocess
import sys
exe=sys.argv[1]
rng=random.Random(0x4b414755)
samples=[bytes((a,b)) for a in range(256) for b in range(256)]
samples += [bytes(rng.randrange(256) for _ in range(rng.randrange(1,9))) for _ in range(20000)]
samples += [chr(c).encode() for c in (0,0x7f,0x80,0x7ff,0x800,0xd7ff,0xe000,0xffff,0x10000,0x10ffff,0x795e)]
out=subprocess.run([exe],input=''.join(s.hex()+'\n' for s in samples),text=True,capture_output=True,check=True).stdout.splitlines()
assert len(out)==len(samples)
for raw,line in zip(samples,out):
    want=(0,1,0xfffd)
    for n in range(1,min(4,len(raw))+1):
        try:s=raw[:n].decode('utf-8','strict')
        except UnicodeDecodeError:continue
        if len(s)==1:want=(1,n,ord(s));break
    valid,used,cp=line.split();assert (int(valid),int(used),int(cp,16))==want,(raw,line,want)
source=Path(__file__).resolve().parents[3]/'software/micropython/fonts/misaki8.kfnt'
data=source.read_bytes(); count=struct.unpack_from('<H',data,6)[0]
glyphs=subprocess.run([exe,'glyphs'],capture_output=True,text=True,check=True).stdout.splitlines()
assert len(glyphs)==count==7171
for i,line in enumerate(glyphs):
    code,rows=line.split(); cp=struct.unpack_from('<H',data,8+i*10)[0]
    assert int(code,16)==cp and bytes.fromhex(rows)==data[10+i*10:18+i*10]
print(f'ORACLE_PASS {len(samples)} strict UTF8 cases; all {count} source glyphs byte-exact')
