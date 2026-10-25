# Diagnostic copy of the sticky HDMI pixel-domain underflow flag.
set_max_delay 10.000 -from [get_clocks {pixel25}] -to [get_pins {underflow_sync1_s0/D}]
set_false_path -hold -from [get_clocks {pixel25}] -to [get_pins {underflow_sync1_s0/D}]
