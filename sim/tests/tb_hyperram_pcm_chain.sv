`timescale 1ns/1ps
// Real HyperRAM controller and byte-pair memory model through the
// byte cache and CDC into prefetch and the optional PCM mixer.
module tb_hyperram_pcm_chain;
    localparam integer AW=8;
    reg sys_clk=0,mem_clk=0,sys_reset=1,mem_reset=1;
    always #9.259 sys_clk=~sys_clk;
    initial begin
        #3;
        forever #9.259 mem_clk=~mem_clk; // 54MHz with a phase offset
    end

    reg [1:0] cfg_valid=0,start_play=0;
    wire [1:0] cfg_ready,pcm_ready,active,done,underrun,config_error,memory_error;
    wire sample_boundary,sample_valid;
    wire signed [7:0] pcm0,pcm1;
    wire signed [15:0] audio_l,audio_r;
    wire [6:0] last_cycles;
    reg apply_valid=0;
    wire apply_ready,apply_done;

    wire sys_req_valid,sys_req_ready,sys_rsp_valid,sys_rsp_error;
    wire [AW-1:0] sys_req_addr;
    wire [7:0] sys_rsp_data;
    wire ctrl_cmd,ctrl_cmd_en,ctrl_cmd_rdy;
    wire [5:0] ctrl_addr;
    wire ctrl_rd_data_valid;
    wire [31:0] ctrl_rd_data;
    reg [7:0] expected [0:255];
    integer ctrl_commands=0;
    reg done_seen=0;

    kagura_pcm_prefetch #(
        .ADDR_WIDTH(AW),.BUFFER_ADDR_BITS(3),.MEMORY_BYTES(9'd128),.RESPONSE_TIMEOUT(200)
    ) prefetch(
        .clk(sys_clk),.reset(sys_reset),.sample_tick(sample_boundary),
        .cfg_valid(cfg_valid),.cfg_ready(cfg_ready),
        .cfg_start({8'b0,8'h20}),.cfg_end({8'b0,8'h28}),.cfg_loop({8'b0,8'h20}),
        .cfg_loop_enable(2'b0),.start_play(start_play),.stop_play(2'b0),
        .ready(pcm_ready),.active(active),.done(done),.underrun(underrun),
        .config_error(config_error),.memory_error(memory_error),.sample0(pcm0),.sample1(pcm1),
        .mem_req_valid(sys_req_valid),.mem_req_ready(sys_req_ready),.mem_req_addr(sys_req_addr),
        .mem_rsp_valid(sys_rsp_valid),.mem_rsp_data(sys_rsp_data),.mem_rsp_error(sys_rsp_error));

    kagura_psram_read_path #(
        .BYTE_ADDR_WIDTH(AW),.CTRL_ADDR_WIDTH(6),.CTRL_ADDR_SHIFT(2)
    ) read_path(
        .sys_clk(sys_clk),.sys_reset(sys_reset),.sys_req_valid(sys_req_valid),
        .sys_req_ready(sys_req_ready),.sys_req_addr(sys_req_addr),
        .sys_rsp_valid(sys_rsp_valid),.sys_rsp_data(sys_rsp_data),.sys_rsp_error(sys_rsp_error),
        .mem_clk(mem_clk),.mem_reset(mem_reset),.controller_ready(init_calib && !upload),.cache_flush(1'b0),
        .ctrl_cmd(ctrl_cmd),.ctrl_cmd_en(ctrl_cmd_en),.ctrl_cmd_rdy(ctrl_cmd_rdy),.ctrl_addr(ctrl_addr),
        .ctrl_rd_data(ctrl_rd_data),.ctrl_rd_data_valid(ctrl_rd_data_valid));

    reg upload=1, upload_en=0;
    reg [5:0] upload_addr=0;
    reg [31:0] upload_data=0;
    reg [3:0] upload_mask=0;
    wire init_calib, reset_n, cs_n, ck_en, dq_oe, rwds_oe, mask_r, mask_f;
    wire [7:0] dq_r,dq_f,read_r,read_f;
    kagura_hyperram_ctrl #(.ADDR_WIDTH(6),.INIT_CYCLES(64)) controller(
        .clk(mem_clk),.rst_n(!mem_reset),.lat_cycles(5'd14),.rd_latency(3'd6),
        .cmd(upload ? 1'b1 : ctrl_cmd),.cmd_reg(1'b0),.cmd_en(upload ? upload_en : ctrl_cmd_en),
        .cmd_rdy(ctrl_cmd_rdy),.addr(upload ? upload_addr : ctrl_addr),
        .wr_data(upload_data),.data_mask(upload_mask),.rd_data(ctrl_rd_data),
        .rd_data_valid(ctrl_rd_data_valid),.init_calib(init_calib),
        .phy_reset_n(reset_n),.phy_cs_n(cs_n),.phy_ck_en(ck_en),.phy_dq_oe(dq_oe),
        .phy_dq_o_rise(dq_r),.phy_dq_o_fall(dq_f),.phy_rwds_oe(rwds_oe),
        .phy_rwds_o_rise(mask_r),.phy_rwds_o_fall(mask_f),
        .phy_dq_i_rise(read_r),.phy_dq_i_fall(read_f));
    kagura_hyperram_pair_model model(
        .clk(mem_clk),.reset_n(reset_n),.cs_n(cs_n),.ck_en(ck_en),
        .dq_oe(dq_oe),.rwds_oe(rwds_oe),.dq_r(dq_r),.dq_f(dq_f),
        .mask_r(mask_r),.mask_f(mask_f),.read_r(read_r),.read_f(read_f));
    always @(posedge mem_clk)
        if(ctrl_cmd_en && ctrl_cmd_rdy) ctrl_commands<=ctrl_commands+1;
    task automatic write_word(input [5:0] a,input [31:0] d,input [3:0] m);
        @(negedge mem_clk);
        while(!ctrl_cmd_rdy) @(negedge mem_clk);
        upload_addr=a; upload_data=d; upload_mask=m; upload_en=1;
        @(negedge mem_clk); upload_en=0;
        while(!ctrl_cmd_rdy) @(negedge mem_clk);
    endtask
    kagura_audio_synth #(.PCM_ENABLE(1)) synth(
        .clk(sys_clk),.reset(sys_reset),.apply_valid(apply_valid),.apply_ready(apply_ready),
        .cfg_step(144'b0),.cfg_duty(24'b0),.cfg_gain_l(48'b0),.cfg_gain_r(48'b0),
        .cfg_enable(6'b0),.cfg_phase_reset(6'b0),.cfg_wave_len(8'h55),.cfg_master(8'd32),
        .cfg_noise_period(16'b0),.apply_done(apply_done),.apply_error(),.apply_busy(),
        .wave_read(),.wave_addr(),.wave_data(8'sd0),.sample_valid(sample_valid),
        .sample_left(audio_l),.sample_right(audio_r),.last_cycles(last_cycles),
        .apply_boundary(),.sample_boundary(sample_boundary),.pcm_sample0(pcm0),.pcm_sample1(pcm1),
        .cfg_pcm_gain_l(16'h0008),.cfg_pcm_gain_r(16'h0008),.cfg_pcm_enable(2'b01));

    always @(posedge sys_clk) if(done[0]) done_seen<=1;

    initial begin
        for(integer i=0;i<256;i=i+1) expected[i]=0;
        expected[8'h20]=8'd8;   expected[8'h21]=8'd16;
        expected[8'h22]=-8'sd8; expected[8'h23]=-8'sd16;
        expected[8'h24]=8'd24;  expected[8'h25]=-8'sd24;
        expected[8'h26]=8'd32;  expected[8'h27]=-8'sd32;

        repeat(4) @(negedge sys_clk); sys_reset=0;
        repeat(4) @(negedge mem_clk); mem_reset=0;
        wait(init_calib);
        // Upload through the real controller; expected samples stay independent.
        write_word(6'h08,32'hF0AA10AA,4'b0000);
        write_word(6'h09,32'hAA20AA18,4'b0000);
        // Masked bytes retain data; unmasked bytes replace the AA placeholders.
        write_word(6'h08,32'h00F80008,4'b1010);
        write_word(6'h09,32'hE000E800,4'b0101);
        @(negedge mem_clk); upload=0;
        wait(cfg_ready[0]); @(negedge sys_clk); cfg_valid[0]=1;
        @(negedge sys_clk); cfg_valid[0]=0;
        wait(pcm_ready[0]);
        if(ctrl_commands!=2) $fatal(1,"eight sequential bytes used %0d controller commands",ctrl_commands);

        @(negedge sys_clk); start_play[0]=1; apply_valid=1;
        @(negedge sys_clk); start_play[0]=0; apply_valid=0;
        wait(apply_done);
        for(integer n=0;n<8;n=n+1) begin
            @(posedge sample_valid); #1;
            if(audio_l!==16'($signed(expected[32+n])) || audio_r!==16'($signed(expected[32+n])) || last_cycles!=29)
                $fatal(1,"chain sample %0d got %0d,%0d expected %0d",n,audio_l,audio_r,$signed(expected[32+n]));
        end
        if(!done_seen || active[0] || (|underrun) || (|config_error) || (|memory_error))
            $fatal(1,"chain completion/status failed");
        @(posedge sample_valid); #1;
        if(audio_l!==0 || audio_r!==0 || ctrl_commands!=2)
            $fatal(1,"one-shot did not stop cleanly");
        $display("PASS: HyperRAM upload/masked writes, CA model, read path, prefetch and PCM mixer; lat 14/6, 8 samples in 2 reads");
        $finish;
    end
    initial begin #3000000; $fatal(1,"PSRAM PCM chain timeout"); end
endmodule
