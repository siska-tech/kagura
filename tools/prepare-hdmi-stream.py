#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate a reviewable, narrowly patched HDMI core; never modify vendor files."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
vendor = root / 'third_party/hdl-util-hdmi'
manifest = json.loads((vendor / 'manifest.json').read_text())
original = (vendor / 'src/hdmi.sv').read_bytes()
expected = next(f['sha256'] for f in manifest['files'] if f['path'] == 'src/hdmi.sv')
if hashlib.sha256(original).hexdigest() != expected:
    raise SystemExit('Upstream hdmi.sv hash mismatch')
text = original.decode('utf-8')

def replace_once(old, new):
    global text
    if text.count(old) != 1:
        raise SystemExit(f'Expected exactly one patch anchor: {old!r}')
    text = text.replace(old, new, 1)

replace_once('module hdmi ', 'module kagura_hdmi_stream ')
replace_once('    input logic clk_audio,', '''    input logic sample_valid,
    input logic [31:0] sample_data,
    output wire sample_ready,''')
replace_once('    input logic [AUDIO_BIT_WIDTH-1:0] audio_sample_word [1:0],', '')
replace_once("                control_data = 6'd0;", "                control_data <= 6'd0;")
start = text.index('        packet_picker #(')
end = text.index('        logic [8:0] packet_data;', start)
text = text[:start] + '''        kagura_audio_packets #(.VIDEO_ID_CODE(VIDEO_ID_CODE), .CTS(int'(VIDEO_RATE / 1000.0))) audio_packets (
            .clk_pixel(clk_pixel), .reset(reset), .video_field_end(video_field_end),
            .packet_enable(packet_enable), .sample_valid(sample_valid),
            .sample_data(sample_data), .sample_ready(sample_ready),
            .header(header), .sub(sub));
''' + text[end:]
# Pipelined encoder (4-cycle latency) for 74.25MHz; equivalence is checked
# against the unchanged upstream tmds_channel by sim/tests/tb_tmds_pipeline.sv.
replace_once('        tmds_channel #(.CN(i)) tmds_channel (', '        kagura_tmds_channel #(.CN(i)) tmds_channel (')
# Same output sequence without the counter-indexed bit mux in front of the BCH
# update; checked against the upstream module by sim/tests/tb_packet_assembler.sv.
replace_once('        packet_assembler packet_assembler (', '        kagura_packet_assembler packet_assembler (')
# Predict the packet-start pulse one pixel ahead. The registered pulse is
# consumed at exactly the original cx, but the range/modulo decode no longer
# chains into the audio scheduler's count and packet-selection enables.
# START_X=0 in both board modes, so reset cannot start inside a packet.
replace_once('''        logic packet_enable;
        assign packet_enable = data_island_period_instantaneous && 5'(cx + screen_width + 18) == 5'd0;
''', '''        logic packet_enable = 0;
        always_ff @(posedge clk_pixel)
            if (reset) packet_enable <= 0;
            else packet_enable <= num_packets_alongside > 0 &&
                cx >= screen_width + 13 && cx < screen_width + 13 + num_packets_alongside * 32 &&
                5'(cx + screen_width + 19) == 5'd0;
''')
# The guard/preamble line test from a register. cy is constant from cx 1 to the
# end of the line (START_X is 0) and the test is used only at cx >= frame_width-10,
# so the output is unchanged; cy no longer feeds these flags combinationally.
replace_once('''        logic video_guard = 1;
        logic video_preamble = 0;
''', '''        logic video_guard = 1;
        logic video_preamble = 0;
        logic guard_line = 0;
        always_ff @(posedge clk_pixel) guard_line <= cy == frame_height - 1 || cy < screen_height - 1;
''')
replace_once('(cy == frame_height - 1 || cy < screen_height - 1 /* no VG at end of last line */)', 'guard_line /* no VG at end of last line */')
replace_once('(cy == frame_height - 1 || cy < screen_height - 1 /* no VP at end of last line */)', 'guard_line /* no VP at end of last line */')
# This generated variant is used only with HDMI enabled at the fixed mode.
text = ('// Modified for KAGURA-9: fixed VIC (1 or 4)/60Hz/48kHz/16bit sample-valid interface.\n'
        '// Derived from hdl-util/hdmi, Sameer Puri; Apache-2.0 option selected.\n'
        '// See third_party/hdl-util-hdmi/LICENSE-APACHE and manifest.json.\n' + text)
dest = root / 'build/generated/kagura_hdmi_stream.sv'
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(text, encoding='utf-8', newline='\n')
print(f'Prepared {dest}')
