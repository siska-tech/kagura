#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Stage 3A checks, from the repository root in WSL/Linux:
#   1. native: kdm tests and 7 kdm mutants (each must fail), C reference;
#   2. the unix MicroPython build with kagura_desktop;
#   3. demo/demo.py on MicroPython must print exactly what the native C
#      reference (tests/ref_demo.c, kd_app.h only) prints: per step the
#      framebuffer CRC, the TILE4 mirror CRC and the tiles exported;
#   4. tests/test_binding.py (API, lifetimes, GC, atomic failures, heap lock).
#   bash experiments/c-gem-desktop/micropython/tools/run_tests.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
EXP="$ROOT/experiments/c-gem-desktop/micropython"
OUT="${OUT:-$ROOT/build/c-gem-mp}"
cmake -S "$EXP" -B "$OUT" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$OUT" -j"$(nproc)" >/dev/null
ctest --test-dir "$OUT" --output-on-failure
MP="$(bash "$EXP/tools/build_unix.sh")"
"$OUT/kd_ref_demo" > "$OUT/ref_demo.txt"
"$MP" "$EXP/demo/demo.py" > "$OUT/mp_demo.txt"
if diff "$OUT/ref_demo.txt" "$OUT/mp_demo.txt"; then
    echo "demo: MicroPython equals the native C reference ($(wc -l < "$OUT/ref_demo.txt") steps)"
else
    echo "demo: MISMATCH" >&2
    exit 1
fi
"$MP" "$EXP/tests/test_binding.py"
