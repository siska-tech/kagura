"""Require equal load addresses, memory sizes and bytes against a fresh #72 build."""
import hashlib
import json
from pathlib import Path
import struct

r = Path(__file__).resolve().parents[1]
repo = r.parents[1]
paths = [repo / 'experiments/wren-japanese-desktop/build-pico/wren_desktop_flash.elf',
         r / 'build-pico/wren_desktop_flash.elf']
def load(path):
    data = path.read_bytes()
    assert data[:7] == b'\x7fELF\x01\x01\x01'
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    segments = []
    for i in range(h[10]):
        kind, offset, va, pa, fs, ms, flags, alignment = struct.unpack_from('<8I', data, h[5] + i * h[9])
        if kind == 1:
            segments.append(dict(vaddr=hex(va), paddr=hex(pa), filesz=fs, memsz=ms,
                                 flags=flags, alignment=alignment,
                                 sha256=hashlib.sha256(data[offset:offset + fs]).hexdigest()))
    return dict(elf_sha256=hashlib.sha256(data).hexdigest(), entry=hex(h[4]), segments=segments)
reference, consolidated = map(load, paths)
assert reference['entry'] == consolidated['entry']
assert reference['segments'] == consolidated['segments'], (reference, consolidated)
result = dict(kind='fresh reference versus consolidated static load image; not hardware execution',
              reference=reference, consolidated=consolidated, load_images_equal=True)
(r / 'results/load-equivalence.json').write_text(json.dumps(result, indent=2) + '\n')
print('Every PT_LOAD address, reservation size and initialized byte matches the fresh reference')
