# SPDX-License-Identifier: Apache-2.0
# Run from a per-variant build directory after tools/prepare-hdmi-stream.py.
# Arguments: [hdmi|dvi|phase2|phase2boot|demo|spi|qspi|spipsram|qspipsram][720], bootprobe, or magicprobe.
# spipsram/qspipsram add the in-package PSRAM and PCM (CAPS b3, ABI 0.4).
# Defaults build the flashable HDMI+audio
# colour-bar image; stress keeps all TMDS encoder logic for P1-05 measurement.
# A 720 suffix (not for dvi) builds the 16:9 mode: 1280x720p60, VIC4, 320x180
# logical screen (docs/wide-mode.md).
set root [file normalize [file join [file dirname [info script]] ..]]
set build_dir [pwd]
if {[info exists ::env(KAGURA_BUILD_DIR)]} {
    set build_dir $::env(KAGURA_BUILD_DIR)
    file mkdir $build_dir
    cd $build_dir
}
set mode [expr {[llength $argv] > 0 ? [lindex $argv 0] : "hdmi"}]
set pattern [expr {[llength $argv] > 1 ? [lindex $argv 1] : "bars"}]
set wide [string match *720 $mode]
set base [regsub {720$} $mode ""]
if {$base ni {hdmi dvi phase2 phase2boot bootprobe magicprobe demo spi qspi spipsram qspipsram} ||
    ($wide && $base in {dvi bootprobe magicprobe})} {
    error "Expected hdmi, dvi, phase2, phase2boot, demo, spi, qspi, spipsram or qspipsram, optionally with a 720 suffix (not dvi), bootprobe, or magicprobe"
}
if {$pattern ni {bars stress}} { error "Expected bars or stress" }
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
set cst {phase1.cst}
# Board tops take VIDEO_ID_CODE (and the host top LANES) from this package.
set config [file join $build_dir kagura_build_config.sv]
set out [open $config w]
puts $out "package kagura_build_config; localparam integer VIDEO_ID_CODE=[expr {$wide ? 4 : 1}]; localparam integer LANES=[expr {$base in {qspi qspipsram} ? 4 : 1}]; localparam bit PSRAM=[expr {$base in {spipsram qspipsram} ? 1 : 0}]; localparam bit PSRAM_DEBUG=[expr {[info exists ::env(KAGURA_PSRAM_DEBUG)] ? 1 : 0}]; endpackage"
close $out
set vdp {rtl/audio/kagura_audio_registers.sv rtl/audio/kagura_audio_synth.sv rtl/memory/kagura_ram_sp.sv rtl/memory/kagura_ram_rmw16.sv rtl/vdp/kagura_vram.sv rtl/core/kagura_command_queue.sv rtl/core/kagura_vram_engine.sv rtl/core/kagura_registers.sv rtl/core/kagura_raster_scroll.sv rtl/core/kagura_core.sv rtl/memory/kagura_ram_tdp.sv rtl/vdp/kagura_bg_renderer.sv rtl/vdp/kagura_sprite_selector.sv rtl/vdp/kagura_sprite_row.sv rtl/vdp/kagura_sprite_renderer.sv rtl/vdp/kagura_line_display.sv rtl/vdp/kagura_vdp.sv rtl/audio/kagura_pcm_control.sv rtl/audio/kagura_pcm_prefetch.sv rtl/memory/kagura_psram_arbiter.sv rtl/memory/kagura_psram_read_path.sv rtl/memory/kagura_psram_read_cdc.sv rtl/memory/kagura_psram_byte_bridge.sv rtl/memory/kagura_hyperram_ctrl.sv}
# Line-handover payload bound: just under one pixel period of the mode.
set vdp_sdc [list phase3-vdp.sdc [expr {$wide ? "vdp-720p.sdc" : "vdp-480p.sdc"}]]
if {$base in {bootprobe magicprobe}} {
    set upstream {}
    set boot {rtl/boot/kagura_flash_reader.sv rtl/boot/kagura_boot_image_check.sv rtl/boot/kagura_boot_window.sv rtl/boot/kagura_boot_controller.sv}
    if {$base eq "bootprobe"} {
        set local [concat [list $config] $boot [list boards/tang-nano-9k/kagura_boot_probe_top.sv]]
        set top kagura_boot_probe_top
    } else {
        set local [list $config rtl/boot/kagura_flash_reader.sv boards/tang-nano-9k/kagura_flash_magic_probe_top.sv]
        set top kagura_flash_magic_probe_top
    }
    set cst {boot-probe.cst}
    set sdc {boot-probe.sdc}
    set_option -use_mspi_as_gpio 1
} elseif {$base in {hdmi phase2 phase2boot demo spi qspi spipsram qspipsram}} {
    set upstream {audio_info_frame audio_sample_packet auxiliary_video_information_info_frame packet_assembler source_product_description_info_frame tmds_channel}
    set local [list $config build/generated/kagura_hdmi_stream.sv rtl/memory/kagura_async_fifo.sv rtl/audio/kagura_audio_transport.sv rtl/audio/kagura_test_tone.sv rtl/hdmi/kagura_audio_packets.sv rtl/hdmi/kagura_tmds_channel.sv rtl/hdmi/kagura_packet_assembler.sv rtl/hdmi/kagura_hdmi_stream_eval.sv boards/tang-nano-9k/kagura_phase1_top.sv]
    set top kagura_phase1_top
    set sdc {phase1.sdc phase1-audio.sdc}
    if {$wide} { lappend sdc phase1-720p.sdc }
    if {$base eq "phase2"} {
        set local [concat $local $vdp rtl/bus/kagura_w65c02_adapter.sv boards/tang-nano-9k/kagura_phase2_top.sv]
        set top kagura_phase2_top
        set sdc [concat $sdc phase2-cpu.sdc $vdp_sdc]
        lappend cst phase2-cpu.cst
    }
    if {$base eq "phase2boot"} {
        set boot {rtl/boot/kagura_flash_reader.sv rtl/boot/kagura_boot_image_check.sv rtl/boot/kagura_boot_window.sv rtl/boot/kagura_boot_controller.sv}
        set local [concat $local $vdp rtl/bus/kagura_w65c02_adapter.sv $boot boards/tang-nano-9k/kagura_phase2_boot_top.sv]
        set top kagura_phase2_boot_top
        set sdc [concat $sdc phase2-cpu.sdc boot.sdc $vdp_sdc]
        lappend cst phase2-cpu.cst boot.cst
        set_option -use_mspi_as_gpio 1
    }
    if {$base eq "demo"} {
        # No CPU pins: the demo sequencer drives the register window.
        set local [concat $local $vdp rtl/core/kagura_demo_art.sv rtl/core/kagura_demo_sequencer.sv boards/tang-nano-9k/kagura_demo_top.sv]
        set top kagura_demo_top
        set sdc [concat $sdc $vdp_sdc]
    }
    if {$base in {spi qspi spipsram qspipsram}} {
        # Host adapter instead of the CPU bus.
        set local [concat $local $vdp rtl/bus/kagura_spi_adapter.sv rtl/memory/kagura_hyperram_phy_gowin.sv boards/tang-nano-9k/kagura_host_top.sv]
        set top kagura_host_top
        set sdc [concat $sdc host.sdc $vdp_sdc]
        if {$base in {spipsram qspipsram}} { lappend sdc psram-ck.sdc }
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
merge_into [file join $build_dir kagura_${mode}.cst] $cst
merge_into [file join $build_dir kagura_${mode}.sdc] $sdc
# Optional audit output: the default timing report lists only 25 paths even
# when more endpoints fail.  Keep this out of release builds unless requested.
if {[info exists ::env(KAGURA_TIMING_AUDIT)]} {
    set audit [open [file join $build_dir kagura_${mode}.sdc] a]
    puts $audit {report_timing -hold -max_paths 100 -max_common_paths 1}
    close $audit
}
add_file -type cst [file join $build_dir kagura_${mode}.cst]
add_file -type sdc [file join $build_dir kagura_${mode}.sdc]
set_option -top_module $top
set name [dict get {hdmi kagura_phase1 dvi kagura_phase1_dvi phase2 kagura_phase2 phase2boot kagura_phase2boot bootprobe kagura_boot_probe magicprobe kagura_flash_magic_probe demo kagura_demo spi kagura_spi qspi kagura_qspi spipsram kagura_spi_psram qspipsram kagura_qspi_psram} $base]
if {$wide} { set name [expr {$base eq "hdmi" ? "kagura_hdmi720" : "${name}720"}] }
set_option -output_base_name $name
# Integrated builds are placement-sensitive even at 54MHz: option 1 improves
# every measured configuration and raises the minimum setup slack from 0.063ns
# to 0.130ns (docs/timing.md).  Keep both stages explicit and reproducible.
set_option -place_option 1
set_option -route_option 1
# phase2boot720/demo720: the raster scroll table moved the upstream
# packet_assembler path (pixel74) to about -1.0/-0.56ns with option 1; option 0
# gives +0.16/+0.02ns.
if {$mode in {phase2boot720 demo720}} { set_option -place_option 0 }
# qspipsram720 remains the densest 720p build. Route option 2 keeps its pixel
# paths short; the PSRAM CK-enable crossing is handled structurally in the PHY.
if {$mode in {phase2boot720 qspipsram720}} { set_option -route_option 2 }
# Optional P&R overrides for controlled exploration.
if {[info exists ::env(KAGURA_PLACE_OPTION)]} { set_option -place_option $::env(KAGURA_PLACE_OPTION) }
if {[info exists ::env(KAGURA_ROUTE_OPTION)]} { set_option -route_option $::env(KAGURA_ROUTE_OPTION) }
# Optional post-P&R Verilog netlist for inspecting I/O packing.
if {[info exists ::env(KAGURA_SIM_NETLIST)]} { set_option -gen_verilog_sim_netlist 1; set_option -gen_sdf 1 }
# Keep readback enabled so SRAM/embFlash programming can be verified.
set_option -bit_security 0
run all
