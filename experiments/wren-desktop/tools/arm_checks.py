#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
r=Path(__file__).resolve().parents[1]
out=r/'results';out.mkdir(exist_ok=True)
qemu=os.environ.get('QEMU','qemu-arm')
test=subprocess.run([qemu,str(r/'build-arm/integration_memory.elf'),'262144','135168','1','tests'],capture_output=True,text=True,encoding='utf-8')
(out/'arm-correctness.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
assert test.returncode==0 and 'INTEGRATION_PASS' in test.stdout,(test.returncode,test.stdout,test.stderr)
def run(budget=98304,capacity=135168,cycles=1,mode='normal'):
    p=subprocess.run([qemu,str(r/'build-arm/integration_memory.elf'),str(budget),str(capacity),str(cycles),mode],capture_output=True,text=True,encoding='utf-8')
    assert p.returncode in (0,1), (p.returncode,p.stdout,p.stderr)
    rows=[dict(part.split('=',1) for part in line.split()[1:]) for line in p.stdout.splitlines() if line.startswith('MEM ')]
    assert len(rows)==cycles+(mode in ('malloc-recovery','budget-recovery'))
    assert all(row['live']=='0' and row['blocks']=='0' and row['allocs']==row['frees'] for row in rows)
    arena=next(dict(part.split('=',1) for part in line.split()[1:]) for line in p.stdout.splitlines() if line.startswith('ARENA '))
    assert int(arena['high_water'])<=capacity
    return p.returncode,p.stdout,rows,arena
summary={}
for mode in ('normal','cover','malloc-recovery','budget-recovery'):
    status,raw,rows,arena=run(cycles=20,mode=mode)
    assert status==0
    successful=rows[-20:]
    assert all(row['status']=='0' and row['completed']=='10' and row['foreign']=='161' and int(row['collections'])>=61 for row in successful)
    assert 'こんにちは、神楽！\n' in raw
    if 'recovery' in mode:
        assert rows[0]['status']=='1' and rows[0]['oom']==('2' if mode=='malloc-recovery' else '1')
    (out/f'arm-{mode}.txt').write_text(raw,encoding='utf-8')
    summary[mode]=dict(peak=max(int(row['peak']) for row in successful),ledger_peak=max(int(row['ledger_peak']) for row in successful),arena=arena)
for budget in (1,32768,65536,90000,98304,131072):
    status,raw,_,_=run(budget=budget)
    (out/f'arm-cap-{budget}.txt').write_text(raw,encoding='utf-8')
for capacity in (96064,122880,135168):
    status,raw,_,_=run(capacity=capacity)
    (out/f'arm-arena-{capacity}.txt').write_text(raw,encoding='utf-8')
minimum={}
for variable in ('budget','capacity'):
    lo,hi=1,262144 if variable=='budget' else 135168
    while lo<hi:
        mid=(lo+hi)//2
        status,_,_,_=run(**{variable:mid})
        if status==0:hi=mid
        else:lo=mid+1
    minimum[variable]=lo
summary['minimum_fixed_binary']=minimum
(out/'arm-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
