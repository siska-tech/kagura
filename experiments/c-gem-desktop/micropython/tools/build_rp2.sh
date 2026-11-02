#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Builds (never flashes) the KAGURA_PICO MicroPython v1.26.0 firmware twice
# from the same tree, without and with the kagura_desktop module, so the
# memory report can give exact flash and RAM deltas. Run in WSL/Linux from
# the repository root; needs the Arm GNU toolchain (as for the KAGURA_PICO
# build in software/micropython/README.md) and an initialised
# build/micropython-src (rp2 submodules, mpy-cross).
#   bash experiments/c-gem-desktop/micropython/tools/build_rp2.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
MPY_DIR="${MPY_DIR:-$ROOT/build/micropython-src}"
export PATH="${ARM_GCC_BIN:-$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin}:$PATH"
BOARD_DIR="$ROOT/software/micropython/boards/KAGURA_PICO"
for variant in base kd; do
    extra=()
    [ "$variant" = kd ] && extra=(USER_C_MODULES="$ROOT/experiments/c-gem-desktop/micropython/micropython.cmake")
    make -C "$MPY_DIR/ports/rp2" BOARD=KAGURA_PICO BOARD_DIR="$BOARD_DIR" \
        BUILD="build-KAGURA_PICO-stage3a-$variant" "${extra[@]}" -j"$(nproc)" >&2
    echo "$MPY_DIR/ports/rp2/build-KAGURA_PICO-stage3a-$variant/firmware.elf"
done
