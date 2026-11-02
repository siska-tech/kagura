#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Host benchmarks of stage 3A, three runs each (the report uses the median
# of the three means per workload):
#   kdm_bench          pure C through kdm
#   bench_binding.py   the same workloads from MicroPython (unix port)
#   kagura_ui_reference.py --backend framebuf   KAGURA-UI on the same binary
# Run tools/run_tests.sh first (it builds both). From the repository root:
#   bash experiments/c-gem-desktop/micropython/tools/run_bench.sh [OUT_DIR]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
EXP="$ROOT/experiments/c-gem-desktop/micropython"
OUT="${1:-$ROOT/build/c-gem-mp/bench}"
MP="$ROOT/build/micropython-src/ports/unix/build-kagura-desktop/micropython"
mkdir -p "$OUT"
for run in 1 2 3; do
    "$ROOT/build/c-gem-mp/kdm_bench" > "$OUT/native-$run.md"
    "$MP" "$EXP/bench/bench_binding.py" > "$OUT/binding-$run.md"
    (cd "$ROOT" && MICROPYPATH=software/micropython:software/micropython/examples \
        "$MP" experiments/c-gem-desktop/bench/kagura_ui_reference.py --backend framebuf --samples 101 \
        > "$OUT/kagura-ui-$run.md")
done
python3 -I - "$OUT" <<'PY'
import sys, glob, statistics
out = sys.argv[1]
def table(path, col):
    rows = {}
    for line in open(path):
        f = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(f) > col and f[0] and not f[0].startswith('-') and f[0] != 'workload':
            try:
                rows[f[0]] = float(f[col].replace(',', ''))
            except ValueError:
                pass
    return rows
def median(kind, col):
    runs = [table(p, col) for p in sorted(glob.glob('%s/%s-*.md' % (out, kind)))]
    return {k: statistics.median(r[k] for r in runs) for k in runs[0]}
nat, mp, ui = median('native', 1), median('binding', 1), median('kagura-ui', 1)
print('| workload | C through kdm, mean us | MicroPython + binding, mean us | difference us | ratio |')
print('|---|---:|---:|---:|---:|')
for k, v in mp.items():
    c = nat.get('events_3' if k == 'events_3_poll_into' else k)
    if c is not None:
        print('| %s | %.2f | %.2f | %.2f | %.2f |' % (k, c, v, v - c, v / c if c else 0))
print()
print('KAGURA-UI framebuf p50 us (median of runs): ' + ', '.join('%s %.0f' % kv for kv in ui.items()))
PY
