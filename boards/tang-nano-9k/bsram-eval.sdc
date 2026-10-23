create_clock -name clk27 -period 37.037 [get_ports {clk27}]
create_generated_clock -name serial126 -source [get_ports {clk27}] -multiply_by 14 -divide_by 3 [get_pins {clocks/video_pll/CLKOUT}]
create_generated_clock -name pixel25 -source [get_pins {clocks/video_pll/CLKOUT}] -divide_by 5 [get_pins {clocks/pixel_div/CLKOUT}]
create_generated_clock -name system54 -source [get_ports {clk27}] -multiply_by 2 [get_pins {clocks/system_pll/CLKOUT}]
# Line-bank handover toggles: bound the first synchronizer stage like the
# FIFO Gray pointers; the second stage stays timed.
set_max_delay 10.000 -from [get_clocks {system54}] -to [get_pins {lines/ready_sync_0_s0/D}]
set_max_delay 10.000 -from [get_clocks {pixel25}] -to [get_pins {lines/display_sync_0_s0/D}]
set_false_path -from [get_ports {reset_n}]
set_false_path -to [get_ports {led_n[*]}]
