# SPDX-License-Identifier: Apache-2.0
# Synthesis-only check of the vendor-neutral HyperRAM controller and Gowin PHY.
set root [file normalize [file join [file dirname [info script]] ..]]
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
add_file -type verilog [file join $root rtl memory kagura_hyperram_ctrl.sv]
add_file -type verilog [file join $root rtl memory kagura_hyperram_phy_gowin.sv]
add_file -type verilog [file join $root boards tang-nano-9k kagura_hyperram_eval_top.sv]
set_option -top_module kagura_hyperram_eval_top
set_option -output_base_name kagura_hyperram_eval
run syn
