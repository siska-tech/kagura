# SPDX-License-Identifier: Apache-2.0
# Run from build/audio-synth. Core-only synthesis; no board bitstream/STA.
set root [file normalize [file join [file dirname [info script]] ..]]
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
add_file -type verilog [file join $root rtl audio kagura_audio_synth.sv]
set_option -top_module kagura_audio_synth
set_option -output_base_name kagura_audio_synth
run syn
