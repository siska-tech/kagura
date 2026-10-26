# Line-handover payload into the 74.25MHz pixel domain (VIC4 builds), used
# after phase3-vdp.sdc: just under one pixel period (13.47ns).
set_max_delay 12.000 -from [get_pins {vdp/display/done_tag_*/Q}] -to [get_clocks {pixel74}]
# done_tag is held with done_toggle and sampled only after the toggle crosses
# two stages.  Preserve the setup max-delay and exclude asynchronous hold only.
set_false_path -hold -from [get_pins {vdp/display/done_tag_*/Q}] -to [get_clocks {pixel74}]
