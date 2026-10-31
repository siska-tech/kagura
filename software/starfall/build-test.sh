#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
cd "$(dirname "$0")/../.."
export PICO_SDK_PATH="${PICO_SDK_PATH:-$HOME/opt/pico-sdk-2.2.0}"
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$HOME/opt/cmake-3.31.6-linux-x86_64/bin:$PATH"
cmake -S software/starfall -B build/starfall-host -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_C_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer"
cmake --build build/starfall-host -j2
ctest --test-dir build/starfall-host --output-on-failure
cmake -S software/starfall -B build/starfall-pico -DSTARFALL_PICO=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build/starfall-pico -j4
arm-none-eabi-size build/starfall-pico/starfall.elf
cmake -S software/starfall -B build/starfall-qspi -DSTARFALL_PICO=ON -DSTARFALL_QSPI=ON \
    -DCMAKE_BUILD_TYPE=Release -U PICOTOOL_FETCH_FROM_GIT_PATH \
    -Dpicotool_DIR="$PWD/build/starfall-pico/_deps/picotool"
cmake --build build/starfall-qspi -j4
arm-none-eabi-size build/starfall-qspi/starfall.elf
cp build/starfall-pico/starfall.uf2 build/starfall-v6-spi.uf2
cp build/starfall-qspi/starfall.uf2 build/starfall-v6-qspi.uf2
