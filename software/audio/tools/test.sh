#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Tests of the audio HAL, the KSNG format and player and kagura_audio, from
# the repository root (WSL/Linux):
#   1. host build under ASan/UBSan: HAL against a model of the FPGA's commit
#      semantics, the parser (malformed files, truncations, corruption), the
#      player (exact tick times, flow, effects, envelopes) and their mutants;
#   2. the unix MicroPython port with kagura_audio (tools/build-micropython-unix.sh);
#   3. tests/test_binding.py on it;
#   4. tools/make_fixtures.py writes songs/click.ksn again: it must equal the
#      committed file (and its C header).
# The music tracker and its fixture songs/demo.ksn are tested in kagura-desktop.
#   bash software/audio/tools/test.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="${OUT:-$ROOT/build/audio}"
cmake -S "$ROOT/software/audio" -B "$OUT" -DCMAKE_BUILD_TYPE=Debug >/dev/null
cmake --build "$OUT" -j"$(nproc)" >/dev/null
ctest --test-dir "$OUT" --output-on-failure
MP="$(bash "$ROOT/tools/build-micropython-unix.sh")"
MICROPYPATH="$ROOT/software/micropython" "$MP" "$ROOT/software/audio/tests/test_binding.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SONGS="$ROOT/software/audio/songs"
MICROPYPATH="$ROOT/software/micropython" "$MP" "$ROOT/software/audio/tools/make_fixtures.py" "$TMP" >/dev/null
cmp "$TMP/click.ksn" "$SONGS/click.ksn"
cmp "$TMP/click.h" "$SONGS/click.h"
echo "audio: all tests passed"
