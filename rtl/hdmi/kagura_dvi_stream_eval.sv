// SPDX-License-Identifier: Apache-2.0
// DVI-only comparison core for P1-05: pinned upstream hdmi with DVI_OUTPUT=1,
// same video source and serializer as the HDMI+audio stream, no audio path.
module kagura_dvi_stream_eval (
    input wire clk_pixel,clk_pixel_x5,reset,
    output wire [2:0] tmds,
    output wire tmds_clock
);
    wire [9:0] x,y,fw,fh,sw,sh;
    wire [23:0] rgb;
    wire [15:0] silence [1:0];
    assign silence[0]=0;
    assign silence[1]=0;
    kagura_video_source video(x,y,rgb);
    hdmi #(.VIDEO_ID_CODE(1),.VIDEO_REFRESH_RATE(60.0),.DVI_OUTPUT(1)) protocol (
        .clk_pixel(clk_pixel),.clk_pixel_x5(clk_pixel_x5),.clk_audio(1'b0),
        .reset(reset),.rgb(rgb),.audio_sample_word(silence),
        .tmds(tmds),.tmds_clock(tmds_clock),
        .cx(x),.cy(y),.frame_width(fw),.frame_height(fh),.screen_width(sw),.screen_height(sh));
endmodule
