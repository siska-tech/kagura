# CLKOUTP uses the system PLL's dynamic phase inputs fixed at PSDA=3.
# Dynamic PLL phase is NOT inferred by STA. Explicitly describe 67.5 degrees
# (3.472ns at 54MHz); otherwise the CK-enable crossing is checked at 0 degrees.
create_generated_clock -name psram54 -source [get_ports {clk27}] -multiply_by 2 -phase 67.5 [get_pins {clocks/system_pll/CLKOUTP}]
set_false_path -to [get_ports {uart_tx}]
