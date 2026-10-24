# BOOT_MAP changes only after a PHI2 falling edge and is delayed to phase 2.
set_false_path -to [get_ports {boot_map}]
# P25Q32U MISO changes after an SCLK falling edge and is sampled four system54
# cycles later.  Values are provisional until the exact P25Q32U AC table and
# board measurement are available; they do not false-path the input.
set_input_delay -clock [get_clocks {system54}] -max 55.000 [get_ports {flash_miso}]
set_input_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {flash_miso}]
set_multicycle_path -from [get_ports {flash_miso}] -to [get_clocks {system54}] -setup -end 4
set_multicycle_path -from [get_ports {flash_miso}] -to [get_clocks {system54}] -hold -end 3
