// SPDX-License-Identifier: Apache-2.0
// External-clock evaluation top; no PLL/pin/PHY/STA completeness implied.
// EXTERNAL_RGB=0 draws kagura_video_source; 1 takes rgb_in, which must be
// aligned to cx_out/cy_out of the same cycle.
// VIDEO_ID_CODE 1 (640x480, 25.2MHz) or 4 (1280x720, 74.25MHz); the 48kHz
// tick is pixel*8/12375 for VIC4 and the coordinates widen to 11 bits.
module kagura_hdmi_stream_eval #(
    parameter bit EXTERNAL_RGB=0,
    parameter integer VIDEO_ID_CODE=1,
    localparam integer XW=VIDEO_ID_CODE==4 ? 11 : 10
) (
    input wire clk_system,clk_pixel,clk_pixel_x5,reset,
    input wire sample_valid,
    input wire [31:0] sample_data,
    output wire full,overflow,underflow,
    output wire [2:0] tmds,
    output wire tmds_clock,
    output wire muted,
    input wire [23:0] rgb_in,
    output wire [XW-1:0] cx_out,
    output wire [9:0] cy_out,
    output wire underflow_toggle
);
    localparam integer TICK_NUM=VIDEO_ID_CODE==4 ? 12375 : 525;
    localparam integer TICK_DEN=VIDEO_ID_CODE==4 ? 8 : 1;
    wire valid,ready;
    wire [31:0] pcm;
    wire [XW-1:0] x,fw,sw;
    wire [9:0] y,fh,sh;
    wire [23:0] rgb, pattern_rgb;
    generate if(!EXTERNAL_RGB) begin: internal
        kagura_video_source #(.XW(XW),.H_ACTIVE(VIDEO_ID_CODE==4 ? 1280 : 640),.V_ACTIVE(VIDEO_ID_CODE==4 ? 720 : 480))
            video(x,y,pattern_rgb);
    end else begin: external
        assign pattern_rgb=24'h000000;
    end endgenerate
    assign rgb=EXTERNAL_RGB ? rgb_in : pattern_rgb;
    assign cx_out=x;
    assign cy_out=y;
    kagura_audio_transport #(.TICK_NUM(TICK_NUM),.TICK_DEN(TICK_DEN)) audio_link(reset,clk_system,clk_pixel,
        sample_valid,sample_data,full,overflow,valid,pcm,ready,underflow,muted,underflow_toggle);
    kagura_hdmi_stream #(.VIDEO_ID_CODE(VIDEO_ID_CODE),.VIDEO_REFRESH_RATE(60.0),
        .DVI_OUTPUT(0),.AUDIO_RATE(48000),.AUDIO_BIT_WIDTH(16)) protocol (
        .clk_pixel(clk_pixel),.clk_pixel_x5(clk_pixel_x5),.reset(reset),
        .sample_valid(valid),.sample_data(pcm),.sample_ready(ready),
        .rgb(rgb),.tmds(tmds),.tmds_clock(tmds_clock),
        .cx(x),.cy(y),.frame_width(fw),.frame_height(fh),.screen_width(sw),.screen_height(sh));
endmodule
