#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Tests of the native desktop library, from the repository root (WSL/Linux):
#   1. host build: text engine (UTF-8, all Misaki glyphs), kdm and 7 mutants;
#   2. the unix MicroPython port with the kagura_desktop module;
#   3. tests/test_binding.py on it (API, lifetimes, GC, errors, Japanese),
#      tests/test_session.py (kagura.desktop against a recording device) and
#      the Japanese desktop demo (examples/desktop_ja.py) without hardware.
#   bash software/desktop/tools/test.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="${OUT:-$ROOT/build/desktop}"
cmake -S "$ROOT/software/desktop" -B "$OUT" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$OUT" -j"$(nproc)" >/dev/null
ctest --test-dir "$OUT" --output-on-failure
MP="$(bash "$ROOT/software/desktop/tools/build_unix.sh")"
"$MP" "$ROOT/software/desktop/tests/test_binding.py"
MICROPYPATH="$ROOT/software/micropython" "$MP" "$ROOT/software/desktop/tests/test_session.py"
"$MP" "$ROOT/software/micropython/examples/desktop_ja.py" --host
