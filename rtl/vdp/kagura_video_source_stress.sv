// SPDX-License-Identifier: Apache-2.0
// Resource/timing measurement video source (P1-05). Every RGB bit toggles, so
// synthesis keeps the full TMDS encoders that a VDP palette output will need;
// the two-level bars collapse most encoder logic into constants.
// Exactly one kagura_video_source_*.sv file is compiled per build.
module kagura_video_source #(
    parameter integer XW=10,
    parameter integer H_ACTIVE=640,
    parameter integer V_ACTIVE=480
) (
    input wire [XW-1:0] x, input wire [9:0] y,
    output wire [23:0] rgb
);
    assign rgb = {x[7:0], y[7:0], x[7:0] ^ y[7:0]};
endmodule
