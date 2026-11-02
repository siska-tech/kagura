"""Static ELF audit only. Reuses all protected reference assertions unchanged."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

r = Path(__file__).resolve().parents[1]
repo = r.parents[1]
out = r / 'results'
out.mkdir(exist_ok=True)
elf = r / 'build-pico/wren_desktop_flash.elf'
checker = repo / 'experiments/wren-desktop/tools/analyze_elf.py'
sys.argv = [str(checker), str(elf)]
scope = {}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(checker.read_text(), str(checker), 'exec'), scope)
layout, symbols = scope['result'], scope['symbols']
font, descriptor = symbols['font_bytes'], symbols['kj_misaki8']
assert font['size'] == 71718 and 0x10000000 <= font['address'] < font['address'] + font['size'] <= 0x10200000
assert descriptor['size'] == 24 and 0x10000000 <= descriptor['address'] < 0x10200000
assert layout['desktop_state']['size'] == 34284
rom = sum(h['filesz'] for h in layout['headers'] if 0x10000000 <= int(h['paddr'], 16) < 0x10200000)
baseline = json.loads((repo / 'experiments/wren-japanese-desktop/results/flash-layout.json').read_text())
assert (baseline['ROM_bytes'], baseline['static_sram'], baseline['total_unassigned']) == (227480, 45596, 32228)
layout.update(ROM_bytes=rom, font_flash=font, font_descriptor_flash=descriptor,
              baseline_PR72=dict(ROM_bytes=227480, static_sram=45596, total_unassigned=32228),
              delta_PR72=dict(ROM_bytes=rom - 227480, static_sram=layout['static_sram'] - 45596,
                              total_unassigned=layout['total_unassigned'] - 32228),
              estimate_stage5_delta=dict(ROM_bytes=0, static_sram=0, reserved_arena=0, reserved_stack=0, recovery=0))
# Remove the older #70 pre-integration estimate; it is not the Stage 5 estimate.
for field in ('estimated_native_integration', 'difference_from_estimate'):
    layout.pop(field)
layout['main_word_interleaved_banks'] = [dict(bank=i, unassigned=0) for i in range(4)]
for address in range(int(layout['heap_limit'], 16), int(layout['recovery_start'], 16), 4):
    layout['main_word_interleaved_banks'][((address - 0x20000000) // 4) % 4]['unassigned'] += 4
# Include every named static SRAM object and writable section. Linker padding,
# anonymous allocations and SDK ownership are resolved by the complete map.
layout['static_objects'] = [dict(name=name, **value) for name, value in sorted(symbols.items(), key=lambda pair: pair[1]['address'])
                            if value['size'] and value['type'] == 1 and 0x20000000 <= value['address'] < int(layout['heap_start'], 16)]
layout['expected_protected_baseline'] = dict(allocator_capacity=135168, stack_reserved=49152, recovery_reserved=8192)
assert all(layout[key] == value for key, value in layout['expected_protected_baseline'].items())
shutil.copyfile(r / 'build-pico/wren_desktop_flash.map', out / 'flash-linker.map')
shutil.copyfile(r / 'build-pico/integration_flash.ld', out / 'integration_flash.ld')
for name, args in [('flash-readelf.txt', ['arm-none-eabi-readelf', '-lWS', str(elf)]),
                   ('flash-symbols.txt', ['arm-none-eabi-nm', '-S', '--size-sort', str(elf)])]:
    if not shutil.which(args[0]):
        args[0] = str(Path.home() / 'opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin' / args[0])
    (out / name).write_text(subprocess.check_output(args, text=True))
(out / 'flash-layout.json').write_text(json.dumps(layout, indent=2) + '\n')
frames = []
for f in sorted((r / 'build-pico').rglob('*.su')):
    for line in f.read_text().splitlines():
        frames.append(line)
(out / 'stack-frames.txt').write_text('\n'.join(frames) + '\n')
print(json.dumps({key: layout[key] for key in ('elf_sha256', 'ROM_bytes', 'static_sram', 'allocator_capacity', 'stack_reserved', 'recovery_reserved', 'total_unassigned', 'delta_PR72')}, indent=2))
