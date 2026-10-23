# W65C02S bus I/O, used with phase1.sdc and phase1-audio.sdc by the Phase 2
# build. PHI2 is a system54 register output, so every CPU path is timed from
# system54 edges with multicycle counts taken from docs/timing.md. Delays (ns):
# PHI2 clock-to-out estimate 8, board 3 each way, W65C02S tADS/tMDS 40,
# external CS decode 10, read setup 15. First P&R reported the phi2 output
# delay as 2.70..4.39ns, so the 8ns estimate is kept as margin; recheck it
# against the measured board. Gowin applies multicycle paths that
# start at ports only with an explicit -to clock (and outputs with -from clock).
# A/RWB: launched by the PHI2 fall (phase 0 edge), sampled at phase 6.
set_input_delay -clock [get_clocks {system54}] -max 54.000 [get_ports {cpu_a[*] cpu_rwb}]
set_input_delay -clock [get_clocks {system54}] -min 13.000 [get_ports {cpu_a[*] cpu_rwb}]
set_input_delay -clock [get_clocks {system54}] -max 64.000 [get_ports {cpu_cs_n}]
set_input_delay -clock [get_clocks {system54}] -min 13.000 [get_ports {cpu_cs_n}]
set_multicycle_path -from [get_ports {cpu_a[*] cpu_rwb cpu_cs_n}] -to [get_clocks {system54}] -setup -end 6
set_multicycle_path -from [get_ports {cpu_a[*] cpu_rwb cpu_cs_n}] -to [get_clocks {system54}] -hold -end 5
# Write data: launched by the PHI2 rise (phase 8 edge), sampled at phase 13.
set_input_delay -clock [get_clocks {system54}] -max 54.000 [get_ports {cpu_d[*]}]
set_input_delay -clock [get_clocks {system54}] -min 13.000 [get_ports {cpu_d[*]}]
set_multicycle_path -from [get_ports {cpu_d[*]}] -to [get_clocks {system54}] -setup -end 5
set_multicycle_path -from [get_ports {cpu_d[*]}] -to [get_clocks {system54}] -hold -end 4
# Read data/OE: launched at the latest at phase 10, needed 15ns before the
# PHI2 fall at the CPU (phase 16) plus board delay.
set_output_delay -clock [get_clocks {system54}] -max 18.000 [get_ports {cpu_d[*]}]
set_output_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {cpu_d[*]}]
set_multicycle_path -from [get_clocks {system54}] -to [get_ports {cpu_d[*]}] -setup -end 6
set_multicycle_path -from [get_clocks {system54}] -to [get_ports {cpu_d[*]}] -hold -end 5
# Changed only in the PHI2-low phases 2/3, outside every CPU sampling window.
set_false_path -to [get_ports {cpu_irq_n cpu_reset_release}]
# pixel release -> system domain readiness synchronizer, first stage only.
set_false_path -to [get_pins {pixel_up_sync_0_s0/D}]
