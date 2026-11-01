# SPDX-License-Identifier: Apache-2.0
"""Stream benchmark logs into a small summary; never average percentiles."""
import argparse
import json
from pathlib import Path


def summarize(lines):
    profiles = {}
    current = None
    restored = False
    cleanup = False
    started = False
    for line in lines:
        # A live log can end halfway through a record. A complete bad record
        # remains an error, rather than becoming evidence of successful work.
        if not line.endswith('\n'):
            continue
        if line.startswith('HOST_START '):
            if started:
                raise ValueError('multiple host runs; summarize each log separately')
            started = True
        elif line.startswith('UI_BENCH '):
            restored = cleanup = False
            value = json.loads(line.split(' ',1)[1])
            current = value.get('profile') or 'legacy'
            profile = profiles.setdefault(current,dict(workloads={},heap=None,finish=None))
            profile['finish'] = None
            workload = profile['workloads'].setdefault(value['workload'],dict(
                groups=0,samples=0,latency_samples=0,tiles=0,pattern_payload_bytes=0,
                frame_us_percentile_ranges=None,flush_us_percentile_ranges=None,
                synthetic_invalidate_us_percentile_ranges=None,
                first=value,last=value))
            workload['groups'] += 1
            workload['samples'] += value['samples']
            workload['latency_samples'] += value.get('latency_samples',0)
            for key in ('tiles','pattern_payload_bytes'):
                workload[key] += value[key]
            for source,target in (('frame_us_p50_p95_p99','frame_us_percentile_ranges'),
                                  ('flush_us_p50_p95_p99','flush_us_percentile_ranges'),
                                  ('synthetic_invalidate_us_p50_p95_p99','synthetic_invalidate_us_percentile_ranges')):
                values = value.get(source)
                if values is None:
                    continue
                if workload[target] is None:
                    workload[target] = [[v,v] for v in values]
                else:
                    for bounds,v in zip(workload[target],values):
                        bounds[0],bounds[1] = min(bounds[0],v),max(bounds[1],v)
            workload['last'] = value
        elif line.startswith('UI_HEAP '):
            value = json.loads(line.split(' ',1)[1])
            if current is None:
                raise ValueError('heap record before workload profile')
            free = value['free']
            heap = profiles[current]['heap']
            if heap is None:
                heap = dict(groups=0,first_free=free,last_free=free,min_free=free,max_free=free)
                profiles[current]['heap'] = heap
            heap['groups'] += 1
            heap['last_free'] = free
            if free is not None:
                heap['min_free'],heap['max_free'] = min(heap['min_free'],free),max(heap['max_free'],free)
            heap['last_cycle'] = value['cycle']
            heap['elapsed_ms'] = value.get('elapsed_ms')
        elif line.startswith('UI_FINISH '):
            value = json.loads(line.split(' ',1)[1])
            if current is None:
                raise ValueError('finish record before workload profile')
            profiles[current]['finish'] = value
        elif line.strip() == 'STANDARD_RESTORED False True':
            restored = True
        elif line.strip() == 'STANDARD_CLEANUP':
            cleanup = True
    return dict(profiles=profiles,console_restored=restored,cleanup_complete=cleanup,
                percentile_scope='min/max of per-group p50/p95/p99; not global percentiles',
                allocation_count=None,gc_count=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    parser.add_argument('--require-seconds',type=int)
    args = parser.parse_args()
    if args.require_seconds is not None and not 0 <= args.require_seconds <= 86400:
        parser.error('require-seconds must be 0..86400')
    with args.log.open(encoding='utf8') as source:
        result = summarize(source)
    print(json.dumps(result,indent=2))
    if args.require_seconds is not None:
        finish = result['profiles'].get('glyph8',{}).get('finish')
        if (not finish or finish.get('elapsed_ms',0) < args.require_seconds*1000 or
                not result['console_restored'] or not result['cleanup_complete']):
            raise SystemExit('measurement incomplete or console not restored')


if __name__ == '__main__':
    main()
