# VDP line display CDC (kagura_line_display), used by the phase2 build.
# Toggles: bound the first synchronizer stage like the FIFO Gray pointers.
set_max_delay 10.000 -from [get_clocks {pixel25}] -to [get_pins {vdp/display/req_sync_0_s0/D vdp/display/vblank_sync_0_s0/D vdp/display/underrun_sync_0_s0/D vdp/display/live_sync_0_s0/D}]
set_max_delay 10.000 -from [get_clocks {system54}] -to [get_pins {vdp/display/done_sync_0_s0/D}]
set_max_delay 10.000 -from [get_clocks {system54}] -to [get_pins {vdp/display/memory_up_sync_0_s0/D}]
set_max_delay 10.000 -from [get_clocks {pixel25}] -to [get_pins {vdp/display/scan_quiet_sync_0_s0/D}]
set_max_delay 10.000 -from [get_clocks {pixel25}] -to [get_pins {vdp/core/audio_uf_sync_0_s0/D vdp/core/audio_mute_sync_0_s0/D}]
# Payloads change together with their toggle and are used only after the
# toggle has crossed two synchronizer stages (>= 2 destination cycles), so
# one destination period less margin bounds them; they are not false paths.
# The pixel-side bound (done_tag) is in vdp-480p.sdc / vdp-720p.sdc.
set_max_delay 18.000 -from [get_pins {vdp/display/req_line_*/Q vdp/display/req_bank*/Q}] -to [get_clocks {system54}]
