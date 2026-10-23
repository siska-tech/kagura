# SPDX-License-Identifier: Apache-2.0
# P1-06: map the 25-block RAM plan on GW1NR-9C. Run from build/p1-06-bsram.
set root [file normalize [file join [file dirname [info script]] ..]]
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
foreach path {rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_sdp.sv rtl/memory/kagura_ram_tdp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_line_banks.sv rtl/platform/kagura_nano9k_clocks.sv boards/tang-nano-9k/kagura_bsram_eval_top.sv} {
    add_file -type verilog [file join $root $path]
}
add_file -type cst [file join $root boards tang-nano-9k bsram-eval.cst]
add_file -type sdc [file join $root boards tang-nano-9k bsram-eval.sdc]
set_option -top_module kagura_bsram_eval_top
set_option -output_base_name kagura_bsram_eval
run all
