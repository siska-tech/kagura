"""Compare actual reference and consolidated pixels/traces; no rewritten goldens."""
import hashlib
import json
from pathlib import Path
import subprocess

r = Path(__file__).resolve().parents[1]
reference = r / 'build-reference-wren-japanese-desktop-Release'
current = r / 'build-Release'
def trace(root):
    raw = subprocess.check_output([str(root / 'japanese_tests')], text=True)
    return [line for line in raw.splitlines() if line.startswith(('JP_CRC ', 'CRC '))]
a, b = trace(reference), trace(current)
assert a and a == b, (a, b)
baseline = json.loads((r / 'tests/pr73-baseline.json').read_text())
assert a == baseline['host']['crc_trace'], 'CRC differs from the retained PR #73 baseline'
images = {}
for directory in ('wren-frames', 'native-frames'):
    files = sorted((reference / directory).glob('*.pgm'))
    assert len(files) == 7
    assert [f.name for f in files] == sorted(f.name for f in (current / directory).glob('*.pgm'))
    for f in files:
        data = f.read_bytes()
        assert data == (current / directory / f.name).read_bytes(), f
        images[f'{directory}/{f.name}'] = hashlib.sha256(data).hexdigest()
assert images == baseline['host']['frame_sha256'], 'Pixels differ from PR #73'
native_ref = r / 'build-reference-native-text-Release/demo'
native_current = current / 'native-demo'
native_files = sorted(f for f in native_ref.rglob('*') if f.is_file())
assert native_files
for f in native_files:
    relative = f.relative_to(native_ref)
    assert f.read_bytes() == (native_current / relative).read_bytes(), relative
# The facade's generated application must remain byte-identical to the reference.
repo = r.parents[1]
assert (current / 'japanese_app_source.h').read_bytes() == (repo / 'experiments/wren-japanese-desktop/src/japanese_app_source.h').read_bytes()
symbols = subprocess.check_output(['nm', '-u', str(r / 'build-native-only/libdesktop_native.a'),
                                  str(r / 'build-native-only/libdesktop_text.a'),
                                  str(r / 'build-native-only/libdesktop_application_host.a')], text=True)
assert not any(prefix in symbols for prefix in ('wren', 'mp_', 'malloc', 'realloc', 'free'))
assert not (r / 'build-native-only/libwren_vm.a').exists()
native_trace = subprocess.check_output([str(r / 'build-native-only/native_application')], text=True)
native_crcs = [dict(part.split('=', 1) for part in line.split()[1:])['crc']
               for line in native_trace.splitlines() if line.startswith('NATIVE_CRC ')]
reference_crcs = [dict(part.split('=', 1) for part in line.split()[1:])['crc']
                  for line in a if line.startswith('JP_CRC cover=0 ')]
assert len(native_crcs) == 7 and native_crcs == reference_crcs, (native_crcs, reference_crcs)
result = dict(kind='host equivalence, not physical hardware acceptance',
              crc_trace=a, frame_sha256=images, native_demo_files=len(native_files),
              native_without_runtime_or_allocator=True, generated_app_identical=True,
              baseline_PR73=baseline['commit'], baseline_PR73_matches=True)
(r / 'results/equivalence.json').write_text(json.dumps(result, indent=2) + '\n')
print('Reference/consolidated CRC and pixels match; runtime-free native build verified')
