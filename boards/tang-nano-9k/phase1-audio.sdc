# Audio FIFO CDC exceptions; used with phase1.sdc by the HDMI+audio build only.
# Gray pointer buses: bound every first-stage input below the fastest source
# period (18.518ns). Do not false-path the bus or second synchronizer stage.
set_max_delay 10.000 -from [get_clocks {system54}] -to [get_pins {link/audio_link/fifo/wg_sync1_*/D}]
set_max_delay 10.000 -from [get_clocks {pixel25}] -to [get_pins {link/audio_link/fifo/rg_sync1_*/D}]
# These first synchronizer stages deliberately sample asynchronous Gray buses.
# Keep the setup-side absolute delay bound above, but do not apply a
# phase-related hold/removal check between the independent PLL domains.
set_false_path -hold -from [get_clocks {system54}] -to [get_pins {link/audio_link/fifo/wg_sync1_*/D}]
set_false_path -hold -from [get_clocks {pixel25}] -to [get_pins {link/audio_link/fifo/rg_sync1_*/D}]
# Only the asynchronous preset inputs of the reset synchronizer are excepted.
set_false_path -to [get_pins {link/audio_link/fifo/wr_reset_*_s0/PRESET}]
