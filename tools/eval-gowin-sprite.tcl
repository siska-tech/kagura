# SPDX-License-Identifier: Apache-2.0
# Run from a build directory. Optional argument: selector (default) or row.
# Synthesis only; no board bitstream or STA.
set root [file normalize [file join [file dirname [info script]] ..]]
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
set part [expr {[llength $argv] ? [lindex $argv 0] : "selector"}]
if {$part ni {selector row}} { error "Expected selector or row" }
set top kagura_sprite_${part}
add_file -type verilog [file join $root rtl vdp ${top}.sv]
set_option -top_module $top
set_option -output_base_name $top
run syn
