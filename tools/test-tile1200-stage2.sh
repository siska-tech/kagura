#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Focused regression for the 1200-pattern experiment.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
mkdir -p build/tile1200-stage2
exec 9>build/tile1200-stage2/.lock
flock -n 9 || exit 1
printf 'test\tresult\n' > build/tile1200-stage2/summary.tsv
core=(rtl/audio/kagura_audio_registers.sv rtl/audio/kagura_audio_synth.sv
    rtl/audio/kagura_audio_transport.sv rtl/memory/kagura_async_fifo.sv
    rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_vram.sv
    rtl/core/kagura_command_queue.sv rtl/core/kagura_vram_engine.sv rtl/core/kagura_registers.sv
    rtl/core/kagura_raster_scroll.sv rtl/core/kagura_core.sv rtl/vdp/kagura_bg_renderer.sv
    rtl/vdp/kagura_sprite_selector.sv rtl/vdp/kagura_sprite_row.sv rtl/vdp/kagura_sprite_renderer.sv
    rtl/audio/kagura_pcm_control.sv rtl/audio/kagura_pcm_prefetch.sv
    rtl/memory/kagura_psram_arbiter.sv rtl/memory/kagura_psram_read_path.sv
    rtl/memory/kagura_psram_read_cdc.sv rtl/memory/kagura_psram_byte_bridge.sv rtl/memory/kagura_hyperram_ctrl.sv)
vdp=(rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv rtl/vdp/kagura_vdp.sv)
failures=0
run_test() {
    local top="$1"; shift
    local dest="$root/build/tile1200-stage2/$top" result=pass
    if ! verilator --binary --timing --timescale 1ns/1ps -Wno-fatal --top-module "$top" \
        --Mdir "$dest" -j 2 "$@" > "build/tile1200-stage2/$top.build.log" 2>&1; then
        result=build_failed
        tail -20 "build/tile1200-stage2/$top.build.log"
    elif ! timeout 1800 "$dest/V$top" +verilator+seed+1 > "build/tile1200-stage2/$top.run.log" 2>&1; then
        result=failed
        tail -20 "build/tile1200-stage2/$top.run.log"
    elif ! grep -q '^PASS:' "build/tile1200-stage2/$top.run.log"; then
        result=failed
    else
        grep '^PASS:' "build/tile1200-stage2/$top.run.log"
    fi
    printf '%s\t%s\n' "$top" "$result" | tee -a build/tile1200-stage2/summary.tsv
    if [ "$result" != pass ]; then failures=$((failures+1)); fi
}
verilator --version
run_test tb_command_queue rtl/core/kagura_command_queue.sv sim/tests/tb_command_queue.sv
run_test tb_register_abi rtl/core/kagura_abi_pkg.sv rtl/core/kagura_registers.sv rtl/audio/kagura_audio_registers.sv sim/tests/tb_register_abi.sv
run_test tb_vram_init rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_vram.sv sim/tests/tb_vram_init.sv
run_test tb_vram_core "${core[@]}" sim/tests/tb_vram_core.sv
run_test tb_psram_core "${core[@]}" sim/support/kagura_hyperram_pair_model.sv sim/tests/tb_psram_core.sv
run_test tb_w65c02_bus rtl/bus/kagura_w65c02_adapter.sv "${core[@]}" sim/tests/tb_w65c02_bus.sv
for top in tb_spi_bus tb_qspi_bus; do
    run_test "$top" rtl/bus/kagura_spi_adapter.sv "${core[@]}" sim/tests/tb_host_bus.sv
done
run_test tb_startup_cpu "${core[@]}" "${vdp[@]}" rtl/bus/kagura_w65c02_adapter.sv sim/tests/tb_startup_cpu.sv
for top in tb_vdp_frame tb_vdp_sprites tb_vdp_frame720 tb_vdp_sprites720; do
    run_test "$top" "${core[@]}" "${vdp[@]}" sim/tests/tb_vdp_frame.sv sim/tests/tb_vdp_sprites.sv
done
for top in tb_tile1200_frame tb_tile1200_frame720; do
    run_test "$top" "${core[@]}" "${vdp[@]}" sim/tests/tb_vdp_frame.sv sim/tests/tb_tile1200_frame.sv
done
test "$failures" -eq 0
