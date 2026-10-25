// SPDX-License-Identifier: Apache-2.0
// System-domain core behind the CPU-independent request interface:
// register window -> command queue -> VRAM engine -> VRAM, plus the
// background renderer and the active (COMMITted) display state.
// The line display block (pixel domain) connects through the render_* and
// video event ports. Background is followed by an optional sprite pass.
// CAPS b3 (ABI 0.4) adds the PSRAM region and two PCM channels: the vendor-
// neutral HyperRAM controller, host/PCM arbiter, PCM read path, prefetcher
// and PCM control live here; only the byte-pair PHY boundary (psram_*) leaves
// the core. Without b3 those ports are constant and their inputs unused.
module kagura_core #(
    parameter [7:0] CAPS=8'h00,
    parameter integer LINES=240,      // logical lines per frame (180 for 16:9)
    // PSRAM controller timing at system 54MHz (hardware: 14 / 6, rtl/README.md)
    parameter integer PSRAM_LAT=14,
    parameter integer PSRAM_RDL=6,
    parameter integer PSRAM_INIT_CYCLES=4096
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
    output wire [5:0] queue_free,     // free command entries (host BUSY pin)
    // PSRAM PHY boundary (kagura_hyperram_phy_gowin), CAPS b3 only
    output wire psram_reset_n,psram_cs_n,psram_ck_en,psram_dq_oe,psram_rwds_oe,
    output wire [7:0] psram_dq_o_rise,psram_dq_o_fall,
    output wire psram_rwds_o_rise,psram_rwds_o_fall,
    input wire [7:0] psram_dq_i_rise,psram_dq_i_fall
);
    localparam PSRAM=CAPS[3];
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
    wire [47:0] pcm_start,pcm_end,pcm_loop;
    wire [1:0] pcm_loop_enable,pcm_prepare,pcm_stop,pcm_clear,pcm_commit_enable;
    wire [15:0] pcm_status,pcm_gain_l,pcm_gain_r;
    wire signed [7:0] pcm_sample0,pcm_sample1;
    wire sample_boundary,audio_settle;
    kagura_audio_registers #(.PCM(PSRAM)) audio_registers(.clk(clk),.reset(reset),.index_write(audio_index_write),.data_write(audio_data_write),
        .wdata(audio_wdata),.index(audio_index),.rdata(audio_rdata),.read_legal(audio_read_legal),.write_legal(audio_write_legal),
        .settings_valid(audio_settings_valid),.capture(audio_capture),.commit_done(audio_commit_done),.apply_busy(audio_busy),
        .underflow_event(audio_underflow_event),.overflow_event(audio_overflow_event),.muted(audio_mute_sync[1]),.status(audio_status),
        .snapshot_step(audio_steps),.snapshot_duty(audio_duties),.snapshot_l(audio_l),.snapshot_r(audio_r),
        .snapshot_enable(audio_enable),.snapshot_reset(audio_resets),.snapshot_len(audio_lengths),.snapshot_master(audio_master),.snapshot_period(audio_period),
        .pcm_start(pcm_start),.pcm_end(pcm_end),.pcm_loop(pcm_loop),.pcm_loop_enable(pcm_loop_enable),
        .pcm_prepare(pcm_prepare),.pcm_stop(pcm_stop),.pcm_clear(pcm_clear),.pcm_status(pcm_status),
        .snapshot_pcm_l(pcm_gain_l),.snapshot_pcm_r(pcm_gain_r),.snapshot_pcm_enable(pcm_commit_enable),.settle(audio_settle));
    kagura_audio_synth #(.EXTERNAL_SNAPSHOT(1),.PCM_ENABLE(PSRAM)) audio_synth(.clk(clk),.reset(reset),.apply_valid(audio_apply_valid),.apply_ready(audio_apply_ready),
        .cfg_step(audio_steps),.cfg_duty(audio_duties),.cfg_gain_l(audio_l),.cfg_gain_r(audio_r),.cfg_enable(audio_enable),
        .cfg_phase_reset(audio_resets),.cfg_wave_len(audio_lengths),.cfg_master(audio_master),.cfg_noise_period(audio_period),
        .apply_done(audio_apply_done),.apply_error(audio_apply_error),.apply_busy(),.wave_read(wave_read),.wave_addr(wave_addr),
        .wave_data(wave_data),.sample_valid(audio_sample_valid),.sample_left(audio_left),.sample_right(audio_right),.last_cycles(),
        .apply_boundary(wave_swap),.sample_boundary(sample_boundary),
        .pcm_sample0(pcm_sample0),.pcm_sample1(pcm_sample1),.cfg_pcm_gain_l(pcm_gain_l),.cfg_pcm_gain_r(pcm_gain_r),.cfg_pcm_enable(pcm_commit_enable));

    // PSRAM: queue byte operations (host port) and PCM refills (PCM port)
    // share one controller. PSRAM writes complete in order with later reads.
    wire eng_psram_valid,eng_psram_ready,eng_psram_write,eng_psram_rsp_valid;
    wire [21:0] eng_psram_addr;
    wire [7:0] eng_psram_wdata,eng_psram_rdata;
    generate if(PSRAM) begin: psram
        wire calib,c_cmd,c_en,c_rdy,c_valid,h_rdy,h_valid,p_cmd,p_en,p_rdy,p_valid;
        wire [19:0] c_addr,p_addr;
        wire [31:0] c_wdata,c_rdata,h_rdata,p_rdata;
        wire [3:0] c_mask;
        kagura_hyperram_ctrl #(.ADDR_WIDTH(20),.INIT_CYCLES(PSRAM_INIT_CYCLES)) ctrl(
            .clk(clk),.rst_n(!reset),.lat_cycles(5'(PSRAM_LAT)),.rd_latency(3'(PSRAM_RDL)),
            .cmd(c_cmd),.cmd_reg(1'b0),.cmd_en(c_en),.cmd_rdy(c_rdy),.addr(c_addr),.wr_data(c_wdata),.data_mask(c_mask),
            .rd_data(c_rdata),.rd_data_valid(c_valid),.init_calib(calib),
            .phy_reset_n(psram_reset_n),.phy_cs_n(psram_cs_n),.phy_ck_en(psram_ck_en),.phy_dq_oe(psram_dq_oe),
            .phy_dq_o_rise(psram_dq_o_rise),.phy_dq_o_fall(psram_dq_o_fall),.phy_rwds_oe(psram_rwds_oe),
            .phy_rwds_o_rise(psram_rwds_o_rise),.phy_rwds_o_fall(psram_rwds_o_fall),
            .phy_dq_i_rise(psram_dq_i_rise),.phy_dq_i_fall(psram_dq_i_fall));
        // Host side: one masked byte lane of a 32-bit word per queue byte operation.
        reg [1:0] lane;
        wire h_en=eng_psram_valid && calib;
        assign eng_psram_ready=h_rdy && calib;
        always @(posedge clk) if(h_en && h_rdy) lane<=eng_psram_addr[1:0];
        assign eng_psram_rsp_valid=h_valid;
        assign eng_psram_rdata=h_rdata[8*lane +: 8];
        kagura_psram_arbiter #(.ADDR_WIDTH(20)) arbiter(.clk(clk),.reset(reset),
            .p_cmd(p_cmd),.p_cmd_en(p_en),.p_cmd_rdy(p_rdy),.p_addr(p_addr),.p_rd_data(p_rdata),.p_rd_data_valid(p_valid),
            .h_cmd(eng_psram_write),.h_cmd_en(h_en),.h_cmd_rdy(h_rdy),.h_addr(eng_psram_addr[21:2]),
            .h_wr_data({4{eng_psram_wdata}}),.h_data_mask(~(4'b0001<<eng_psram_addr[1:0])),
            .h_rd_data(h_rdata),.h_rd_data_valid(h_valid),
            .c_cmd(c_cmd),.c_cmd_en(c_en),.c_cmd_rdy(c_rdy),.c_addr(c_addr),.c_wr_data(c_wdata),.c_data_mask(c_mask),
            .c_rd_data(c_rdata),.c_rd_data_valid(c_valid));
        // PCM side. Public addresses are 400000-7FFFFF; the prefetcher works in
        // PSRAM offsets (a lower START wraps above 4 MiB and fails its range check).
        wire pf_req_valid,pf_req_ready,pf_rsp_valid,pf_rsp_error,flush;
        wire [23:0] pf_req_addr;
        wire [7:0] pf_rsp_data;
        wire [1:0] cfg_valid,cfg_ready,start_play,stop_play,pf_ready,pf_active,pf_done,pf_underrun,pf_config_error,pf_memory_error;
        // Offsets registered: a PREPARE is accepted at least three cycles after the
        // last START/END/LOOP write, and this keeps the subtraction out of the
        // prefetcher's configuration check.
        reg [47:0] rel_start,rel_end,rel_loop;
        always @(posedge clk) begin
            rel_start<={pcm_start[47:24]-24'h400000,pcm_start[23:0]-24'h400000};
            rel_end<={pcm_end[47:24]-24'h400000,pcm_end[23:0]-24'h400000};
            rel_loop<={pcm_loop[47:24]-24'h400000,pcm_loop[23:0]-24'h400000};
        end
        kagura_psram_read_path #(.BYTE_ADDR_WIDTH(24),.CTRL_ADDR_WIDTH(20)) path(
            .sys_clk(clk),.sys_reset(reset),.sys_req_valid(pf_req_valid),.sys_req_ready(pf_req_ready),.sys_req_addr(pf_req_addr),
            .sys_rsp_valid(pf_rsp_valid),.sys_rsp_data(pf_rsp_data),.sys_rsp_error(pf_rsp_error),
            .mem_clk(clk),.mem_reset(reset),.controller_ready(calib),.cache_flush(flush),
            .ctrl_cmd(p_cmd),.ctrl_cmd_en(p_en),.ctrl_cmd_rdy(p_rdy),.ctrl_addr(p_addr),
            .ctrl_rd_data(p_rdata),.ctrl_rd_data_valid(p_valid));
        kagura_pcm_prefetch #(.ADDR_WIDTH(24),.BUFFER_ADDR_BITS(5),.MEMORY_BYTES(25'h0400000),.RESPONSE_TIMEOUT(4096)) prefetch(
            .clk(clk),.reset(reset),.sample_tick(sample_boundary),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),
            .cfg_start(rel_start),.cfg_end(rel_end),.cfg_loop(rel_loop),
            .cfg_loop_enable(pcm_loop_enable),.start_play(start_play),.stop_play(stop_play),
            .ready(pf_ready),.active(pf_active),.done(pf_done),.underrun(pf_underrun),
            .config_error(pf_config_error),.memory_error(pf_memory_error),.sample0(pcm_sample0),.sample1(pcm_sample1),
            .mem_req_valid(pf_req_valid),.mem_req_ready(pf_req_ready),.mem_req_addr(pf_req_addr),
            .mem_rsp_valid(pf_rsp_valid),.mem_rsp_data(pf_rsp_data),.mem_rsp_error(pf_rsp_error));
        kagura_pcm_control control(.clk(clk),.reset(reset),.prepare(pcm_prepare),.stop(pcm_stop),.clear(pcm_clear),
            .apply_boundary(wave_swap),.commit_enable(pcm_commit_enable),
            .cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.start_play(start_play),.stop_play(stop_play),.cache_flush(flush),
            .pf_ready(pf_ready),.pf_active(pf_active),.pf_done(pf_done),.pf_underrun(pf_underrun),
            .pf_config_error(pf_config_error),.pf_memory_error(pf_memory_error),
            .status0(pcm_status[7:0]),.status1(pcm_status[15:8]));
    end else begin: no_psram
        assign {psram_reset_n,psram_cs_n,psram_ck_en,psram_dq_oe,psram_rwds_oe}=5'b01000;
        assign {psram_dq_o_rise,psram_dq_o_fall,psram_rwds_o_rise,psram_rwds_o_fall}=0;
        assign {eng_psram_ready,eng_psram_rsp_valid,eng_psram_rdata}=0;
        assign {pcm_sample0,pcm_sample1,pcm_status}=0;
    end endgenerate

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
        .audio_settings_valid(audio_settings_valid),.audio_busy(audio_busy),.audio_settle(audio_settle),.audio_index_write(audio_index_write),
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
        .audio_apply_ready(audio_apply_ready),.audio_apply_done(audio_apply_done),.audio_apply_valid(audio_apply_valid),.audio_commit_done(audio_commit_done),
        .psram_valid(eng_psram_valid),.psram_ready(eng_psram_ready),.psram_write(eng_psram_write),.psram_addr(eng_psram_addr),
        .psram_wdata(eng_psram_wdata),.psram_rsp_valid(eng_psram_rsp_valid),.psram_rdata(eng_psram_rdata));

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
