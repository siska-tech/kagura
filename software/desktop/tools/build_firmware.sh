#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Builds the KAGURA_PICO MicroPython v1.26.0 firmware of this tree (the board
# includes the native desktop module, software/desktop). Needs the Arm GNU
# toolchain and an initialised build/micropython-src (see
# software/micropython/README.md). From the repository root (WSL/Linux):
#   bash software/desktop/tools/build_firmware.sh [BOARD] [BUILD_DIR_NAME]
# Prints the UF2 path; tools/rp2040-firmware.py flashes it with checks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MPY_DIR="${MPY_DIR:-$ROOT/build/micropython-src}"
BOARD="${1:-KAGURA_PICO}"
BUILD="${2:-build-$BOARD-native}"
export PATH="${ARM_GCC_BIN:-$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin}:$PATH"
make -C "$MPY_DIR/ports/rp2" BOARD="$BOARD" BOARD_DIR="$ROOT/software/micropython/boards/$BOARD" \
    BUILD="$BUILD" -j"$(nproc)" >&2
arm-none-eabi-size "$MPY_DIR/ports/rp2/$BUILD/firmware.elf" >&2
echo "$MPY_DIR/ports/rp2/$BUILD/firmware.uf2"
