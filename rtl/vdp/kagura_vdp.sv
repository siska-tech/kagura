// SPDX-License-Identifier: Apache-2.0
// VDP: system-domain core (registers, queue, VRAM, renderer) plus the line
// display in the pixel domain. cx/cy come from the HDMI timing core; rgb is
// aligned to them (two pixel clocks of internal latency are pre-compensated).
// VIDEO_ID_CODE 1: 320x240 on 640x480; 4: 320x180 on 1280x720.
module kagura_vdp #(
    parameter [7:0] CAPS=8'h00,
    parameter integer VIDEO_ID_CODE=1,
    parameter bit PSRAM_DEBUG=0,
    localparam integer XW=VIDEO_ID_CODE==4 ? 11 : 10
) (
    input wire sys_clk, sys_reset,
    input wire req_valid,
    output wire req_ready,
    input wire req_write,
    input wire [4:0] req_addr,
    input wire [7:0] req_wdata,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [7:0] rsp_rdata,
    output wire rsp_error,
    output wire irq,
    output wire init_done,
    output wire frame_ready,
    input wire audio_full,audio_underflow_toggle,audio_muted,
    output wire audio_sample_valid,
    output wire signed [15:0] audio_left,audio_right,
    output wire [7:0] audio_status,
    output wire [11:0] render_cycles,
    output wire [5:0] queue_free,
    input wire pix_clk, pix_reset,
    input wire [XW-1:0] cx,
    input wire [9:0] cy,
    output wire [23:0] rgb,
    // PSRAM PHY boundary (CAPS b3 only; see kagura_core)
    output wire psram_reset_n,psram_cs_n,psram_ck_en,psram_dq_oe,psram_rwds_oe,
    output wire [7:0] psram_dq_o_rise,psram_dq_o_fall,
    output wire psram_rwds_o_rise,psram_rwds_o_fall,
    output wire psram_dq_tx,psram_rwds_tx,
    input wire [7:0] psram_dq_i_rise,psram_dq_i_fall,
    input wire psram_rwds_i_rise,psram_rwds_i_fall
);
    wire render_start, line_write, render_done, vblank_start, vblank_live, underrun_event, line_start;
    wire [7:0] render_line, shown_line;
    wire [8:0] line_addr;
    wire [15:0] line_data,line_rdata;
    wire line_read;
    wire memory_ready,bank_ready;
    assign init_done=memory_ready && bank_ready;
    kagura_core #(.CAPS(CAPS),.LINES(VIDEO_ID_CODE==4 ? 180 : 240),.PSRAM_DEBUG(PSRAM_DEBUG)) core(.clk(sys_clk),.reset(sys_reset),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.init_done(memory_ready),
        .audio_full(audio_full),.audio_underflow_toggle(audio_underflow_toggle),.audio_muted(audio_muted),
        .audio_sample_valid(audio_sample_valid),.audio_left(audio_left),.audio_right(audio_right),.audio_status(audio_status),
        .render_start(render_start),.render_line(render_line),.line_write(line_write),
        .line_addr(line_addr),.line_data(line_data),.line_read(line_read),.line_rdata(line_rdata),.render_done(render_done),
        .vblank_start(vblank_start),.vblank_live(vblank_live),.underrun_event(underrun_event),
        .line_start(line_start),.shown_line(shown_line),.render_cycles(render_cycles),.queue_free(queue_free),
        .psram_reset_n(psram_reset_n),.psram_cs_n(psram_cs_n),.psram_ck_en(psram_ck_en),.psram_dq_oe(psram_dq_oe),
        .psram_rwds_oe(psram_rwds_oe),.psram_dq_o_rise(psram_dq_o_rise),.psram_dq_o_fall(psram_dq_o_fall),
        .psram_rwds_o_rise(psram_rwds_o_rise),.psram_rwds_o_fall(psram_rwds_o_fall),
        .psram_dq_tx(psram_dq_tx),.psram_rwds_tx(psram_rwds_tx),.psram_dq_i_rise(psram_dq_i_rise),.psram_dq_i_fall(psram_dq_i_fall),
        .psram_rwds_i_rise(psram_rwds_i_rise),.psram_rwds_i_fall(psram_rwds_i_fall));
    kagura_line_display #(.VIDEO_ID_CODE(VIDEO_ID_CODE)) display(.sys_clk(sys_clk),.sys_reset(sys_reset),
        .memory_ready(memory_ready),.line_init_done(bank_ready),.frame_ready(frame_ready),
        .render_start(render_start),.render_line(render_line),.line_write(line_write),
        .line_addr(line_addr),.line_data(line_data),.line_read(line_read),.line_rdata(line_rdata),.render_done(render_done),
        .vblank_start(vblank_start),.vblank_live(vblank_live),.underrun_event(underrun_event),
        .line_start(line_start),.shown_line(shown_line),
        .pix_clk(pix_clk),.pix_reset(pix_reset),.cx(cx),.cy(cy),.rgb(rgb));
endmodule
