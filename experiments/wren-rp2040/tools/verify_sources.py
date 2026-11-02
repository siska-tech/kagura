#!/usr/bin/env python3
import hashlib
from pathlib import Path
r = Path(__file__).resolve().parents[1]
for line in (r/'upstream.sha256').read_text().splitlines():
    digest, name = line.split('  ', 1)
    assert hashlib.sha256((r/'vendor/wren'/name).read_bytes()).hexdigest() == digest, name
print('Pinned Wren source and MIT license hashes verified')
