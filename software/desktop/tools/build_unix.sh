#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Builds the MicroPython v1.26.0 unix port (standard variant) with the
# KAGURA user C modules (kagura_desktop, kagura_audio) into its own build directory, leaving the
# plain build-standard untouched. Run from the repository root in WSL/Linux:
#   bash software/desktop/tools/build_unix.sh
# MPY_DIR defaults to build/micropython-src (v1.26.0 checkout with mpy-cross).
# libffi, btree, mbedtls and the frozen micropython-lib are left out, as in the
# repository CI (no submodules needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MPY_DIR="${MPY_DIR:-$ROOT/build/micropython-src}"
BUILD="${BUILD:-build-kagura-desktop}"
make -C "$MPY_DIR/ports/unix" VARIANT=standard BUILD="$BUILD" \
    MICROPY_PY_FFI=0 MICROPY_PY_BTREE=0 MICROPY_PY_SSL=0 MICROPY_SSL_MBEDTLS=0 FROZEN_MANIFEST= \
    USER_C_MODULES="$ROOT/software/micropython/usermods" -j"$(nproc)" "$@" >&2
echo "$MPY_DIR/ports/unix/$BUILD/micropython"
