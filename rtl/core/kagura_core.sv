// SPDX-License-Identifier: Apache-2.0
// System-domain core behind the CPU-independent request interface:
// register window -> command queue -> VRAM engine -> VRAM, plus the
// background renderer and the active (COMMITted) display state.
// The line display block (pixel domain) connects through the render_* and
// video event ports. Background is followed by an optional sprite pass.
module kagura_core #(
    parameter [7:0] CAPS=8'h00,
    parameter integer LINES=240       // logical lines per frame (180 for 16:9)
) (
    input wire clk, reset,
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
    input wire audio_full,audio_underflow_toggle,audio_muted,
    output wire audio_sample_valid,
    output wire signed [15:0] audio_left,audio_right,
    output wire [7:0] audio_status,
    // line display (system side)
    input wire render_start,
    input wire [7:0] render_line,
    output wire line_write,
    output wire [8:0] line_addr,
    output wire [15:0] line_data,
    output wire line_read,
    input wire [15:0] line_rdata,
    output wire render_done,
    input wire vblank_start,
    input wire vblank_live,
    input wire underrun_event,
    input wire line_start,
    input wire [7:0] shown_line,
    output wire [11:0] render_cycles,
    output wire [5:0] queue_free      // free command entries (host BUSY pin)
);
    wire push, push_ready, queue_idle, queue_staging, head_valid, pop, engine_busy;
    wire [63:0] push_desc, head;
    wire read_done, fence_done, commit_done;
    wire [7:0] read_data, fence_tag;
    wire [39:0] commit_snapshot;
    wire vram_valid, vram_ready, vram_write, vram_word, vram_rsp_valid;
    wire [15:0] vram_addr, vram_wdata, vram_rdata;
    wire [2:0] display_ctrl;
    wire [8:0] scroll_x;
    wire [7:0] scroll_y, backdrop, raster_line;
    wire [7:0] audio_index,audio_rdata,audio_wdata;
    wire audio_read_legal,audio_write_legal,audio_settings_valid,audio_busy;
    wire audio_index_write,audio_data_write,audio_capture;
    wire audio_apply_valid,audio_apply_ready,audio_apply_done,audio_commit_done,audio_apply_error;
    wire [143:0] audio_steps;
    wire [23:0] audio_duties;
    wire [47:0] audio_l,audio_r;
    wire [5:0] audio_enable,audio_resets;
    wire [7:0] audio_lengths,audio_master;
    wire [15:0] audio_period;
    wire wave_read,wave_swap,vram_idle;
    wire [8:0] wave_addr;
    wire signed [7:0] wave_data;
    (* ASYNC_REG="TRUE" *) reg [1:0] audio_uf_sync,audio_mute_sync;
    reg audio_uf_seen;
    always @(posedge clk)
        if(reset) begin audio_uf_sync<=0; audio_mute_sync<=3; audio_uf_seen<=0; end
        else begin
            audio_uf_sync<={audio_uf_sync[0],audio_underflow_toggle}; audio_uf_seen<=audio_uf_sync[1];
            audio_mute_sync<={audio_mute_sync[0],audio_muted};
        end
    wire audio_underflow_event=audio_uf_sync[1]!=audio_uf_seen;
    wire audio_overflow_event=audio_sample_valid && audio_full;
    kagura_audio_registers audio_registers(.clk(clk),.reset(reset),.index_write(audio_index_write),.data_write(audio_data_write),
        .wdata(audio_wdata),.index(audio_index),.rdata(audio_rdata),.read_legal(audio_read_legal),.write_legal(audio_write_legal),
        .settings_valid(audio_settings_valid),.capture(audio_capture),.commit_done(audio_commit_done),.apply_busy(audio_busy),
        .underflow_event(audio_underflow_event),.overflow_event(audio_overflow_event),.muted(audio_mute_sync[1]),.status(audio_status),
        .snapshot_step(audio_steps),.snapshot_duty(audio_duties),.snapshot_l(audio_l),.snapshot_r(audio_r),
        .snapshot_enable(audio_enable),.snapshot_reset(audio_resets),.snapshot_len(audio_lengths),.snapshot_master(audio_master),.snapshot_period(audio_period));
    kagura_audio_synth #(.EXTERNAL_SNAPSHOT(1)) audio_synth(.clk(clk),.reset(reset),.apply_valid(audio_apply_valid),.apply_ready(audio_apply_ready),
        .cfg_step(audio_steps),.cfg_duty(audio_duties),.cfg_gain_l(audio_l),.cfg_gain_r(audio_r),.cfg_enable(audio_enable),
        .cfg_phase_reset(audio_resets),.cfg_wave_len(audio_lengths),.cfg_master(audio_master),.cfg_noise_period(audio_period),
        .apply_done(audio_apply_done),.apply_error(audio_apply_error),.apply_busy(),.wave_read(wave_read),.wave_addr(wave_addr),
        .wave_data(wave_data),.sample_valid(audio_sample_valid),.sample_left(audio_left),.sample_right(audio_right),.last_cycles(),.apply_boundary(wave_swap),.sample_boundary(),
        .pcm_sample0(8'sd0),.pcm_sample1(8'sd0),.cfg_pcm_gain_l(16'b0),.cfg_pcm_gain_r(16'b0),.cfg_pcm_enable(2'b0));

    // Active display state, replaced only when a COMMIT completes.
    reg [2:0] active_display;
    reg [8:0] active_scroll_x;
    reg [7:0] active_scroll_y, active_backdrop, active_raster;
    always @(posedge clk)
        if(reset) begin
            active_display<=0; active_scroll_x<=0; active_scroll_y<=0; active_backdrop<=0; active_raster<=8'd255;
        end else if(commit_done) begin
            // snapshot = {backdrop, raster_line, 4'b0, display_ctrl, scroll_x, scroll_y}
            active_scroll_y<=commit_snapshot[7:0];
            active_scroll_x<=commit_snapshot[16:8];
            active_display<=commit_snapshot[19:17];
            active_raster<=commit_snapshot[31:24];
            active_backdrop<=commit_snapshot[39:32];
        end
    // RASTER: once, when the matching logical line starts showing (0..LINES-1).
    wire raster_event=line_start && shown_line==active_raster && active_raster<8'(LINES);
    wire [3:0] rs_count;
    wire [199:0] rs_table;
    wire bg_start;
    wire [8:0] bg_scroll_x;
    wire [7:0] bg_scroll_y;

    kagura_registers #(.CAPS(CAPS),.LINES(LINES)) registers(
        .clk(clk),.reset(reset),.init_done(init_done),.vblank_live(vblank_live),
        .irq_events({7'b0,vblank_start} | {6'b0,raster_event,1'b0} | {2'b00,sp_done && sp_overflow,5'b0}),
        .sprite_overflow_index(sp_overflow_index),.sprite_overflow_line(sp_overflow_line),
        .error_events({1'b0,audio_underflow_event || audio_overflow_event,underrun_event && init_done,5'b0}),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),
        .req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(rsp_ready),
        .rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.irq(irq),
        .push(push),.push_desc(push_desc),.push_ready(push_ready),.queue_free(queue_free),
        .queue_idle(queue_idle),.queue_staging(queue_staging),.engine_busy(engine_busy),
        .read_done(read_done),.read_data(read_data),
        .fence_done(fence_done),.fence_tag(fence_tag),.commit_done(commit_done),.display_ctrl(display_ctrl),
        .audio_index(audio_index),.audio_rdata(audio_rdata),.audio_read_legal(audio_read_legal),.audio_write_legal(audio_write_legal),
        .audio_settings_valid(audio_settings_valid),.audio_busy(audio_busy),.audio_index_write(audio_index_write),
        .audio_data_write(audio_data_write),.audio_capture(audio_capture),.audio_wdata(audio_wdata),
        .scroll_x(scroll_x),.scroll_y(scroll_y),.backdrop(backdrop),.raster_line(raster_line),
        .rs_count(rs_count),.rs_table(rs_table));
    kagura_raster_scroll raster_scroll(.clk(clk),.reset(reset),.start(render_start && init_done),.line(render_line),
        .frame_x(active_scroll_x),.frame_y(active_scroll_y),.load(commit_done),.count_in(rs_count),.table_in(rs_table),
        .start_o(bg_start),.x_o(bg_scroll_x),.y_o(bg_scroll_y));
    kagura_command_queue queue(.clk(clk),.reset(reset),.push(push),.push_desc(push_desc),
        .push_ready(push_ready),.free(queue_free),.idle(queue_idle),.staging(queue_staging),
        .head_valid(head_valid),.head(head),.pop(pop));
    kagura_vram_engine engine(.clk(clk),.reset(reset),.head_valid(head_valid),.head(head),.pop(pop),
        .busy(engine_busy),.vblank_start(vblank_start),
        .vram_valid(vram_valid),.vram_ready(vram_ready),.vram_write(vram_write),.vram_word(vram_word),
        .vram_addr(vram_addr),.vram_wdata(vram_wdata),.vram_rsp_valid(vram_rsp_valid),
        .vram_rdata(vram_rdata),.read_done(read_done),.read_data(read_data),
        .fence_done(fence_done),.fence_tag(fence_tag),
        .commit_done(commit_done),.commit_snapshot(commit_snapshot),.vram_idle(vram_idle),
        .audio_apply_ready(audio_apply_ready),.audio_apply_done(audio_apply_done),.audio_apply_valid(audio_apply_valid),.audio_commit_done(audio_commit_done));

    wire render_hold, render_grant, map_read, pattern_read, palette_read;
    wire bg_hold,bg_done,sp_hold,sp_done,sp_overflow;
    wire [5:0] sp_overflow_index;
    wire [7:0] sp_overflow_line;
    reg rendering,use_sprites;
    reg [11:0] elapsed,last_cycles;
    assign render_cycles=rendering ? elapsed : last_cycles;
    always @(posedge clk)
        if(reset) begin rendering<=0; use_sprites<=0; elapsed<=0; last_cycles<=0; end
        else if(render_start && init_done) begin rendering<=1; use_sprites<=active_display[0] && active_display[2]; elapsed<=0; end
        else if(rendering) begin
            elapsed<=elapsed+1'b1;
            if(render_done) begin rendering<=0; last_cycles<=elapsed; end
        end
    // One owner flag spans both passes, avoiding the pass-selection mux in
    // the high-fanout RAM grant/address path. It drops only after final done.
    assign render_hold=rendering;
    assign render_done=(bg_done && !use_sprites) || sp_done;
    wire bg_pr,bg_pal,sp_pr,sp_pal,bg_lw,sp_lw;
    wire [14:0] bg_pa,sp_pa;
    wire [9:0] bg_pi,sp_pi;
    wire [8:0] bg_la,sp_la;
    wire [15:0] bg_ld,sp_ld;
    wire oam_read;
    wire [9:0] oam_index;
    assign pattern_read=sp_hold ? sp_pr : bg_pr;
    assign pattern_addr=sp_hold ? sp_pa : bg_pa;
    assign palette_read=sp_hold ? sp_pal : bg_pal;
    assign palette_index=sp_hold ? sp_pi : bg_pi;
    assign line_write=sp_hold ? sp_lw : bg_lw;
    assign line_addr=sp_hold ? sp_la : bg_la;
    assign line_data=sp_hold ? sp_ld : bg_ld;
    wire [10:0] map_index;
    wire [14:0] pattern_addr;
    wire [9:0] palette_index;
    wire [15:0] map_data, palette_data, oam_data;
    wire [7:0] pattern_data;
    kagura_vram vram(.clk(clk),.reset(reset),.init_done(init_done),.valid(vram_valid),.ready(vram_ready),.write_in(vram_write),
        .command_idle(vram_idle),.audio_wave_read(wave_read),.audio_wave_addr(wave_addr),.audio_wave_swap(wave_swap),.audio_wave_data(wave_data),
        .word_in(vram_word),.addr_in(vram_addr),.wdata_in(vram_wdata),.rsp_valid(vram_rsp_valid),.rdata(vram_rdata),
        .render_hold(render_hold),.render_grant(render_grant),
        .map_read(map_read),.map_index(map_index),.map_data(map_data),
        .pattern_read(pattern_read),.pattern_addr(pattern_addr),.pattern_data(pattern_data),
        .palette_read(palette_read),.palette_index(palette_index),.palette_data(palette_data),
        .oam_read(oam_read),.oam_index(oam_index),.oam_data(oam_data));
    kagura_bg_renderer renderer(.clk(clk),.reset(reset),.start(bg_start),.line(render_line),
        .display_enable(active_display[0]),.bg_enable(active_display[1]),
        .scroll_x(bg_scroll_x),.scroll_y(bg_scroll_y),.backdrop(active_backdrop),
        .render_hold(bg_hold),.render_grant(render_grant),
        .map_read(map_read),.map_index(map_index),.map_data(map_data),
        .pattern_read(bg_pr),.pattern_addr(bg_pa),.pattern_data(pattern_data),
        .palette_read(bg_pal),.palette_index(bg_pi),.palette_data(palette_data),
        .line_write(bg_lw),.line_addr(bg_la),.line_data(bg_ld),
        .done(bg_done),.cycles());
    kagura_sprite_renderer sprites(.clk(clk),.reset(reset),.start(bg_done && use_sprites),.line(render_line),
        .render_hold(sp_hold),.render_grant(render_grant),.oam_read(oam_read),.oam_index(oam_index),.oam_data(oam_data),
        .pattern_read(sp_pr),.pattern_addr(sp_pa),.pattern_data(pattern_data),
        .palette_read(sp_pal),.palette_index(sp_pi),.palette_data(palette_data),
        .line_read(line_read),.line_write(sp_lw),.line_addr(sp_la),.line_data(sp_ld),.line_rdata(line_rdata),
        .done(sp_done),.overflow(sp_overflow),.overflow_index(sp_overflow_index),.overflow_line(sp_overflow_line));
// synthesis translate_off
    always @(posedge clk) if(!reset && audio_apply_error) $fatal(1,"validated audio snapshot rejected by synthesizer");
// synthesis translate_on
endmodule
