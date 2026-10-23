// SPDX-License-Identifier: Apache-2.0
// Display build video source: colour bars with a one pixel border.
// Exactly one kagura_video_source_*.sv file is compiled per build.
module kagura_video_source #(
    parameter integer XW=10,
    parameter integer H_ACTIVE=640,
    parameter integer V_ACTIVE=480
) (
    input wire [XW-1:0] x, input wire [9:0] y,
    output wire [23:0] rgb
);
    kagura_bar_pattern #(.XW(XW),.H_ACTIVE(H_ACTIVE),.V_ACTIVE(V_ACTIVE)) bars(x, y, rgb);
endmodule
