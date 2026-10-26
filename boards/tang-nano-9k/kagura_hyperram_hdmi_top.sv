// SPDX-License-Identifier: Apache-2.0
// Shared system PLL: full die-0 UART memtest alongside HDMI bars/48kHz tone.
// VIDEO_ID_CODE 1: 640x480; 4: 1280x720 (the 16:9 physical-layer gate,
// docs/video.md). tools/build-gowin-hyperram-hdmi.tcl writes the config.
module kagura_hyperram_hdmi_top #(
    parameter integer VIDEO_ID_CODE=kagura_build_config::VIDEO_ID_CODE
) (
    input wire clk27, reset_n,
    output wire tmds_clk_p,tmds_clk_n,
    output wire [2:0] tmds_d_p,tmds_d_n,
    output wire [5:0] led_n,
    output wire uart_tx,
    output wire [1:0] O_psram_ck, O_psram_ck_n, O_psram_reset_n, O_psram_cs_n,
    inout wire [1:0] IO_psram_rwds,
    inout wire [15:0] IO_psram_dq
);
    wire pixel,serial,system_clk,pixel_lock,system_lock,psram_ck;
    kagura_nano9k_clocks #(.VIDEO_ID_CODE(VIDEO_ID_CODE),.PSRAM_CK_ENABLE(1)) clocks(
        clk27,reset_n,pixel,serial,system_clk,pixel_lock,system_lock,psram_ck);
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
    wire [5:0] memory_led_n;
    kagura_hyperram_memtest test(
        .clk(system_clk),.clk_ck(psram_ck),.rst_n(system_release[3]),.psda(),
        .uart_tx,.led_n(memory_led_n),.O_psram_ck,.O_psram_ck_n,
        .IO_psram_rwds,.O_psram_reset_n,.IO_psram_dq,.O_psram_cs_n);
    // Low four LEDs retain the memtest meanings; high two show HDMI errors.
    assign led_n={~overflow,~underflow,memory_led_n[3:0]};
endmodule
