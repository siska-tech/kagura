#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Builds the MicroPython v1.26.0 unix port (standard variant) with the
# kagura_desktop user C module into its own build directory, leaving the
# plain build-standard untouched. Run from the repository root in WSL/Linux:
#   bash experiments/c-gem-desktop/micropython/tools/build_unix.sh
# MPY_DIR defaults to build/micropython-src (v1.26.0 checkout with mpy-cross).
# libffi, btree and mbedtls are left out, as in the plain build-standard here.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
MPY_DIR="${MPY_DIR:-$ROOT/build/micropython-src}"
BUILD="${BUILD:-build-kagura-desktop}"
make -C "$MPY_DIR/ports/unix" VARIANT=standard BUILD="$BUILD" \
    MICROPY_PY_FFI=0 MICROPY_PY_BTREE=0 MICROPY_PY_SSL=0 MICROPY_SSL_MBEDTLS=0 \
    USER_C_MODULES="$ROOT/experiments/c-gem-desktop/micropython" -j"$(nproc)" "$@" >&2
echo "$MPY_DIR/ports/unix/$BUILD/micropython"
