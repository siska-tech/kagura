// SPDX-License-Identifier: Apache-2.0
// Phase 2/3 board top: the Phase 1 HDMI/48kHz stream showing the VDP picture
// (background layer), driven through the W65C02S bus adapter. Instance names
// of the stream part match kagura_phase1_top so phase1.cst/phase1*.sdc apply.
// VIDEO_ID_CODE comes from kagura_build_config (tools/build-nano9k.tcl).
// CPU pins follow boards/tang-nano-9k/pin-inventory.csv (3.3V banks only).
module kagura_phase2_top #(
    parameter integer VIDEO_ID_CODE=kagura_build_config::VIDEO_ID_CODE,
    localparam integer XW=VIDEO_ID_CODE==4 ? 11 : 10
) (
    input wire clk27, reset_n,
    output wire tmds_clk_p,tmds_clk_n,
    output wire [2:0] tmds_d_p,tmds_d_n,
    output wire [5:0] led_n,
    output wire cpu_phi2, cpu_reset_release,
    input wire [4:0] cpu_a,
    input wire cpu_cs_n, cpu_rwb,
    inout wire [7:0] cpu_d,
    output wire cpu_irq_n
);
    wire pixel,serial,system_clk,pixel_lock,system_lock;
    kagura_nano9k_clocks #(.VIDEO_ID_CODE(VIDEO_ID_CODE)) clocks(clk27,reset_n,pixel,serial,system_clk,pixel_lock,system_lock);
    wire release_ok=reset_n && pixel_lock && system_lock;
    (* ASYNC_REG="TRUE" *) reg [3:0] pixel_release,system_release;
    always @(posedge pixel or negedge release_ok)
        if(!release_ok) pixel_release<=0; else pixel_release<={pixel_release[2:0],1'b1};
    always @(posedge system_clk or negedge release_ok)
        if(!release_ok) system_release<=0; else system_release<={system_release[2:0],1'b1};
    wire valid,full,overflow,underflow,muted,tc,audio_uf_toggle;
    wire [7:0] audio_status;
    wire [2:0] tx;
    wire [15:0] left_sample,right_sample;
    wire [XW-1:0] cx;
    wire [9:0] cy;
    wire [23:0] vdp_rgb;
    kagura_hdmi_stream_eval #(.EXTERNAL_RGB(1),.VIDEO_ID_CODE(VIDEO_ID_CODE)) link(system_clk,pixel,serial,~pixel_release[3],valid,
        {right_sample,left_sample},full,overflow,underflow,tx,tc,muted,vdp_rgb,cx,cy,audio_uf_toggle);
    ELVDS_OBUF clock_buffer(.I(tc),.O(tmds_clk_p),.OB(tmds_clk_n));
    genvar i;
    generate for(i=0;i<3;i=i+1) begin: output_lane
        ELVDS_OBUF buffer_lane(.I(tx[i]),.O(tmds_d_p[i]),.OB(tmds_d_n[i]));
    end endgenerate

    // CPU release also waits for RAM/line initialization and first line 0.
    // Pixel-domain clock release crosses through this synchronizer.
    (* ASYNC_REG="TRUE" *) reg [1:0] pixel_up_sync;
    always @(posedge system_clk)
        if(!system_release[3]) pixel_up_sync<=0; else pixel_up_sync<={pixel_up_sync[0],pixel_release[3]};
    wire sys_reset=~system_release[3];
    wire req_valid,req_ready,req_write,rsp_valid,rsp_ready,rsp_error,irq,irq_drive,data_oe,late;
    wire [4:0] req_addr;
    wire [7:0] req_wdata,rsp_rdata,data_out;
    wire vdp_ready,frame_ready;
    kagura_w65c02_adapter bus(system_clk,sys_reset,pixel_up_sync[1] && vdp_ready && frame_ready,cpu_phi2,cpu_reset_release,
        cpu_a,cpu_cs_n,cpu_rwb,cpu_d,data_out,data_oe,irq_drive,irq,
        req_valid,req_ready,req_write,req_addr,req_wdata,rsp_valid,rsp_ready,rsp_rdata,rsp_error,late);
    // CAPS: HDMI_AUDIO, WAVE, 16 sprites per line, WIDE for 320x180.
    wire [11:0] render_cycles;
    kagura_vdp #(.CAPS(VIDEO_ID_CODE==4 ? 8'h33 : 8'h13),.VIDEO_ID_CODE(VIDEO_ID_CODE)) vdp(.sys_clk(system_clk),.sys_reset(sys_reset),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.init_done(vdp_ready),.frame_ready(frame_ready),.render_cycles(render_cycles),
        .audio_full(full),.audio_underflow_toggle(audio_uf_toggle),.audio_muted(muted),
        .audio_sample_valid(valid),.audio_left(left_sample),.audio_right(right_sample),.audio_status(audio_status),
        .pix_clk(pixel),.pix_reset(~pixel_release[3]),.cx(cx),.cy(cy),.rgb(vdp_rgb));
    assign cpu_d=data_oe ? data_out : 8'hzz;
    assign cpu_irq_n=irq_drive ? 1'b0 : 1'bz;
    // LED1 now shows the bus deadline flag instead of audio mute.
    assign led_n=~{pixel_lock,system_lock,audio_status[2],audio_status[1],late,pixel_release[3]};
endmodule
