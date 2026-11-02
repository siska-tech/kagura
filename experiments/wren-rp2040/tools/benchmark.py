#!/usr/bin/env python3
"""Record raw host budget sweeps, timing medians, exact observed minimums."""
import json
import pathlib
import platform
import statistics
import subprocess
import sys

r = pathlib.Path(__file__).resolve().parents[1]
exe = pathlib.Path(sys.argv[1]).resolve()
out = r / 'results'
out.mkdir(exist_ok=True)
def invoke(budget, cycles=1):
    p = subprocess.run([str(exe), str(budget), str(cycles)], capture_output=True, text=True, encoding='utf-8')
    assert p.returncode in (0, 1), (p.returncode, p.stdout, p.stderr)
    rows = [dict(x.split('=',1) for x in line.split()[1:]) for line in p.stdout.splitlines() if line.startswith('RESULT ')]
    assert len(rows) == cycles*10
    return p.stdout, rows

allrows = []
for kib in (32, 64, 96, 128, 160, 192, 256):
    raw, rows = invoke(kib*1024, 5)
    (out / ('host-%dk.txt' % kib)).write_text(raw, encoding='utf-8')
    allrows += rows
minimums = {}
for name in [row['name'] for row in allrows[:10]]:
    lo, hi = 1, 262144
    while lo < hi:
        mid = (lo+hi)//2
        _, rows = invoke(mid)
        row = next(row for row in rows if row['name'] == name)
        if row['status'] == 'PASS': hi = mid
        else: lo = mid+1
    minimums[name] = lo
summary = dict(platform=platform.platform(), minimum_requested_budget_bytes=minimums,
               note='Host x86-64 only; minimum excludes malloc and instrumentation metadata, native stack, static image; fixed GC policy. Timing includes automatic GC, excludes explicit GC.')
(out/'host-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
lines = ['| workload | mean call us (median of 5 runs) | peak VM bytes | peak + headers | timed allocations/call | timed reallocations/call | compile us | explicit GC us/collection |',
         '|---|---:|---:|---:|---:|---:|---:|---:|']
for name in minimums:
    rs = [row for row in allrows if row['name']==name and row['budget']=='262144']
    med = lambda key: statistics.median(float(row[key]) for row in rs)
    lines.append('| %s | %.3f | %d | %d | %.1f | %.1f | %.1f | %.3f |' % (name,med('run_us')/8,med('peak'),med('physical_peak'),med('run_allocs')/8,med('run_reallocs')/8,med('compile_us'),med('explicit_gc_us')/med('explicit_gc_count')))
(out/'host-table.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(summary, indent=2))
