#!/usr/bin/env python3
"""Allocation-only CPU emulation, not hardware measurements."""
import json
import os
from pathlib import Path
import subprocess
r = Path(__file__).resolve().parents[1]
qemu = os.environ.get('QEMU', 'qemu-arm')
def run(budget):
    p = subprocess.run([qemu, str(r/'build-arm-memory/wren_memory.elf'), str(budget)], capture_output=True, text=True, encoding='utf-8')
    assert p.returncode in (0, 1), (p.returncode, p.stdout, p.stderr)
    rows = [dict(x.split('=',1) for x in line.split()[1:]) for line in p.stdout.splitlines() if line.startswith('RESULT ')]
    assert len(rows) == 10
    return p.stdout, rows
for kib in (32, 64, 96, 128, 160, 256):
    raw, _ = run(kib*1024)
    (r/'results'/('arm-emulated-%dk.txt'%kib)).write_text(raw, encoding='utf-8')
minimums = {}
_, rows = run(262144)
for name in [row['name'] for row in rows]:
    lo, hi = 1, 262144
    while lo < hi:
        mid = (lo+hi)//2
        _, rs = run(mid)
        row = next(row for row in rs if row['name'] == name)
        if row['status'] == 'PASS': hi = mid
        else: lo = mid+1
    minimums[name] = lo
(r/'results/arm-emulated-summary.json').write_text(json.dumps(dict(
    kind='ARMv6-M CPU emulation with newlib; NO RP2040 hardware or timing results',
    minimum_requested_budget_bytes=minimums), indent=2)+'\n')
print(minimums)
