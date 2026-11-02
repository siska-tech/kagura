#!/usr/bin/env python3
"""Acquire an exact official Wren tree; verify all source bytes before builds."""
import hashlib
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
REV = '99d2f0b8fc2686134b32b18166e037639f7e9f2c'
DEST = ROOT / 'vendor/wren'
if not DEST.exists():
    subprocess.run(['git', 'clone', '--config', 'core.autocrlf=false', 'https://github.com/wren-lang/wren.git', str(DEST)], check=True)
subprocess.run(['git', '-C', str(DEST), 'checkout', '--detach', REV], check=True)
assert subprocess.check_output(['git', '-C', str(DEST), 'rev-parse', 'HEAD'], text=True).strip() == REV
for line in (ROOT / 'upstream.sha256').read_text().splitlines():
    digest, name = line.split('  ', 1)
    assert hashlib.sha256((DEST / name).read_bytes()).hexdigest() == digest, name
print('Verified Wren', REV, '(MIT)')
