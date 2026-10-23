// SPDX-License-Identifier: Apache-2.0
// Replacement for the upstream platform serializer. Never compile both.
module serializer #(
    parameter int NUM_CHANNELS = 3,
    parameter real VIDEO_RATE = 25.2e6
) (
    input wire clk_pixel, clk_pixel_x5, reset,
    input wire [9:0] tmds_internal [NUM_CHANNELS-1:0],
    output wire [2:0] tmds,
    output wire tmds_clock
);
    // Local reset fanout for the fast I/O domain; only this synchronizer
    // receives the asynchronous pixel-domain reset release.
    (* ASYNC_REG="TRUE" *) reg [1:0] serial_reset;
    // Third stage duplicated per OSER10, placed near each IOLOGIC site.
    // VIC1 keeps OSER10 RESET recovery/removal timing checks. VIC4 excludes
    // lane-copy -> OSER10 RESET paths in phase1-720p.sdc and treats release
    // at OSER10 as asynchronous; lane alignment needs hardware validation
    // (docs/timing.md, docs/wide-mode.md). [3] drives the clock lane.
    (* syn_preserve=1 *) reg [3:0] serial_reset_lane;
    always @(posedge clk_pixel_x5 or posedge reset)
        if(reset) begin serial_reset<=2'b11; serial_reset_lane<=4'hf; end
        else begin serial_reset<={serial_reset[0],1'b0}; serial_reset_lane<={4{serial_reset[1]}}; end
    genvar c;
    generate for (c=0;c<3;c=c+1) begin: lane
        OSER10 tx(.Q(tmds[c]), .PCLK(clk_pixel), .FCLK(clk_pixel_x5), .RESET(serial_reset_lane[c]),
            .D0(tmds_internal[c][0]), .D1(tmds_internal[c][1]),
            .D2(tmds_internal[c][2]), .D3(tmds_internal[c][3]),
            .D4(tmds_internal[c][4]), .D5(tmds_internal[c][5]),
            .D6(tmds_internal[c][6]), .D7(tmds_internal[c][7]),
            .D8(tmds_internal[c][8]), .D9(tmds_internal[c][9]));
    end endgenerate
    // Clock lane through IOLOGIC like the data lanes (5 high, 5 low bits),
    // instead of routing the fabric pixel clock to the output buffer.
    OSER10 clock_tx(.Q(tmds_clock), .PCLK(clk_pixel), .FCLK(clk_pixel_x5), .RESET(serial_reset_lane[3]),
        .D0(1'b1), .D1(1'b1), .D2(1'b1), .D3(1'b1), .D4(1'b1),
        .D5(1'b0), .D6(1'b0), .D7(1'b0), .D8(1'b0), .D9(1'b0));
endmodule
