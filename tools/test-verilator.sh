#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
# Environment:
#   KAGURA_STRICT_VERSION=1  fail unless verilator matches tools/verilator.version (CI)
#   KAGURA_SEED=<n>          runtime seed for $urandom (default 1)
#   KAGURA_TEST_TIMEOUT=<s>  per-test run timeout in seconds (default 1800)
#   KAGURA_TRACE="tb_a tb_b" dump build/verilator/<top>.vcd for these tops
#   KAGURA_FORCE_FAIL=<top>  report that top as failed, to check failure artifacts
expected_version="$(tr -d '[:space:]' < tools/verilator.version)"
actual_version="$(verilator --version | awk '{print $2}')"
echo "Verilator $actual_version (expected $expected_version)"
if [ "$actual_version" != "$expected_version" ]; then
    if [ "${KAGURA_STRICT_VERSION:-0}" = 1 ]; then echo "FAIL: Verilator version mismatch"; exit 1; fi
    echo "WARNING: Verilator version differs from tools/verilator.version"
fi
seed="${KAGURA_SEED:-1}"
test_timeout="${KAGURA_TEST_TIMEOUT:-1800}"
echo "seed $seed, per-test timeout ${test_timeout}s"
mkdir -p build/verilator
python3 sim/tests/test_boot_image.py
# Stale outputs would be mistaken for this run's evidence.
rm -f build/verilator/*.run.log build/verilator/*.raw build/verilator/*.wav build/verilator/*.ppm build/verilator/*.vcd
summary=build/verilator/summary.tsv
printf 'test\tresult\tseconds\n' > "$summary"
failures=()
# Records the result and continues, so one failure keeps the other tests' outputs.
run_test() {
    local top="$1"; shift
    local dest="$root/build/verilator/$top"
    local trace_args=() run_args=("+verilator+seed+$seed") result start=$SECONDS
    if [[ " ${KAGURA_TRACE:-} " == *" $top "* ]]; then
        printf 'bind %s kagura_trace kagura_trace_i();\n' "$top" > "build/verilator/$top.bind.sv"
        trace_args=(--trace sim/support/kagura_trace.sv "build/verilator/$top.bind.sv")
        run_args+=("+kagura_trace=build/verilator/$top.vcd")
    fi
    if ! verilator --binary --timing --timescale 1ns/1ps -Wno-fatal --top-module "$top" \
        --Mdir "$dest" -j 2 "$@" "${trace_args[@]}" > "build/verilator/$top.build.log" 2>&1; then
        result=build_failed
        tail -20 "build/verilator/$top.build.log"
    else
        local status=0
        timeout "$test_timeout" "$dest/V$top" "${run_args[@]}" | tee "build/verilator/$top.run.log" || status=$?
        if [ "$status" = 124 ]; then result=timeout
        elif [ "$status" != 0 ] || ! grep -q '^PASS:' "build/verilator/$top.run.log"; then result=failed
        else result=pass; fi
    fi
    if [ "$result" = pass ] && [ "${KAGURA_FORCE_FAIL:-}" = "$top" ]; then result=forced_fail; fi
    printf '%s\t%s\t%s\n' "$top" "$result" "$((SECONDS-start))" >> "$summary"
    if [ "$result" != pass ]; then echo "FAIL: $top ($result)"; failures+=("$top"); fi
}
run_test tb_phase1_sources rtl/vdp/kagura_bar_pattern.sv rtl/vdp/kagura_test_pattern.sv \
    rtl/audio/kagura_test_tone.sv sim/tests/tb_phase1_sources.sv
# Compile unchanged upstream SystemVerilog; no Icarus compatibility rewriting.
run_test tb_tmds_channel third_party/hdl-util-hdmi/src/tmds_channel.sv \
    sim/tests/tb_tmds_channel.sv
run_test tb_tmds_pipeline third_party/hdl-util-hdmi/src/tmds_channel.sv rtl/hdmi/kagura_tmds_channel.sv \
    sim/tests/tb_tmds_pipeline.sv
run_test tb_packet_assembler third_party/hdl-util-hdmi/src/packet_assembler.sv rtl/hdmi/kagura_packet_assembler.sv \
    sim/tests/tb_packet_assembler.sv
run_test tb_serializer_reset rtl/platform/kagura_gowin_serializer.sv sim/tests/tb_serializer_reset.sv
run_test tb_async_fifo rtl/memory/kagura_async_fifo.sv sim/tests/tb_async_fifo.sv
run_test tb_audio_packets rtl/memory/kagura_async_fifo.sv \
    rtl/audio/kagura_audio_transport.sv rtl/hdmi/kagura_audio_packets.sv \
    third_party/hdl-util-hdmi/src/audio_sample_packet.sv \
    third_party/hdl-util-hdmi/src/audio_info_frame.sv \
    third_party/hdl-util-hdmi/src/auxiliary_video_information_info_frame.sv \
    third_party/hdl-util-hdmi/src/source_product_description_info_frame.sv \
    third_party/hdl-util-hdmi/src/packet_assembler.sv sim/tests/tb_audio_packets.sv
python3 tools/prepare-hdmi-stream.py
# The same stream at VIC1 (640x480) and VIC4 (1280x720, docs/wide-mode.md).
for stream_test in tb_hdmi_stream tb_hdmi_stream720; do
    run_test "$stream_test" build/generated/kagura_hdmi_stream.sv rtl/hdmi/kagura_tmds_channel.sv rtl/hdmi/kagura_packet_assembler.sv \
        rtl/memory/kagura_async_fifo.sv rtl/audio/kagura_audio_transport.sv \
        rtl/hdmi/kagura_audio_packets.sv rtl/vdp/kagura_bar_pattern.sv rtl/vdp/kagura_video_source_bars.sv rtl/hdmi/kagura_hdmi_stream_eval.sv \
        third_party/hdl-util-hdmi/src/audio_sample_packet.sv \
        third_party/hdl-util-hdmi/src/audio_info_frame.sv \
        third_party/hdl-util-hdmi/src/auxiliary_video_information_info_frame.sv \
        third_party/hdl-util-hdmi/src/source_product_description_info_frame.sv \
        third_party/hdl-util-hdmi/src/packet_assembler.sv \
        third_party/hdl-util-hdmi/src/tmds_channel.sv sim/tests/tb_hdmi_stream.sv
done
run_test tb_bsram_wrappers rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_sdp.sv \
    rtl/memory/kagura_ram_tdp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_line_banks.sv \
    sim/tests/tb_bsram_wrappers.sv
CORE_SOURCES=(rtl/audio/kagura_audio_registers.sv rtl/audio/kagura_audio_synth.sv
    rtl/audio/kagura_audio_transport.sv rtl/memory/kagura_async_fifo.sv
    rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_vram.sv
    rtl/core/kagura_command_queue.sv rtl/core/kagura_vram_engine.sv rtl/core/kagura_registers.sv
    rtl/core/kagura_raster_scroll.sv rtl/core/kagura_core.sv rtl/vdp/kagura_bg_renderer.sv rtl/vdp/kagura_sprite_selector.sv rtl/vdp/kagura_sprite_row.sv rtl/vdp/kagura_sprite_renderer.sv
    rtl/audio/kagura_pcm_control.sv rtl/audio/kagura_pcm_prefetch.sv rtl/memory/kagura_psram_arbiter.sv rtl/memory/kagura_psram_read_path.sv
    rtl/memory/kagura_psram_read_cdc.sv rtl/memory/kagura_psram_byte_bridge.sv rtl/memory/kagura_hyperram_ctrl.sv)
run_test tb_w65c02_bus rtl/bus/kagura_w65c02_adapter.sv "${CORE_SOURCES[@]}" sim/tests/tb_w65c02_bus.sv
run_test tb_flash_reader rtl/boot/kagura_flash_reader.sv sim/tests/tb_flash_reader.sv
run_test tb_boot_image_check rtl/boot/kagura_boot_image_check.sv sim/tests/tb_boot_image_check.sv
run_test tb_boot_window rtl/boot/kagura_boot_window.sv sim/tests/tb_boot_window.sv
run_test tb_boot_controller rtl/boot/kagura_flash_reader.sv rtl/boot/kagura_boot_image_check.sv \
    rtl/boot/kagura_boot_window.sv rtl/boot/kagura_boot_controller.sv sim/tests/tb_boot_controller.sv
run_test tb_romless_boot_system rtl/boot/kagura_flash_reader.sv rtl/boot/kagura_boot_image_check.sv \
    rtl/boot/kagura_boot_window.sv rtl/boot/kagura_boot_controller.sv sim/tests/tb_romless_boot_system.sv
for host_test in tb_spi_bus tb_qspi_bus; do
    run_test "$host_test" rtl/bus/kagura_spi_adapter.sv "${CORE_SOURCES[@]}" sim/tests/tb_host_bus.sv
done
run_test tb_vram_core "${CORE_SOURCES[@]}" sim/tests/tb_vram_core.sv
run_test tb_audio_core "${CORE_SOURCES[@]}" sim/tests/tb_audio_core.sv
run_test tb_psram_core "${CORE_SOURCES[@]}" sim/support/kagura_hyperram_pair_model.sv sim/tests/tb_psram_core.sv
run_test tb_vdp_frame "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
    rtl/vdp/kagura_vdp.sv sim/tests/tb_vdp_frame.sv
# tb_vdp_frame720/tb_vdp_sprites720: 320x180 on 1280x720 (docs/wide-mode.md).
for vdp_test in tb_vdp_sprites tb_vdp_frame720 tb_vdp_sprites720 tb_raster_scroll tb_raster_scroll720; do
    run_test "$vdp_test" "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
        rtl/vdp/kagura_vdp.sv sim/tests/tb_vdp_frame.sv sim/tests/tb_vdp_sprites.sv
done
run_test tb_demo_sequencer "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
    rtl/vdp/kagura_vdp.sv rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv sim/tests/tb_demo_sequencer.sv
run_test tb_demo_sprites "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
    rtl/vdp/kagura_vdp.sv rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv sim/tests/tb_demo_sequencer.sv sim/tests/tb_demo_sprites.sv
run_test tb_demo_raster "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
    rtl/vdp/kagura_vdp.sv rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv sim/tests/tb_demo_sequencer.sv sim/tests/tb_demo_raster.sv
run_test tb_demo_audio "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
    rtl/vdp/kagura_vdp.sv rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv sim/tests/tb_demo_sequencer.sv sim/tests/tb_demo_audio.sv
# Half a second of the demo song; for the whole loop with the lead run
# build/verilator/tb_demo_music/Vtb_demo_music +frames=1350 (about 15 minutes).
run_test tb_demo_music "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
    rtl/vdp/kagura_vdp.sv rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv sim/tests/tb_demo_music.sv
[ ! -f build/verilator/demo-music.raw ] || python3 tools/render-audio-wav.py build/verilator/demo-music.raw build/verilator/demo-music.wav
# Shooter scene of the board demo; checked frames are saved as build/verilator/shooter-<k>.ppm.
# build/verilator/tb_demo_shooter/Vtb_demo_shooter +long also checks update 100.
run_test tb_demo_shooter "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
    rtl/vdp/kagura_vdp.sv rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv sim/tests/tb_demo_shooter.sv
# The same scene started inside the enemy-wall phases (16 sprites/line overflow, fixed and rotated order),
# and on the 16:9 build (320x180 on 1280x720).
for wall_test in tb_demo_wall tb_demo_flicker tb_demo_shooter720 tb_demo_shooter_raster tb_demo_shooter_raster720; do
    run_test "$wall_test" "${CORE_SOURCES[@]}" rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_line_display.sv \
        rtl/vdp/kagura_vdp.sv rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv \
        sim/tests/tb_demo_shooter.sv sim/tests/tb_demo_wall.sv
done
run_test tb_sprite_selector rtl/vdp/kagura_sprite_selector.sv sim/tests/tb_sprite_selector.sv
run_test tb_sprite_composite rtl/vdp/kagura_sprite_selector.sv rtl/vdp/kagura_sprite_row.sv sim/tests/tb_sprite_composite.sv
run_test tb_sprite_irq rtl/core/kagura_registers.sv sim/tests/tb_sprite_irq.sv
run_test tb_fill_timing rtl/core/kagura_registers.sv sim/tests/tb_fill_timing.sv
# Generated ABI package (tools/gen-registers.ps1) against the register RTL.
run_test tb_register_abi rtl/core/kagura_abi_pkg.sv rtl/core/kagura_registers.sv rtl/audio/kagura_audio_registers.sv \
    sim/tests/tb_register_abi.sv
run_test tb_vram_init rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_vram.sv sim/tests/tb_vram_init.sv
run_test tb_startup_cpu "${CORE_SOURCES[@]}" rtl/bus/kagura_w65c02_adapter.sv rtl/memory/kagura_ram_tdp.sv \
    rtl/vdp/kagura_line_display.sv rtl/vdp/kagura_vdp.sv sim/tests/tb_startup_cpu.sv
run_test tb_audio_synth rtl/audio/kagura_audio_synth.sv sim/tests/tb_audio_synth.sv
run_test tb_audio_pcm_mix rtl/audio/kagura_audio_synth.sv sim/tests/tb_audio_pcm_mix.sv
run_test tb_pcm_prefetch rtl/audio/kagura_pcm_prefetch.sv sim/tests/tb_pcm_prefetch.sv
run_test tb_pcm_timeout rtl/audio/kagura_pcm_prefetch.sv sim/tests/tb_pcm_timeout.sv
run_test tb_pcm_audio_path rtl/audio/kagura_audio_synth.sv rtl/audio/kagura_pcm_prefetch.sv sim/tests/tb_pcm_audio_path.sv
run_test tb_psram_byte_bridge rtl/memory/kagura_psram_byte_bridge.sv sim/tests/tb_psram_byte_bridge.sv
run_test tb_psram_read_cdc rtl/memory/kagura_psram_read_cdc.sv sim/tests/tb_psram_read_cdc.sv
run_test tb_hyperram_ctrl rtl/memory/kagura_hyperram_ctrl.sv sim/tests/tb_hyperram_ctrl.sv
run_test tb_psram_arbiter rtl/memory/kagura_psram_arbiter.sv sim/tests/tb_psram_arbiter.sv
run_test tb_hyperram_pcm_source rtl/audio/kagura_audio_synth.sv rtl/audio/kagura_pcm_prefetch.sv \
    rtl/memory/kagura_psram_read_cdc.sv rtl/memory/kagura_psram_byte_bridge.sv \
    rtl/memory/kagura_psram_read_path.sv rtl/memory/kagura_hyperram_ctrl.sv \
    rtl/memory/kagura_psram_arbiter.sv boards/tang-nano-9k/kagura_hyperram_pcm_source.sv \
    sim/support/kagura_hyperram_pair_model.sv sim/tests/tb_hyperram_pcm_source.sv
run_test tb_hyperram_pcm_chain rtl/audio/kagura_audio_synth.sv rtl/audio/kagura_pcm_prefetch.sv \
    rtl/memory/kagura_psram_read_cdc.sv rtl/memory/kagura_psram_byte_bridge.sv \
    rtl/memory/kagura_psram_read_path.sv rtl/memory/kagura_hyperram_ctrl.sv \
    sim/support/kagura_hyperram_pair_model.sv sim/tests/tb_hyperram_pcm_chain.sv
run_test tb_psram_pcm_chain rtl/audio/kagura_audio_synth.sv rtl/audio/kagura_pcm_prefetch.sv \
    rtl/memory/kagura_psram_read_cdc.sv rtl/memory/kagura_psram_byte_bridge.sv \
    rtl/memory/kagura_psram_read_path.sv sim/tests/tb_psram_pcm_chain.sv
[ ! -f build/verilator/audio-synth.raw ] || python3 tools/render-audio-wav.py build/verilator/audio-synth.raw build/verilator/audio-synth.wav
column -t "$summary" 2>/dev/null || cat "$summary"
if [ "${#failures[@]}" -gt 0 ]; then
    echo "FAIL: ${#failures[@]} test(s): ${failures[*]}"
    exit 1
fi
echo "PASS: all $(($(wc -l < "$summary")-1)) tests"
