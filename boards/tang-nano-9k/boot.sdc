# BOOT_MAP changes on the system54 edge that starts phase 2 (two cycles after the
# PHI2 fall), after the CPU read hold and before the next address decode. It
# uses the same budget as cpu_phi2 (phase2-cpu.sdc, PHI2_MAX = 16): the STA fails
# if the pin changes later than 16 ns after its ideal edge. With PHI2 and BOOT_MAP
# both inside 0..16 ns, a carrier checks its switching window from the two
# budgets, its PHI2 buffer and its board delays (docs/romless-boot.md).
set_output_delay -clock [get_clocks {system54}] -max 2.518 [get_ports {boot_map}]
set_output_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {boot_map}]
# P25Q32U MISO changes after an SCLK falling edge and is sampled four system54
# cycles later; the next change is another four cycles after that sample.
# setup=4, hold=7 gives relations +4T and -4T (CLK_DIV=4), including the
# final bit's high half-cycle and byte-boundary low pauses. See boot-sta-audit.md.
# External delays remain provisional pending AC-table/board measurements.
# Limit the exception to the two MISO capture bits; a new consumer must be
# separately audited. Board tops explicitly select FLASH_CLK_DIV=4.
set_input_delay -clock [get_clocks {system54}] -max 55.000 [get_ports {flash_miso}]
set_input_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {flash_miso}]
set_multicycle_path -from [get_ports {flash_miso}] -to [get_regs {boot/reader/data_0_s0 boot/reader/rx_shift_0_s0}] -setup -end 4
set_multicycle_path -from [get_ports {flash_miso}] -to [get_regs {boot/reader/data_0_s0 boot/reader/rx_shift_0_s0}] -hold -end 7
report_exceptions -setup -from [get_ports {flash_miso}] -max_paths 100 -max_common_paths 1
report_exceptions -hold -from [get_ports {flash_miso}] -max_paths 100 -max_common_paths 1
