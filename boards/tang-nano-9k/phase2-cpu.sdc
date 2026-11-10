# W65C02S bus I/O, used with phase1.sdc and phase1-audio.sdc by the Phase 2
# build. PHI2 is a system54 register output, so every CPU path is timed from
# system54 edges with multicycle counts taken from docs/timing.md. Delays (ns):
# PHI2 at the FPGA pin within PHI2_MAX = 16 after the ideal system54 edge,
# board 3 each way, W65C02S tADS/tMDS 40, external CS decode 10, read setup 15.
# PHI2_MAX is a budget, not an estimate: the cpu_phi2 output constraint below
# makes the STA fail when the implemented PHI2 path (PLL output latency, clock
# net, clk->Q, route, output buffer) exceeds it, and the input delays assume
# the same 16.  Gowin V1.9.12.04 (Standard) reported 14.27 (slow corner, 1.73
# slack) for phase2boot with these constraints, including the PLL output
# latency and the clock net; it replaces the earlier 2.70..4.39 figure.  An
# external PHI2 buffer on the carrier is not included; see docs/timing.md
# for the read hold check.
# Gowin applies multicycle paths that start at ports only with an explicit
# -to clock (and outputs with -from clock).
# PHI2 budget: required = edge + 18.518 - 2.518 = edge + PHI2_MAX (setup);
# PHI2 not before the edge (hold).  Ports carry no clock latency here.
set_output_delay -clock [get_clocks {system54}] -max 2.518 [get_ports {cpu_phi2}]
set_output_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {cpu_phi2}]
# A/RWB: launched by the PHI2 fall (phase 0 edge), sampled at phase 6.
# max = PHI2_MAX + board 3 + tADS 40 + board 3; min = board 3 + hold 10.
set_input_delay -clock [get_clocks {system54}] -max 62.000 [get_ports {cpu_a[*] cpu_rwb}]
set_input_delay -clock [get_clocks {system54}] -min 13.000 [get_ports {cpu_a[*] cpu_rwb}]
set_input_delay -clock [get_clocks {system54}] -max 72.000 [get_ports {cpu_cs_n}]
set_input_delay -clock [get_clocks {system54}] -min 13.000 [get_ports {cpu_cs_n}]
set_multicycle_path -from [get_ports {cpu_a[*] cpu_rwb cpu_cs_n}] -to [get_clocks {system54}] -setup -end 6
set_multicycle_path -from [get_ports {cpu_a[*] cpu_rwb cpu_cs_n}] -to [get_clocks {system54}] -hold -end 5
# Write data: launched by the PHI2 rise (phase 8 edge), sampled at phase 13.
# max = PHI2_MAX + board 3 + tMDS 40 + board 3.
set_input_delay -clock [get_clocks {system54}] -max 62.000 [get_ports {cpu_d[*]}]
set_input_delay -clock [get_clocks {system54}] -min 13.000 [get_ports {cpu_d[*]}]
set_multicycle_path -from [get_ports {cpu_d[*]}] -to [get_clocks {system54}] -setup -end 5
set_multicycle_path -from [get_ports {cpu_d[*]}] -to [get_clocks {system54}] -hold -end 4
# Read data/OE: launched at the latest at phase 10, needed 15ns before the
# PHI2 fall at the CPU (phase 16) plus board delay.  PHI2 is taken as early as
# the edge itself here (conservative for setup).  The read hold after the
# fall (OE released at phase 2) is not expressed here: Gowin pairs the hold
# check with the coincident edge; docs/timing.md gives the check.
set_output_delay -clock [get_clocks {system54}] -max 18.000 [get_ports {cpu_d[*]}]
set_output_delay -clock [get_clocks {system54}] -min 0.000 [get_ports {cpu_d[*]}]
set_multicycle_path -from [get_clocks {system54}] -to [get_ports {cpu_d[*]}] -setup -end 6
set_multicycle_path -from [get_clocks {system54}] -to [get_ports {cpu_d[*]}] -hold -end 5
# Changed only in the PHI2-low phases 2/3, outside every CPU sampling window.
set_false_path -to [get_ports {cpu_irq_n cpu_reset_release}]
# pixel release -> system domain readiness synchronizer, first stage only.
set_false_path -to [get_pins {pixel_up_sync_0_s0/D}]
