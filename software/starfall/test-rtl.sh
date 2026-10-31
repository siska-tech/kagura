#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Focused existing RTL regressions; keep the global regression logs untouched.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p build/starfall-rtl
run() {
    local top="$1"; shift
    verilator --binary --timing --timescale 1ns/1ps -Wno-fatal --top-module "$top" \
        --Mdir "$PWD/build/starfall-rtl/$top" -j 2 "$@" > "build/starfall-rtl/$top.build.log" 2>&1
    timeout 60 "build/starfall-rtl/$top/V$top" +verilator+seed+1 | tee "build/starfall-rtl/$top.run.log"
    grep -q '^PASS:' "build/starfall-rtl/$top.run.log"
}
run tb_sprite_selector rtl/vdp/kagura_sprite_selector.sv sim/tests/tb_sprite_selector.sv
run tb_sprite_composite rtl/vdp/kagura_sprite_selector.sv rtl/vdp/kagura_sprite_row.sv sim/tests/tb_sprite_composite.sv
run tb_register_abi rtl/core/kagura_abi_pkg.sv rtl/core/kagura_registers.sv \
    rtl/audio/kagura_audio_registers.sv sim/tests/tb_register_abi.sv
