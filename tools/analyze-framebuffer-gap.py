# SPDX-License-Identifier: Apache-2.0
"""Compare fresh controls with opt-in gap merging and DMA512 on the device."""
import argparse
import ast
import hashlib
import inspect
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log', type=Path, required=True)
    p.add_argument('--restore-log', type=Path, required=True)
    p.add_argument('--console-log', type=Path, required=True)
    p.add_argument('--workload', type=Path, required=True)
    p.add_argument('--output', type=Path, default=Path('docs/framebuffer-gap-results.json'))
    a = p.parse_args()
    records = []
    config = None
    session_closed = False
    for path in (a.log, a.restore_log, a.console_log):
        raw = path.read_bytes()
        for line in raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig').splitlines():
            if line == 'GAP_SESSION_CLOSED':
                session_closed = True
            if line.startswith('TILEFB '):
                r = json.loads(line[7:])
                if r['event'] == 'gap_config':
                    config = dict(chunk=r['chunk'], max_gap=r['max_gap'])
                if r['event'] == 'transport_scene':
                    r['config'] = config.copy()
                r['acquisition_log'] = path.as_posix()
                records.append(r)
    micro = [r for r in records if r['event'] == 'gap_micro']
    scenes = [r for r in records if r['event'] == 'transport_scene']
    comparisons = []
    for collection, field in ((micro, 'case'), (scenes, 'scene')):
        controls = {r[field]: r for r in collection if
                    (r.get('config', r)['chunk'], r.get('config', r)['max_gap']) == (128, 0)}
        for r in collection:
            c = r.get('config', r)
            base = controls[r[field]]
            if field == 'case':
                before, after = base['timing']['mean_us'], r['timing']['mean_us']
            else:
                before, after = base['timing']['flush']['mean_us'], r['timing']['flush']['mean_us']
            comparisons.append(dict(kind=field, name=r[field], config=c if field == 'scene' else
                dict(chunk=c['chunk'], max_gap=c['max_gap']), control_flush_mean_us=before,
                flush_mean_us=after, flush_reduction_percent=(before-after)/before*100,
                flush_speedup=before/after, application_updates_s=r.get('application_updates_s')))
    configs = {(r['chunk'], r['max_gap']) for r in records if r['event'] == 'gap_config_complete'}
    complete = (session_closed and configs == {(128, 0), (128, 1), (512, 1)} and len(micro) == 18 and
                len(scenes) == 12 and any(r['event'] == 'gap_complete' for r in records) and
                any(r['event'] == 'readback_pass' and r.get('full') for r in records) and
                any(r['event'] == 'transport_boot_bytes_restored' and r['sha256'] == r['expected_sha256'] for r in records) and
                any(r['event'] == 'transport_console_restored' and r['console_active'] and r['error'] == 0 for r in records))
    for r in records:
        if 'telemetry' in r:
            assert r['telemetry']['error'] == 0 and r['telemetry']['fifo'] & 6 == 0
            assert all(s & 2 and not s & 0x78 for s in r['telemetry']['pcm'])
    sources = ['software/micropython/kagura/framebuffer.py',
               'software/micropython/examples/framebuffer_transport_benchmark.py',
               'software/micropython/examples/framebuffer_gap_benchmark.py']
    def methods(path, name):
        tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
        # Extraction reindents methods into a subclass; normalize docstring
        # whitespace while comparing every executable node unchanged.
        for n in cls.body:
            if isinstance(n, ast.FunctionDef) and ast.get_docstring(n) is not None:
                n.body[0].value.value = inspect.cleandoc(n.body[0].value.value)
        return {n.name: ast.dump(n, include_attributes=False) for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name in ('flush', '_flush')}
    assert methods(sources[0], 'TileFramebuffer') == methods(a.workload, 'GapFramebuffer'), 'RAM candidate differs from SDK methods'
    def identity(path):
        path = Path(path)
        return dict(path=path.as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    result = dict(status='complete' if complete else 'partial',
        conditions=dict(repetitions=30, warmup=3, cpu_hz=125000000, qspi_baudrate=5000000,
            abi=[0, 6], framebuffer=[320, 240, 4], micropython='v1.26.0-1.g3069c562f',
            renderer='Viper', pcm='2ch looping PSRAM playback; not host streaming',
            control='Fresh max_gap=0/chunk128 in the same VM, SDK, stimulus and observer',
            deployment='RAM subclass containing exact SDK flush/_flush methods over SHA-verified isolated baseline SDK; files unchanged'),
        candidate_methods_match_sdk=True,
        artifacts=[identity(path) for path in (a.log, a.restore_log, a.console_log, a.workload)],
        sources=[identity(path) for path in sources], measurements=records, comparisons=comparisons,
        physical_hdmi_updates_hz=None, busy_pin_time_us=None,
        limits=['Sequential option order, no randomized crossover',
                'N=30 is not a rare-fault endurance or streaming fairness test',
                'Scene D uses the documented scroll/wrap workload, not independent source D'])
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(a.output, result['status'])


if __name__ == '__main__':
    main()
