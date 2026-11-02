#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$HOME/opt/cmake-3.31.6-linux-x86_64/bin:$PATH"
export PICO_SDK_PATH=/home/shion/opt/pico-sdk-2.2.0
cmake --build build-host -j4 >build-host/hardware-build-host.txt 2>&1
ctest --test-dir build-host --output-on-failure >build-host/hardware-preflight-host.txt 2>&1
cmake --build build-asan -j4 >build-host/hardware-build-asan.txt 2>&1
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ctest --test-dir build-asan --output-on-failure >build-host/hardware-preflight-asan.txt 2>&1
bash tools/build_arm.sh >build-host/hardware-build-arm.txt 2>&1
QEMU=/mnt/c/Users/Shion/Documents/Projects/Kagura/build/c-gem-deps/qemu/root/usr/bin/qemu-arm python3 tools/arm_checks.py >build-host/hardware-preflight-arm.txt 2>&1
bash tools/build_pico.sh >build-host/hardware-build-pico.txt 2>&1
bash tools/evidence.sh >build-host/hardware-evidence.txt 2>&1
