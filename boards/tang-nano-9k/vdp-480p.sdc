# Line-handover payload into the 25.2MHz pixel domain (VIC1 builds), used
# after phase3-vdp.sdc: just under one pixel period (39.68ns).
set_max_delay 36.000 -from [get_pins {vdp/display/done_tag_*/Q}] -to [get_clocks {pixel25}]
# done_tag is held with done_toggle and sampled only after the toggle crosses
# two stages.  Preserve the setup max-delay and exclude asynchronous hold only.
set_false_path -hold -from [get_pins {vdp/display/done_tag_*/Q}] -to [get_clocks {pixel25}]
