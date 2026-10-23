# SPI / QSPI host pins, used with phase1.sdc, phase1-audio.sdc and
# phase3-vdp.sdc. SCK, /CS and IO are asynchronous to system54 and enter
# 2FF synchronizers only; the protocol timing is set by oversampling
# (docs/host-interface.md), not by STA against SCK. Outputs are system54
# registers whose clock-to-out is part of that arithmetic; read it from the
# P&R port timing report.
set_false_path -from [get_ports {host_sck host_cs_n host_io[*]}]
set_false_path -to [get_ports {host_io[*] host_busy host_ready host_irq_n}]
# pixel release -> system domain readiness synchronizer, first stage only.
set_false_path -to [get_pins {pixel_up_sync_0_s0/D}]
