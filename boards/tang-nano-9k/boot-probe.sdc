create_clock -name clk27 -period 37.037 [get_ports {clk27}]
create_generated_clock -name system54 -source [get_ports {clk27}] -multiply_by 2 [get_pins {clocks/system_pll/CLKOUT}]
set_false_path -from [get_ports {reset_n}]
set_false_path -to [get_ports {led_n[*] boot_map}]
# CLK_DIV=4: MISO changes four system cycles before and after each sample.
# setup=4, hold=7 gives relations +4T and -4T; see docs/boot-sta-audit.md.
# External delays are provisional pending AC-table/board measurements.
set_input_delay -clock [get_clocks {system54}] -max 55.000 [get_ports {flash_miso}]
set_input_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {flash_miso}]
set_multicycle_path -from [get_ports {flash_miso}] -to [get_regs {boot/reader/data_0_s0 boot/reader/rx_shift_0_s0}] -setup -end 4
set_multicycle_path -from [get_ports {flash_miso}] -to [get_regs {boot/reader/data_0_s0 boot/reader/rx_shift_0_s0}] -hold -end 7
report_exceptions -setup -from [get_ports {flash_miso}] -max_paths 100 -max_common_paths 1
report_exceptions -hold -from [get_ports {flash_miso}] -max_paths 100 -max_common_paths 1
