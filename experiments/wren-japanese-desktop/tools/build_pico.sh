#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$HOME/opt/cmake-3.31.6-linux-x86_64/bin:$PATH"
: "${PICO_SDK_PATH:=/home/shion/opt/pico-sdk-2.2.0}"
export PICO_SDK_PATH
test "$(git -C "$PICO_SDK_PATH" rev-parse HEAD)" = a1438dff1d38bd9c65dbd693f0e5db4b9ae91779
test "$(git -C "$PICO_SDK_PATH/lib/tinyusb" rev-parse HEAD)" = 86ad6e56c1700e85f1c5678607a762cfe3aa2f47
python3 ../wren-rp2040/tools/verify_sources.py
python3 tools/gen_app.py
cmake -S pico -B build-pico -DCMAKE_BUILD_TYPE=Release
cmake --build build-pico --target wren_desktop_flash -j4
