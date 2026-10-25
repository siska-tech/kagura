# SPDX-License-Identifier: Apache-2.0
# Synthesize a locally generated PSRAM_HS 2.1 instance. The encrypted vendor
# source stays under build/ and is copied from the installed Gowin release.
if {![info exists ::env(KAGURA_PSRAM_IP_DIR)]} {
    error "KAGURA_PSRAM_IP_DIR must name the generated PSRAM_HS source directory"
}
set root [file normalize [file join [file dirname [info script]] ..]]
set ip_dir [file normalize $::env(KAGURA_PSRAM_IP_DIR)]
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
foreach name {PSRAM_TOP.v psram_code.v} {
    add_file -type verilog [file join $ip_dir $name]
}
add_file -type verilog [file join $root boards tang-nano-9k kagura_psram_eval_top.sv]
set_option -top_module kagura_psram_eval_top
set_option -output_base_name kagura_psram_eval
run syn
