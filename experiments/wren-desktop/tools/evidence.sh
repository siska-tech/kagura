#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cp build-pico/wren_desktop_flash.map results/flash-linker.map
arm-none-eabi-readelf -lSW build-pico/wren_desktop_flash.elf >results/flash-readelf.txt
arm-none-eabi-nm -S --size-sort build-pico/wren_desktop_flash.elf >results/flash-symbols.txt
python3 - <<'PY'
from pathlib import Path
lines=[]
for p in Path('build-pico').rglob('*.su'):
    for line in p.read_text().splitlines():
        parts=line.split('\t')
        if len(parts)>1 and parts[1].isdigit(): lines.append((int(parts[1]),line))
Path('results/stack-frames.txt').write_text('\n'.join(x[1] for x in sorted(lines,reverse=True)[:40])+'\n')
for name in ('flash-linker.map','flash-readelf.txt'):
    p=Path('results')/name
    p.write_text('\n'.join(line.rstrip() for line in p.read_text().splitlines()).rstrip()+'\n')
PY
python3 tools/analyze_elf.py build-pico/wren_desktop_flash.elf >results/flash-layout.json
python3 tools/verify_inputs.py
