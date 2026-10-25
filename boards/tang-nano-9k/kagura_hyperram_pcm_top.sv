// SPDX-License-Identifier: Apache-2.0
// Shared PLL, PSRAM upload/read path, two PCM loops under host traffic and HDMI audio.
// VIDEO_ID_CODE 1: 640x480; 4: 1280x720 (the 16:9 physical-layer gate,
// docs/wide-mode.md). tools/build-gowin-hyperram-hdmi.tcl writes the config.
module kagura_hyperram_pcm_top #(
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
    
    kagura_hdmi_stream_eval #(.VIDEO_ID_CODE(VIDEO_ID_CODE)) link(system_clk,pixel,serial,~pixel_release[3],valid,
        {right_sample,left_sample},full,overflow,underflow,tx,tc,muted,24'h000000,,,);
    ELVDS_OBUF clock_buffer(.I(tc),.O(tmds_clk_p),.OB(tmds_clk_n));
    genvar i;
    generate for(i=0;i<3;i=i+1) begin: output_lane
        ELVDS_OBUF buffer_lane(.I(tx[i]),.O(tmds_d_p[i]),.OB(tmds_d_n[i]));
    end endgenerate
    wire phy_reset_n,phy_cs_n,phy_ck_en,phy_dq_oe,phy_rwds_oe;
    wire phy_rwds_o_rise,phy_rwds_o_fall;
    wire [7:0] o_rise,o_fall,i_rise,i_fall;
    wire [31:0] checked_samples,read_bytes,data_errors,mix_errors,host_words,host_errors;
    wire [15:0] pcm_wait_max;
    wire [7:0] faults;
    wire [1:0] active;
    kagura_hyperram_pcm_source source(
        .clk(system_clk),.reset(~system_release[3]),.sample_valid(valid),
        .sample_left(left_sample),.sample_right(right_sample),
        .checked_samples,.read_bytes,.data_errors,.mix_errors,.host_words,.host_errors,.pcm_wait_max,
        .faults,.active,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,.phy_rwds_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),
        .phy_rwds_o_rise,.phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall));
    kagura_hyperram_phy_gowin phy(
        .clk(system_clk),.clk_ck(psram_ck),.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall),
        .phy_rwds_i_rise(),.phy_rwds_i_fall(),
        .O_psram_ck(O_psram_ck[0]),.O_psram_ck_n(O_psram_ck_n[0]),
        .O_psram_reset_n(O_psram_reset_n[0]),.O_psram_cs_n(O_psram_cs_n[0]),
        .IO_psram_rwds(IO_psram_rwds[0]),.IO_psram_dq(IO_psram_dq[7:0]));
    assign O_psram_ck[1]=0;
    assign O_psram_ck_n[1]=1;
    assign O_psram_reset_n[1]=0;
    assign O_psram_cs_n[1]=1;
    assign IO_psram_rwds[1]=1'bz;
    assign IO_psram_dq[15:8]=8'bz;

    // Underflow is sticky in the pixel domain; only its first stage is excepted.
    (* async_reg="true", syn_preserve=1 *) reg underflow_sync1,underflow_sync2;
    always @(posedge system_clk) begin
        if(!system_release[3]) begin underflow_sync1<=0; underflow_sync2<=0; end
        else begin underflow_sync1<=underflow; underflow_sync2<=underflow_sync1; end
    end
    kagura_pcm_uart_status status(
        .clk(system_clk),.reset(~system_release[3]),.checked_samples,.read_bytes,
        .data_errors,.mix_errors,.host_words,.host_errors,.pcm_wait_max,.faults,.active,
        .hdmi_errors({overflow,underflow_sync2}),.uart_tx);
    assign led_n=~{overflow,underflow_sync2,(|faults),(|data_errors)||(|host_errors),(|mix_errors),(&active)};
endmodule