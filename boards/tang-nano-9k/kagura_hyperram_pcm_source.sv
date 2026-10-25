// SPDX-License-Identifier: Apache-2.0
// Evaluation only: upload two patterns, then continuously play/check PCM.
// Uploads go through the host port of kagura_psram_arbiter. With HOST_TRAFFIC
// the host port then keeps writing and reading back a separate region
// back-to-back during playback (worst-case host load); host_errors counts
// mismatches and pcm_wait_max the longest PCM byte request-to-response time.
// No host ABI. Connect the byte-pair ports to the Gowin PHY on hardware or a
// CA-decoding model in simulation.
module kagura_hyperram_pcm_source #(
    parameter integer INIT_CYCLES=4096,
    parameter         HOST_TRAFFIC=1'b1,
    parameter integer HOST_WORDS_LOG2=12
) (
    input wire clk, reset,
    output wire sample_valid,
    output wire signed [15:0] sample_left, sample_right,
    output reg [31:0] checked_samples, read_bytes, data_errors, mix_errors,
    output reg [31:0] host_words, host_errors,
    output reg [15:0] pcm_wait_max,
    output wire [7:0] faults,
    output wire [1:0] active,
    output wire phy_reset_n, phy_cs_n, phy_ck_en, phy_dq_oe, phy_rwds_oe,
    output wire [7:0] phy_dq_o_rise, phy_dq_o_fall,
    output wire phy_rwds_o_rise, phy_rwds_o_fall,
    input wire [7:0] phy_dq_i_rise, phy_dq_i_fall
);
    localparam [23:0] START0=24'h000101, END0=24'h000302;
    localparam [23:0] START1=24'h3FFC03, END1=24'h3FFE02;
    typedef enum logic [2:0] {INIT,UPLOAD,DRAIN,CONFIG,PREFILL,ARM,PLAY} state_t;
    state_t state;
    reg region;
    reg [7:0] upload_index;
    wire uploading=state==UPLOAD;
    wire init_calib,ctrl_ready,ctrl_valid,ctrl_cmd,ctrl_en;
    wire [31:0] ctrl_data,ctrl_wr_data;
    wire [3:0] ctrl_mask;
    wire [19:0] ctrl_addr;
    wire read_cmd,read_en,read_rdy,read_valid;
    wire [19:0] read_addr;
    wire [31:0] read_data;
    reg host_cmd,host_en;
    reg [19:0] host_addr;
    reg [31:0] host_wr_data;
    wire host_rdy,host_valid;
    wire [31:0] host_rd_data;
    wire host_fire=host_en && host_rdy;
    wire [19:0] upload_addr=(region ? 20'hFFF00 : 20'h00040)+20'(upload_index);
    wire [23:0] upload_byte={2'b0,upload_addr,2'b0};
    function automatic [7:0] pattern(input [23:0] a);
        pattern=a[21] ? {a[6:0],1'b0} : {a[5:0],2'b0};
    endfunction
    wire [31:0] upload_data={pattern(upload_byte+3),pattern(upload_byte+2),
                            pattern(upload_byte+1),pattern(upload_byte)};
    kagura_psram_arbiter #(.ADDR_WIDTH(20)) arbiter(
        .clk,.reset,
        .p_cmd(read_cmd),.p_cmd_en(read_en),.p_cmd_rdy(read_rdy),.p_addr(read_addr),
        .p_rd_data(read_data),.p_rd_data_valid(read_valid),
        .h_cmd(host_cmd),.h_cmd_en(host_en),.h_cmd_rdy(host_rdy),.h_addr(host_addr),
        .h_wr_data(host_wr_data),.h_data_mask(4'b0),.h_rd_data(host_rd_data),.h_rd_data_valid(host_valid),
        .c_cmd(ctrl_cmd),.c_cmd_en(ctrl_en),.c_cmd_rdy(ctrl_ready),.c_addr(ctrl_addr),
        .c_wr_data(ctrl_wr_data),.c_data_mask(ctrl_mask),.c_rd_data(ctrl_data),.c_rd_data_valid(ctrl_valid));
    kagura_hyperram_ctrl #(.ADDR_WIDTH(20),.INIT_CYCLES(INIT_CYCLES)) ctrl(
        .clk,.rst_n(!reset),.lat_cycles(5'd14),.rd_latency(3'd6),
        .cmd(ctrl_cmd),.cmd_reg(1'b0),.cmd_en(ctrl_en),.cmd_rdy(ctrl_ready),
        .addr(ctrl_addr),.wr_data(ctrl_wr_data),.data_mask(ctrl_mask),
        .rd_data(ctrl_data),.rd_data_valid(ctrl_valid),.init_calib,
        .phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,.phy_rwds_oe,
        .phy_dq_o_rise,.phy_dq_o_fall,.phy_rwds_o_rise,.phy_rwds_o_fall,
        .phy_dq_i_rise,.phy_dq_i_fall);

    wire req_valid,req_ready,rsp_valid,rsp_error;
    wire [23:0] req_addr;
    wire [7:0] rsp_data;
    // Retain the tested mailbox even though both domains share system54.
    kagura_psram_read_path #(.BYTE_ADDR_WIDTH(24),.CTRL_ADDR_WIDTH(20)) path(
        .sys_clk(clk),.sys_reset(reset),.sys_req_valid(req_valid),.sys_req_ready(req_ready),
        .sys_req_addr(req_addr),.sys_rsp_valid(rsp_valid),.sys_rsp_data(rsp_data),.sys_rsp_error(rsp_error),
        .mem_clk(clk),.mem_reset(reset),.controller_ready(init_calib && state>=CONFIG),.cache_flush(1'b0),
        .ctrl_cmd(read_cmd),.ctrl_cmd_en(read_en),.ctrl_cmd_rdy(read_rdy),.ctrl_addr(read_addr),
        .ctrl_rd_data(read_data),.ctrl_rd_data_valid(read_valid));

    wire [1:0] cfg_ready,ready,underrun,config_error,memory_error;
    wire signed [7:0] pcm0,pcm1;
    wire boundary,apply_ready,apply_error;
    wire [6:0] last_cycles;
    wire arm=state==ARM && apply_ready;
    kagura_pcm_prefetch #(.ADDR_WIDTH(24),.BUFFER_ADDR_BITS(5),
        .MEMORY_BYTES(25'h0400000),.RESPONSE_TIMEOUT(4096)) prefetch(
        .clk,.reset,.sample_tick(boundary),.cfg_valid({2{state==CONFIG}}),.cfg_ready,
        .cfg_start({START1,START0}),.cfg_end({END1,END0}),.cfg_loop({START1,START0}),
        .cfg_loop_enable(2'b11),.start_play({2{arm}}),.stop_play(2'b0),.ready,.active,
        .done(),.underrun,.config_error,.memory_error,.sample0(pcm0),.sample1(pcm1),
        .mem_req_valid(req_valid),.mem_req_ready(req_ready),.mem_req_addr(req_addr),
        .mem_rsp_valid(rsp_valid),.mem_rsp_data(rsp_data),.mem_rsp_error(rsp_error));
    kagura_audio_synth #(.PCM_ENABLE(1)) synth(
        .clk,.reset,.apply_valid(arm),.apply_ready,.apply_done(),.apply_error,.apply_busy(),
        .cfg_step(144'b0),.cfg_duty(24'b0),.cfg_gain_l(48'b0),.cfg_gain_r(48'b0),
        .cfg_enable(6'b0),.cfg_phase_reset(6'b0),.cfg_wave_len(8'h55),.cfg_master(8'd32),
        .cfg_noise_period(16'b0),.wave_read(),.wave_addr(),.wave_data(8'sd0),
        .sample_valid,.sample_left,.sample_right,.last_cycles,.apply_boundary(),
        .sample_boundary(boundary),.pcm_sample0(pcm0),.pcm_sample1(pcm1),
        .cfg_pcm_gain_l(16'h0080),.cfg_pcm_gain_r(16'h8000),.cfg_pcm_enable(2'b11));

    // Host port: upload first, then (HOST_TRAFFIC) write a 2^HOST_WORDS_LOG2
    // word region at word 0x40000 and read it back, a new seed per round.
    reg [1:0] t_phase;   // 0 write, 1 read issue, 2 read wait
    reg [HOST_WORDS_LOG2-1:0] t_idx;
    reg [15:0] t_seed;
    function automatic [31:0] host_pattern(input [19:0] a,input [15:0] seed);
        reg [31:0] x;
        x={a[11:0],a}^{seed,~seed};
        x=x^(x<<13);
        x=x^(x>>17);
        host_pattern=x^(x<<5);
    endfunction
    wire t_last=&t_idx;
    always @* begin
        host_cmd=1; host_en=0; host_addr=upload_addr; host_wr_data=upload_data;
        if(uploading) host_en=init_calib;
        else if(HOST_TRAFFIC && state==PLAY) begin
            host_addr=20'h40000+20'(t_idx);
            host_wr_data=host_pattern(20'(t_idx),t_seed);
            host_cmd=t_phase==0;
            host_en=t_phase!=2;
        end
    end
    always @(posedge clk) begin
        if(reset) begin
            t_phase<=0; t_idx<=0; t_seed<=0; host_words<=0; host_errors<=0;
        end else if(state==PLAY) begin
            if(host_fire) begin
                host_words<=host_words+1'b1;
                if(t_phase==0) begin
                    t_idx<=t_idx+1'b1;
                    if(t_last) t_phase<=1;
                end else t_phase<=2;
            end
            if(host_valid && t_phase==2) begin
                if(host_rd_data!=host_pattern(20'(t_idx),t_seed) && !(&host_errors))
                    host_errors<=host_errors+1'b1;
                t_idx<=t_idx+1'b1;
                if(t_last) begin t_phase<=0; t_seed<=t_seed+1'b1; end
                else t_phase<=1;
            end
        end
    end

    // Longest PCM byte request (valid, before acceptance) to response, in cycles.
    reg pcm_waiting;
    reg [15:0] pcm_wait;
    always @(posedge clk) begin
        if(reset) begin pcm_waiting<=0; pcm_wait<=0; pcm_wait_max<=0; end
        else begin
            if(rsp_valid) begin
                pcm_waiting<=0;
                if(pcm_wait>pcm_wait_max) pcm_wait_max<=pcm_wait;
            end else if(pcm_waiting) begin
                if(!(&pcm_wait)) pcm_wait<=pcm_wait+1'b1;
            end else if(req_valid) begin
                pcm_waiting<=1; pcm_wait<=1;
            end
        end
    end

    reg [23:0] startup_timer;
    reg startup_timeout,synth_error;
    assign faults={synth_error,startup_timeout,memory_error,config_error,underrun};
    always @(posedge clk) begin
        if(reset) begin
            state<=INIT; region<=0; upload_index<=0;
            startup_timer<=0; startup_timeout<=0;
        end else begin
            if(state!=PLAY) begin
                if(&startup_timer) startup_timeout<=1;
                else startup_timer<=startup_timer+1'b1;
            end
            case(state)
                INIT: if(init_calib) state<=UPLOAD;
                UPLOAD: if(host_fire) begin
                    if(upload_index==128) begin
                        upload_index<=0;
                        if(region) state<=DRAIN;
                        else region<=1;
                    end else upload_index<=upload_index+1'b1;
                end
                DRAIN: if(ctrl_ready) state<=CONFIG;
                CONFIG: if(&cfg_ready) state<=PREFILL;
                PREFILL: if(&ready) state<=ARM;
                ARM: if(apply_ready) state<=PLAY;
                default: ;
            endcase
        end
    end

    // Check every byte response against its accepted byte address, independently
    // of the prefetch buffer and mixer. Counters saturate to retain failures.
    reg [23:0] pending_addr,play_addr0,play_addr1;
    reg check_pending;
    reg signed [15:0] expected_l,expected_r;
    always @(posedge clk) begin
        if(reset) begin
            pending_addr<=0; read_bytes<=0; data_errors<=0; mix_errors<=0;
            checked_samples<=0; check_pending<=0; synth_error<=0;
            play_addr0<=START0; play_addr1<=START1; expected_l<=0; expected_r<=0;
        end else begin
            if(req_valid && req_ready) pending_addr<=req_addr;
            if(rsp_valid) begin
                read_bytes<=read_bytes+1'b1;
                if((rsp_error || rsp_data!=pattern(pending_addr)) && !(&data_errors))
                    data_errors<=data_errors+1'b1;
            end
            if(apply_error) synth_error<=1;
            if(boundary && (&active)) begin
                expected_l<=16'($signed(pattern(play_addr0)))<<<4;
                expected_r<=16'($signed(pattern(play_addr1)))<<<4;
                play_addr0<=play_addr0==END0-1 ? START0 : play_addr0+1'b1;
                play_addr1<=play_addr1==END1-1 ? START1 : play_addr1+1'b1;
                check_pending<=1;
            end
            if(sample_valid && check_pending) begin
                checked_samples<=checked_samples+1'b1;
                check_pending<=0;
                if(last_cycles!=30) synth_error<=1;
                if((sample_left!=expected_l || sample_right!=expected_r) && !(&mix_errors))
                    mix_errors<=mix_errors+1'b1;
            end
        end
    end
endmodule
