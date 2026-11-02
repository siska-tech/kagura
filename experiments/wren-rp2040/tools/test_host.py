#!/usr/bin/env python3
import subprocess
import sys

exe = sys.argv[1]
def run(budget, cycles=1, checks=False):
    p = subprocess.run([exe, str(budget), str(cycles)] + (['checks'] if checks else []), capture_output=True, text=True, encoding='utf-8')
    assert p.returncode in (0, 1), (p.returncode, p.stdout, p.stderr)
    rows = [dict(pair.split('=', 1) for pair in line.split()[1:]) for line in p.stdout.splitlines() if line.startswith('RESULT ')]
    assert len(rows) == cycles * 10, (p.stdout, p.stderr)
    assert all(row['shutdown'] == '0' for row in rows), rows
    assert all(int(row['allocs']) == int(row['frees']) for row in rows), rows
    return p, rows

# Deliberately fail during first VM allocation and later core initialization.
for budget in (1, 4096, 32768, 65536, 98304, 131072):
    p, rows = run(budget)
    assert all(r['status'] in ('PASS', 'OOM_DISCARDED') for r in rows)
p, rows = run(262144, 20, True)
assert all(r['status'] == 'PASS' for r in rows), p.stdout
assert 'Hello World\nこんにちは、神楽！\n' in p.stdout
assert 'expected failure' in p.stdout
assert all(int(r['foreign_calls']) == 10000 for r in rows if r['name'] == 'foreign')
p = subprocess.run([exe, '262144', '1', 'oom-recovery'], capture_output=True, text=True, encoding='utf-8')
assert p.returncode == 0, (p.stdout, p.stderr)
rows = [dict(pair.split('=',1) for pair in line.split()[1:]) for line in p.stdout.splitlines() if line.startswith('RESULT ')]
assert len(rows) == 20
assert all(row['status'] == 'OOM_DISCARDED' for row in rows[:10])
assert all(row['status'] == 'PASS' for row in rows[10:])
assert all(row['shutdown'] == '0' and row['allocs'] == row['frees'] for row in rows)
p = subprocess.run([exe, '262144', '20', 'checks', 'small_gui'], capture_output=True, text=True, encoding='utf-8')
assert p.returncode == 0, (p.stdout,p.stderr)
rows = [dict(pair.split('=',1) for pair in line.split()[1:]) for line in p.stdout.splitlines() if line.startswith('RESULT ')]
assert len(rows) == 20
assert all(row['status']=='PASS' and row['foreign_calls']=='40' and row['shutdown']=='0' and row['allocs']==row['frees'] for row in rows)
print('PASS: UTF-8, ten checksums, compiled callbacks, foreign calls, errors/recovery, 200 lifecycles, OOM cleanup and same-process restart')
