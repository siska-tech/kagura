import json
from pathlib import Path
import subprocess
r=Path(__file__).resolve().parents[1]
raw=subprocess.run([str(r/'build-host/japanese_tests')],capture_output=True,text=True,check=True).stdout
(r/'results/japanese-trace.txt').write_text(raw,encoding='utf-8')
def read(text):
    cases={'0':[],'1':[]}
    for line in text.splitlines():
        if not line.startswith('JP_CRC '):continue
        d=dict(s.split('=') for s in line.split()[1:]); assert int(d['frame'])==len(cases[d['cover']])
        cases[d['cover']].append(d['crc'])
    assert len(cases['0'])==7 and len(cases['1'])==10
    return cases
golden=read(raw)
assert golden==read((r/'results/arm-correctness.txt').read_text(encoding='utf-8'))
for i in range(7):
    assert (r/f'build-host/wren-frames/frame-{i}.pgm').read_bytes()==(r/f'build-host/native-frames/frame-{i}.pgm').read_bytes()
(r/'results/goldens.json').write_text(json.dumps(dict(kind='native C = Wren = ARM emulation, all frames',cases=golden),indent=2)+'\n')
print('All native/Wren/ARM CRCs agree; seven streaming reference images byte-identical')
