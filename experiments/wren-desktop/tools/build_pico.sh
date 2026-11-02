#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PICO_SDK_PATH:?Set pinned Pico SDK 2.2.0 path}"
test "$(git -C "$PICO_SDK_PATH" rev-parse HEAD)" = a1438dff1d38bd9c65dbd693f0e5db4b9ae91779
test "$(git -C "$PICO_SDK_PATH/lib/tinyusb" rev-parse HEAD)" = 86ad6e56c1700e85f1c5678607a762cfe3aa2f47
arm-none-eabi-gcc --version | head -1 | grep '14.2.1'
python3 ../wren-rp2040/tools/verify_sources.py
python3 tools/gen_app.py
cmake -S pico -B build-pico -DCMAKE_BUILD_TYPE=Release
cmake --build build-pico -j4
