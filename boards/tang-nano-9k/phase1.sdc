create_clock -name clk27 -period 37.037 [get_ports {clk27}]
create_generated_clock -name serial126 -source [get_ports {clk27}] -multiply_by 14 -divide_by 3 [get_pins {clocks/video_pll/CLKOUT}]
create_generated_clock -name pixel25 -source [get_pins {clocks/video_pll/CLKOUT}] -divide_by 5 [get_pins {clocks/pixel_div/CLKOUT}]
create_generated_clock -name system54 -source [get_ports {clk27}] -multiply_by 2 [get_pins {clocks/system_pll/CLKOUT}]
# Common to the HDMI+audio and DVI builds; audio FIFO CDC is in phase1-audio.sdc.
# Board I/O with no external timing relationship. reset_n only asserts the
# release synchronizers and PLL RESET; LEDs are static status indicators.
# TMDS outputs leave OSER10 IOLOGIC directly and the sink recovers the clock,
# so no output delay applies.
set_false_path -from [get_ports {reset_n}]
set_false_path -to [get_ports {led_n[*]}]
