#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Tests of the audio HAL, the KSNG format and player, kagura_audio and the
# music tracker, from the repository root (WSL/Linux):
#   1. host build under ASan/UBSan: HAL against a model of the FPGA's commit
#      semantics, the parser (malformed files, truncations, corruption), the
#      player (exact tick times, flow, effects, envelopes) and their mutants;
#   2. the unix MicroPython port with kagura_desktop and kagura_audio;
#   3. tests/test_binding.py and tests/test_tracker.py on it;
#   4. the tracker's scripted demo composes songs/demo.ksn again, and
#      tools/make_fixtures.py writes songs/click.ksn again: both must equal
#      the committed files (and their C headers).
#   bash software/audio/tools/test.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="${OUT:-$ROOT/build/audio}"
cmake -S "$ROOT/software/audio" -B "$OUT" -DCMAKE_BUILD_TYPE=Debug >/dev/null
cmake --build "$OUT" -j"$(nproc)" >/dev/null
ctest --test-dir "$OUT" --output-on-failure
MP="$(bash "$ROOT/software/desktop/tools/build_unix.sh")"
MICROPYPATH="$ROOT/software/micropython" "$MP" "$ROOT/software/audio/tests/test_binding.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
MICROPYPATH="$ROOT/software/micropython:$ROOT/software/micropython/examples" "$MP" \
    "$ROOT/software/audio/tests/test_tracker.py" "$TMP"
SONGS="$ROOT/software/audio/songs"
cmp "$TMP/demo/DEMO.KSN" "$SONGS/demo.ksn"
cmp "$TMP/demo/DEMO.H" "$SONGS/demo.h"
mkdir "$TMP/fixtures"
MICROPYPATH="$ROOT/software/micropython" "$MP" "$ROOT/software/audio/tools/make_fixtures.py" "$TMP/fixtures" >/dev/null
cmp "$TMP/fixtures/click.ksn" "$SONGS/click.ksn"
cmp "$TMP/fixtures/click.h" "$SONGS/click.h"
echo "audio: all tests passed"
