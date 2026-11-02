#!/usr/bin/env bash
# Offline only. Historic suites remain authoritative; do not edit their goldens.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p results
run_suite() {
  local source="$1" out="$2" mode="$3"
  local flags=()
  if [ "$mode" = Debug ]; then
    flags=(-DCMAKE_C_FLAGS=-fsanitize=address,undefined\ -fno-omit-frame-pointer -DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined)
  fi
  cmake -S "$source" -B "$out" -DCMAKE_BUILD_TYPE="$mode" -DKD_SDL=OFF "${flags[@]}" >"$out-configure.log" 2>&1
  cmake --build "$out" -j4 >"$out-build.log" 2>&1
  ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 \
    ctest --test-dir "$out" --output-on-failure >"results/$(basename "$out")-tests.txt" 2>&1
}
for mode in Release Debug; do
  run_suite . "build-$mode" "$mode"
  for suite in wren-desktop native-text wren-japanese-desktop wren-rp2040; do
    run_suite "../../experiments/$suite" "build-reference-$suite-$mode" "$mode"
  done
done
# Verify that the native build does not even configure or compile the VM.
cmake -S . -B build-native-only -DCMAKE_BUILD_TYPE=Release -DKAGURA_DESKTOP_WITH_WREN=OFF >build-native-configure.log 2>&1
cmake --build build-native-only -j4 >build-native-build.log 2>&1
ctest --test-dir build-native-only --output-on-failure >results/native-only-tests.txt 2>&1
python3 -I tools/compare.py
python3 -I tools/provenance.py
