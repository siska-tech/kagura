// SPDX-License-Identifier: Apache-2.0
// Synthesis diagnostic only: external clocks/PCM, upstream audio CDC unchanged.
// No PLL, board pin assignment or KAGURA audio FIFO is implied by this top.
module kagura_hdmi_eval #(
    parameter bit DVI = 0
) (
    input wire clk_pixel, clk_pixel_x5, clk_audio, reset,
    input wire [15:0] pcm_left, pcm_right,
    output wire [2:0] tmds,
    output wire tmds_clock
);
    wire [9:0] x,y,fw,fh,sw,sh;
    wire [15:0] pcm [1:0];
    assign pcm[0]=pcm_left;
    assign pcm[1]=pcm_right;
    wire [23:0] rgb = {x[7:0], y[7:0], 8'h80};
    hdmi #(.VIDEO_ID_CODE(1), .VIDEO_REFRESH_RATE(60.0), .DVI_OUTPUT(DVI),
        .AUDIO_RATE(48000), .AUDIO_BIT_WIDTH(16)) protocol (
        .clk_pixel(clk_pixel), .clk_pixel_x5(clk_pixel_x5), .clk_audio(clk_audio),
        .reset(reset), .rgb(rgb), .audio_sample_word(pcm),
        .tmds(tmds), .tmds_clock(tmds_clock), .cx(x), .cy(y),
        .frame_width(fw), .frame_height(fh), .screen_width(sw), .screen_height(sh));
endmodule

module kagura_dvi_eval (
    input wire clk_pixel, clk_pixel_x5, clk_audio, reset,
    input wire [15:0] pcm_left, pcm_right,
    output wire [2:0] tmds,
    output wire tmds_clock
);
    kagura_hdmi_eval #(.DVI(1)) diagnostic (.*);
endmodule
