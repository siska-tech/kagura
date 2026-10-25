# SPDX-License-Identifier: Apache-2.0
# Full flow (synthesis, P&R, bitstream) for the HyperRAM bring-up design.
set root [file normalize [file join [file dirname [info script]] ..]]
set b [file join $root boards tang-nano-9k]
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
add_file -type verilog [file join $root rtl memory kagura_hyperram_ctrl.sv]
add_file -type verilog [file join $root rtl memory kagura_hyperram_phy_gowin.sv]
add_file -type verilog [file join $b kagura_hyperram_test_top.sv]
add_file -type cst [file join $b hyperram-test.cst]
add_file -type sdc [file join $b hyperram-test.sdc]
set_option -top_module kagura_hyperram_test_top
set_option -output_base_name kagura_hyperram_test
set_option -use_sspi_as_gpio 1
set_option -use_mspi_as_gpio 1
set_option -use_ready_as_gpio 1
set_option -use_done_as_gpio 1
set_option -use_cpu_as_gpio 1
run all
