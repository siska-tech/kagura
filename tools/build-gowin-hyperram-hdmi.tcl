# SPDX-License-Identifier: Apache-2.0
# Shared-PLL PSRAM + HDMI evaluation. Run in a separate build directory.
# Usage: gw_sh tools/build-gowin-hyperram-hdmi.tcl [480|720] [memtest|pcm]
set root [file normalize [file join [file dirname [info script]] ..]]
set mode [expr {[llength $argv] ? [lindex $argv 0] : "480"}]
if {$mode ni {480 720}} { error "Expected 480 or 720" }
set wide [expr {$mode eq "720"}]
set source [expr {[llength $argv]>1 ? [lindex $argv 1] : "memtest"}]
if {$source ni {memtest pcm}} { error "Expected memtest or pcm" }
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
set config [file join [pwd] kagura_build_config.sv]
set out [open $config w]
puts $out "package kagura_build_config; localparam integer VIDEO_ID_CODE=[expr {$wide ? 4 : 1}]; endpackage"
close $out
add_file -type verilog $config
foreach name {audio_info_frame audio_sample_packet auxiliary_video_information_info_frame packet_assembler source_product_description_info_frame tmds_channel} {
    add_file -type verilog [file join $root third_party hdl-util-hdmi src ${name}.sv]
}
foreach path {
    build/generated/kagura_hdmi_stream.sv
    rtl/memory/kagura_async_fifo.sv rtl/audio/kagura_audio_transport.sv
    rtl/audio/kagura_test_tone.sv rtl/hdmi/kagura_audio_packets.sv
    rtl/hdmi/kagura_tmds_channel.sv rtl/hdmi/kagura_hdmi_stream_eval.sv
    rtl/vdp/kagura_bar_pattern.sv rtl/vdp/kagura_video_source_bars.sv
    rtl/platform/kagura_gowin_serializer.sv rtl/platform/kagura_nano9k_clocks.sv
    rtl/memory/kagura_hyperram_ctrl.sv rtl/memory/kagura_hyperram_phy_gowin.sv
    boards/tang-nano-9k/kagura_hyperram_memtest.sv
    boards/tang-nano-9k/kagura_hyperram_hdmi_top.sv
} { add_file -type verilog [file join $root $path] }
if {$source eq "pcm"} {
    foreach path {
        rtl/audio/kagura_audio_synth.sv rtl/audio/kagura_pcm_prefetch.sv
        rtl/memory/kagura_psram_read_cdc.sv rtl/memory/kagura_psram_byte_bridge.sv
        rtl/memory/kagura_psram_read_path.sv rtl/memory/kagura_psram_arbiter.sv
        boards/tang-nano-9k/kagura_hyperram_pcm_source.sv
        boards/tang-nano-9k/kagura_pcm_uart_status.sv
        boards/tang-nano-9k/kagura_hyperram_pcm_top.sv
    } { add_file -type verilog [file join $root $path] }
}
proc merge {type names} {
    global root wide
    set path [file join [pwd] hyperram-hdmi.$type]
    set out [open $path w]
    foreach name $names {
        set in [open [file join $root boards tang-nano-9k $name] r]
        set text [read $in]
        close $in
        if {$wide} {
            set text [string map {{-multiply_by 14 -divide_by 3} {-multiply_by 55 -divide_by 4} serial126 serial371 pixel25 pixel74} $text]
        }
        puts $out $text
    }
    close $out
    add_file -type $type $path
}
merge cst {phase1.cst hyperram-uart.cst}
set constraints {phase1.sdc phase1-audio.sdc psram-ck.sdc hyperram-hdmi.sdc}
if {$wide} { lappend constraints phase1-720p.sdc }
if {$source eq "pcm"} { lappend constraints hyperram-pcm.sdc }
merge sdc $constraints
set_option -top_module kagura_hyperram_hdmi_top
set_option -output_base_name kagura_hyperram_hdmi$mode
if {$source eq "pcm"} {
    set_option -top_module kagura_hyperram_pcm_top
    set_option -output_base_name kagura_hyperram_pcm$mode
}
# 720p option 1 misses the system54 -> 67.5-degree PSRAM CK-enable setup
# path; option 0 passes with the same phase constraint (see docs/psram-pcm.md).
set_option -place_option [expr {$wide ? 0 : 1}]
set_option -route_option 1
if {[info exists ::env(KAGURA_PLACE_OPTION)]} { set_option -place_option $::env(KAGURA_PLACE_OPTION) }
if {[info exists ::env(KAGURA_ROUTE_OPTION)]} { set_option -route_option $::env(KAGURA_ROUTE_OPTION) }
set_option -bit_security 0
foreach pin {sspi mspi ready done cpu} { set_option -use_${pin}_as_gpio 1 }
run all
