#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$PATH"
cmake -S platform/arm -B build-arm -DCMAKE_BUILD_TYPE=Release
cmake --build build-arm -j4
