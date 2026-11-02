#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p results
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug \
 -DCMAKE_C_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' \
 -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined' > /tmp/wj-asan-configure.txt 2>&1
cmake --build build-asan -j4 >build-asan/build.txt 2>&1
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ctest --test-dir build-asan --output-on-failure >results/asan-tests.txt 2>&1
for input in wren-desktop native-text; do
  for mode in Release Debug; do
    out="build-$input-$mode"
    flags=(); label=release
    if [ "$mode" = Debug ]; then
      label=asan
      flags=(-DCMAKE_C_FLAGS=-fsanitize=address,undefined\ -fno-omit-frame-pointer -DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined)
    fi
    cmake -S "../$input" -B "$out" -DCMAKE_BUILD_TYPE="$mode" "${flags[@]}" > /tmp/wj-regression-configure.txt 2>&1
    cmake --build "$out" -j4 >"$out/build.txt" 2>&1
    ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ctest --test-dir "$out" --output-on-failure >"results/$input-$label-tests.txt" 2>&1
  done
done
