create_clock -name clk27 -period 37.037 [get_ports {clk27}]
create_generated_clock -name system54 -source [get_ports {clk27}] -multiply_by 2 [get_pins {clocks/system_pll/CLKOUT}]
set_false_path -from [get_ports {reset_n}]
set_false_path -to [get_ports {led_n[*] boot_map}]
# Provisional until the P25Q32U AC table and board measurement are available.
set_input_delay -clock [get_clocks {system54}] -max 55.000 [get_ports {flash_miso}]
set_input_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {flash_miso}]
set_multicycle_path -from [get_ports {flash_miso}] -to [get_clocks {system54}] -setup -end 4
set_multicycle_path -from [get_ports {flash_miso}] -to [get_clocks {system54}] -hold -end 3
