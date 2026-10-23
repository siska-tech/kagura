# SPDX-License-Identifier: Apache-2.0
# Run from a per-variant build directory after tools/prepare-hdmi-stream.py.
# Arguments: [hdmi|dvi|phase2|demo|spi|qspi][720] [bars|stress]. Defaults build the flashable HDMI+audio
# colour-bar image; stress keeps all TMDS encoder logic for P1-05 measurement.
# A 720 suffix (not for dvi) builds the 16:9 mode: 1280x720p60, VIC4, 320x180
# logical screen (docs/wide-mode.md).
set root [file normalize [file join [file dirname [info script]] ..]]
set mode [expr {[llength $argv] > 0 ? [lindex $argv 0] : "hdmi"}]
set pattern [expr {[llength $argv] > 1 ? [lindex $argv 1] : "bars"}]
set wide [string match *720 $mode]
set base [regsub {720$} $mode ""]
if {$base ni {hdmi dvi phase2 demo spi qspi} || ($wide && $base eq "dvi")} {
    error "Expected hdmi, dvi, phase2, demo, spi or qspi, optionally with a 720 suffix (not dvi)"
}
if {$pattern ni {bars stress}} { error "Expected bars or stress" }
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
set cst {phase1.cst}
# Board tops take VIDEO_ID_CODE (and the host top LANES) from this package.
set config [file join [pwd] kagura_build_config.sv]
set out [open $config w]
puts $out "package kagura_build_config; localparam integer VIDEO_ID_CODE=[expr {$wide ? 4 : 1}]; localparam integer LANES=[expr {$base eq {qspi} ? 4 : 1}]; endpackage"
close $out
set vdp {rtl/audio/kagura_audio_registers.sv rtl/audio/kagura_audio_synth.sv rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_vram.sv rtl/core/kagura_command_queue.sv rtl/core/kagura_vram_engine.sv rtl/core/kagura_registers.sv rtl/core/kagura_core.sv rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_bg_renderer.sv rtl/vdp/kagura_sprite_selector.sv rtl/vdp/kagura_sprite_row.sv rtl/vdp/kagura_sprite_renderer.sv rtl/vdp/kagura_line_display.sv rtl/vdp/kagura_vdp.sv}
# Line-handover payload bound: just under one pixel period of the mode.
set vdp_sdc [list phase3-vdp.sdc [expr {$wide ? "vdp-720p.sdc" : "vdp-480p.sdc"}]]
if {$base in {hdmi phase2 demo spi qspi}} {
    set upstream {audio_info_frame audio_sample_packet auxiliary_video_information_info_frame packet_assembler source_product_description_info_frame tmds_channel}
    set local [list $config build/generated/kagura_hdmi_stream.sv rtl/memory/kagura_async_fifo.sv rtl/audio/kagura_audio_transport.sv rtl/audio/kagura_test_tone.sv rtl/hdmi/kagura_audio_packets.sv rtl/hdmi/kagura_tmds_channel.sv rtl/hdmi/kagura_hdmi_stream_eval.sv boards/tang-nano-9k/kagura_phase1_top.sv]
    set top kagura_phase1_top
    set sdc {phase1.sdc phase1-audio.sdc}
    if {$wide} { lappend sdc phase1-720p.sdc }
    if {$base eq "phase2"} {
        set local [concat $local $vdp rtl/bus/kagura_w65c02_adapter.sv boards/tang-nano-9k/kagura_phase2_top.sv]
        set top kagura_phase2_top
        set sdc [concat $sdc phase2-cpu.sdc $vdp_sdc]
        lappend cst phase2-cpu.cst
    }
    if {$base eq "demo"} {
        # No CPU pins: the demo sequencer drives the register window.
        set local [concat $local $vdp rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv boards/tang-nano-9k/kagura_demo_top.sv]
        set top kagura_demo_top
        set sdc [concat $sdc $vdp_sdc]
    }
    if {$base in {spi qspi}} {
        # Host adapter instead of the CPU bus.
        set local [concat $local $vdp rtl/bus/kagura_spi_adapter.sv boards/tang-nano-9k/kagura_host_top.sv]
        set top kagura_host_top
        set sdc [concat $sdc host.sdc $vdp_sdc]
        lappend cst host.cst
    }
} else {
    # Pinned upstream hdmi.sv with DVI_OUTPUT=1; packet modules stay unelaborated.
    set upstream {hdmi packet_picker audio_clock_regeneration_packet audio_info_frame audio_sample_packet auxiliary_video_information_info_frame packet_assembler source_product_description_info_frame tmds_channel}
    set local {rtl/hdmi/kagura_dvi_stream_eval.sv boards/tang-nano-9k/kagura_phase1_dvi_top.sv}
    set top kagura_phase1_dvi_top
    set sdc {phase1.sdc}
}
foreach name $upstream {
    add_file -type verilog [file join $root third_party hdl-util-hdmi src ${name}.sv]
}
foreach path [concat $local rtl/vdp/kagura_bar_pattern.sv rtl/vdp/kagura_video_source_${pattern}.sv {rtl/platform/kagura_gowin_serializer.sv rtl/platform/kagura_nano9k_clocks.sv}] {
    add_file -type verilog [file join $root $path]
}
# Gowin does not share clocks between SDC files, so concatenate them; CST
# fragments are merged the same way.
proc merge_into {path names} {
    global root wide
    set out [open $path w]
    foreach name $names {
        set in [open [file join $root boards tang-nano-9k $name] r]
        set text [read $in]
        # VIC4 clocks: same PLL/CLKDIV structure, other ratio and names.
        if {$wide} {
            set text [string map {{-multiply_by 14 -divide_by 3} {-multiply_by 55 -divide_by 4} serial126 serial371 pixel25 pixel74} $text]
        }
        puts $out $text
        close $in
    }
    close $out
}
merge_into [file join [pwd] kagura_${mode}.cst] $cst
merge_into [file join [pwd] kagura_${mode}.sdc] $sdc
add_file -type cst [file join [pwd] kagura_${mode}.cst]
add_file -type sdc [file join [pwd] kagura_${mode}.sdc]
set_option -top_module $top
set name [dict get {hdmi kagura_phase1 dvi kagura_phase1_dvi phase2 kagura_phase2 demo kagura_demo spi kagura_spi qspi kagura_qspi} $base]
if {$wide} { set name [expr {$base eq "hdmi" ? "kagura_hdmi720" : "${name}720"}] }
set_option -output_base_name $name
# 74.25MHz leaves a few tens of ps on the pixel paths; placement option 1
# closed demo720 where the default left -0.010ns (docs/wide-mode.md).
if {$wide} { set_option -place_option 1 }
# Optional P&R effort for exploration, e.g. KAGURA_PLACE_OPTION=1.
if {[info exists ::env(KAGURA_PLACE_OPTION)]} { set_option -place_option $::env(KAGURA_PLACE_OPTION) }
if {[info exists ::env(KAGURA_ROUTE_OPTION)]} { set_option -route_option $::env(KAGURA_ROUTE_OPTION) }
# Keep readback enabled so SRAM/embFlash programming can be verified.
set_option -bit_security 0
run all
