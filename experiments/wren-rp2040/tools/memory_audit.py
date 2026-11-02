#!/usr/bin/env python3
"""CPU-only newlib footprint/phase/GUI acceptance audit; no device access."""
import json
import os
from pathlib import Path
import subprocess
r = Path(__file__).resolve().parents[1]
out = r/'results/memory-audit'
out.mkdir(exist_ok=True)
qemu = os.environ.get('QEMU', 'qemu-arm')
exe = r/'build-arm-memory/wren_memory.elf'
names = ['hello','arithmetic','strings','collections','objects','fibers','foreign','sprite16','events','repeat_gc','small_gui']

def invoke(budget=262144, checks=False, name='small_gui', limit=524288, cycles=1, recovery=None):
    args = [qemu,str(exe),str(budget),'checks' if checks else 'plain',name,str(limit),str(cycles)]
    if recovery: args.append(recovery)
    p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8')
    assert p.returncode in (0,1), (args,p.returncode,p.stdout,p.stderr)
    parsed = {}
    for line in p.stdout.splitlines():
        key, _, rest = line.partition(' ')
        if key in ('RESULT','AUDIT','PHASE','ARM_MALLOC'):
            parsed.setdefault(key,[]).append(dict(token.split('=',1) for token in rest.split()))
    assert len(parsed.get('RESULT',[])) == cycles + bool(recovery)
    assert all(row['shutdown']=='0' and row['allocs']==row['frees'] for row in parsed['RESULT'])
    return p.stdout, parsed, p.returncode

summary = {}
for name in names:
    raw, rows, status = invoke(name=name)
    assert status == 0
    (out/f'arm-{name}.txt').write_text(raw, encoding='utf-8')
    summary[name] = rows

minima = {}
for checks, cycles in [(False,1),(True,20)]:
    key = 'checked_20_lifecycles' if checks else 'single_gui'
    entry = {}
    for variable in ('budget','limit'):
        lo, hi = 1, 262144
        while lo < hi:
            mid = (lo+hi)//2
            _, _, status = invoke(checks=checks,cycles=cycles,**{variable:mid})
            if status == 0: hi = mid
            else: lo = mid+1
        entry[variable] = lo
    minima[key] = entry

for limit in (96064,104256,114688,122880,131072,135168):
    raw, _, _ = invoke(budget=98304,checks=True,limit=limit,cycles=20)
    (out/f'gui-arena-{limit}.txt').write_text(raw, encoding='utf-8')
for mode in (None,'budget-recovery','malloc-recovery'):
    raw, rows, status = invoke(budget=98304,checks=True,limit=131072,cycles=100,recovery=mode)
    assert status == 0
    assert all(row['status']=='PASS' for row in rows['RESULT'][bool(mode):])
    if mode:
        assert rows['RESULT'][0]['status']=='OOM_DISCARDED'
        assert rows['RESULT'][0]['oom_kind']==('malloc' if mode=='malloc-recovery' else 'budget')
    (out/f'gui-{mode or "100-lifecycles"}.txt').write_text(raw, encoding='utf-8')

(out/'summary.json').write_text(json.dumps(dict(kind='ARM CPU emulation, not RP2040 runtime measurements',workloads=summary,gui_minima=minima),indent=2)+'\n')
print(json.dumps(minima,indent=2))
lines = ['| workload | init live | compile peak | execution peak | GC peak | final GC live | shutdown | arena high-water | C stack paint upper |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for name, data in summary.items():
    phases = {row['phase']:row for row in data['PHASE']}
    result = data['RESULT'][0]; malloc = data['ARM_MALLOC'][0]
    lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (name,result['init'],phases['compile']['peak'],phases['call']['peak'],phases['gc']['peak'],result['after_gc'],result['shutdown'],malloc['arena_high_water'],malloc['stack_painted_upper']))
(out/'phase-table.md').write_text('\n'.join(lines)+'\n')
