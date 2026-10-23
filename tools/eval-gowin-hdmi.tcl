# SPDX-License-Identifier: Apache-2.0
# Execute in distinct build directories. Argument: dvi | hdmi | stream
set root [file normalize [file join [file dirname [info script]] ..]]
set mode [lindex $argv 0]
if {$mode ni {dvi hdmi stream}} { error "Expected dvi, hdmi or stream" }
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
set_option -verilog_std sysv2017
foreach path [glob [file join $root third_party hdl-util-hdmi src *.sv]] {
    set tail [file tail $path]
    if {$tail eq "serializer.sv"} { continue }
    if {$mode eq "stream" && $tail in {hdmi.sv packet_picker.sv audio_clock_regeneration_packet.sv}} { continue }
    add_file -type verilog $path
}
add_file -type verilog [file join $root rtl platform kagura_gowin_serializer.sv]
if {$mode eq "stream"} {
    foreach path {build/generated/kagura_hdmi_stream.sv rtl/memory/kagura_async_fifo.sv rtl/audio/kagura_audio_transport.sv rtl/hdmi/kagura_audio_packets.sv rtl/vdp/kagura_bar_pattern.sv rtl/vdp/kagura_video_source_bars.sv rtl/hdmi/kagura_hdmi_stream_eval.sv} {
        add_file -type verilog [file join $root $path]
    }
    set_option -top_module kagura_hdmi_stream_eval
} else {
    add_file -type verilog [file join $root rtl hdmi kagura_hdmi_eval.sv]
    set_option -top_module kagura_${mode}_eval
}
set_option -output_base_name kagura_${mode}_eval
run syn
