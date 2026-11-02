#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build-arm-memory
arm-none-eabi-gcc -std=gnu11 -mcpu=cortex-m0plus -mthumb -Os -nostartfiles -static \
  -ffunction-sections -fdata-sections -Wl,--gc-sections -DWREN_OPT_META=0 -DWREN_OPT_RANDOM=0 \
  -Ivendor/wren/src/include -Ivendor/wren/src/vm -Isrc \
  src/arm_memory.c src/experiment.c vendor/wren/src/vm/*.c -lm -lc -lgcc \
  -o build-arm-memory/wren_memory.elf
"${QEMU:-qemu-arm}" build-arm-memory/wren_memory.elf 262144 checks
