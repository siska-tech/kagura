# SPDX-License-Identifier: Apache-2.0
# Run from build/gowin-smoke. Synthesis-only installation smoke test.
# This does not generate a board-ready HDMI bitstream or perform STA.
set root [file normalize [file join [file dirname [info script]] ..]]
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
add_file -type verilog [file join $root rtl audio kagura_test_tone.sv]
set_option -top_module kagura_test_tone
set_option -output_base_name kagura_source_smoke
run syn
