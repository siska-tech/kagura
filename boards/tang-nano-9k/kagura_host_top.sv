// SPDX-License-Identifier: Apache-2.0
// SPI / QSPI host board top (docs/host-interface.md): the Phase 2 VDP and
// HDMI stream, with kagura_spi_adapter in place of the W65C02S adapter.
// Instance names of the stream part match kagura_phase1_top so phase1.cst
// and phase1*.sdc apply. Pins reuse the 3.3V CPU header pins (host.cst).
// tools/build-nano9k.tcl writes kagura_build_config (LANES, VIDEO_ID_CODE).
module kagura_host_top #(
    parameter integer LANES=kagura_build_config::LANES,
    parameter integer VIDEO_ID_CODE=kagura_build_config::VIDEO_ID_CODE,
    localparam integer XW=VIDEO_ID_CODE==4 ? 11 : 10
) (
    input wire clk27, reset_n,
    output wire tmds_clk_p,tmds_clk_n,
    output wire [2:0] tmds_d_p,tmds_d_n,
    output wire [5:0] led_n,
    input wire host_sck, host_cs_n,
    inout wire [3:0] host_io,
    output wire host_busy, host_ready,
    output wire host_irq_n
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

    (* ASYNC_REG="TRUE" *) reg [1:0] pixel_up_sync;
    always @(posedge system_clk)
        if(!system_release[3]) pixel_up_sync<=0; else pixel_up_sync<={pixel_up_sync[0],pixel_release[3]};
    wire sys_reset=~system_release[3];
    wire req_valid,req_ready,req_write,rsp_valid,rsp_ready,rsp_error,irq,irq_drive,late;
    wire [4:0] req_addr;
    wire [7:0] req_wdata,rsp_rdata;
    wire [3:0] io_out,io_oe;
    wire [5:0] queue_free;
    wire vdp_ready,frame_ready;
    kagura_spi_adapter #(.LANES(LANES)) bus(.clk(system_clk),.reset(sys_reset),
        .spi_sck(host_sck),.spi_cs_n(host_cs_n),.spi_io_in(host_io),.spi_io_out(io_out),.spi_io_oe(io_oe),
        .busy(host_busy),.irq_drive(irq_drive),.irq_level(irq),.queue_free(queue_free),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.late(late));
    // CAPS: HDMI_AUDIO, WAVE, 16 sprites per line, WIDE for 320x180.
    wire [11:0] render_cycles;
    kagura_vdp #(.CAPS(VIDEO_ID_CODE==4 ? 8'h33 : 8'h13),.VIDEO_ID_CODE(VIDEO_ID_CODE)) vdp(.sys_clk(system_clk),.sys_reset(sys_reset),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.init_done(vdp_ready),.frame_ready(frame_ready),.render_cycles(render_cycles),
        .queue_free(queue_free),
        .audio_full(full),.audio_underflow_toggle(audio_uf_toggle),.audio_muted(muted),
        .audio_sample_valid(valid),.audio_left(left_sample),.audio_right(right_sample),.audio_status(audio_status),
        .pix_clk(pixel),.pix_reset(~pixel_release[3]),.cx(cx),.cy(cy),.rgb(vdp_rgb));
    // READY: memory/line initialization and the first line 0 are done.
    reg ready_q;
    always @(posedge system_clk) ready_q<=pixel_up_sync[1] && vdp_ready && frame_ready;
    assign host_ready=ready_q;
    generate for(i=0;i<4;i=i+1) begin: io_lane
        assign host_io[i]=io_oe[i] ? io_out[i] : 1'bz;
    end endgenerate
    assign host_irq_n=irq_drive ? 1'b0 : 1'bz;
    // LED1 shows the adapter deadline flag.
    assign led_n=~{pixel_lock,system_lock,audio_status[2],audio_status[1],late,pixel_release[3]};
endmodule

