// SPDX-License-Identifier: Apache-2.0
// Standalone HDMI/48kHz test. No CPU connection is needed for this bitstream.
// VIDEO_ID_CODE 1: 640x480; 4: 1280x720 (the 16:9 physical-layer gate,
// docs/wide-mode.md). tools/build-nano9k.tcl writes kagura_build_config.
module kagura_phase1_top #(
    parameter integer VIDEO_ID_CODE=kagura_build_config::VIDEO_ID_CODE
) (
    input wire clk27, reset_n,
    output wire tmds_clk_p,tmds_clk_n,
    output wire [2:0] tmds_d_p,tmds_d_n,
    output wire [5:0] led_n
);
    wire pixel,serial,system_clk,pixel_lock,system_lock;
    kagura_nano9k_clocks #(.VIDEO_ID_CODE(VIDEO_ID_CODE)) clocks(clk27,reset_n,pixel,serial,system_clk,pixel_lock,system_lock,);
    wire release_ok=reset_n && pixel_lock && system_lock;
    (* ASYNC_REG="TRUE" *) reg [3:0] pixel_release,system_release;
    always @(posedge pixel or negedge release_ok)
        if(!release_ok) pixel_release<=0; else pixel_release<={pixel_release[2:0],1'b1};
    always @(posedge system_clk or negedge release_ok)
        if(!release_ok) system_release<=0; else system_release<={system_release[2:0],1'b1};
    wire valid,full,overflow,underflow,muted,tc;
    wire [2:0] tx;
    wire [15:0] left_sample,right_sample;
    kagura_test_tone tone(system_clk,~system_release[3],valid,left_sample,right_sample);
    kagura_hdmi_stream_eval #(.VIDEO_ID_CODE(VIDEO_ID_CODE)) link(system_clk,pixel,serial,~pixel_release[3],valid,
        {right_sample,left_sample},full,overflow,underflow,tx,tc,muted,24'h000000,,,);
    ELVDS_OBUF clock_buffer(.I(tc),.O(tmds_clk_p),.OB(tmds_clk_n));
    genvar i;
    generate for(i=0;i<3;i=i+1) begin: output_lane
        ELVDS_OBUF buffer_lane(.I(tx[i]),.O(tmds_d_p[i]),.OB(tmds_d_n[i]));
    end endgenerate
    assign led_n=~{pixel_lock,system_lock,overflow,underflow,muted,pixel_release[3]};
endmodule
