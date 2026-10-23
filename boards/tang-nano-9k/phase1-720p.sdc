# 1280x720p60 (VIC4) builds only, after phase1.sdc/phase1-audio.sdc with the
# clocks renamed to serial371/pixel74 by tools/build-nano9k.tcl.
# OSER10 reset release (one static edge once the clocks are stable): the
# FCLK synchronizer and its lane copies are placed next to the IOLOGIC
# sites (phase1.cst) and stay single-cycle paths. The lane copy -> OSER10
# RESET routing (1..5ns, varying per build) cannot be held inside the
# 1.347ns FCLK half period that its recovery check uses, so those checks are
# not analysed at VIC4: the release is treated as asynchronous to FCLK and
# PCLK, and lane alignment after reset is a hardware check item
# (docs/wide-mode.md). VIC1 builds keep every check.
set_false_path -from [get_pins {link/protocol/serializer/serial_reset_lane_*_s0/Q}] -to [get_pins {link/protocol/serializer/lane[*].tx/RESET link/protocol/serializer/clock_tx/RESET}]
