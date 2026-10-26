`timescale 1ns/1ps
// Vendor-neutral vertical path: a 32-bit PSRAM controller model through the
// byte cache and CDC into prefetch and the optional PCM mixer.
module tb_psram_pcm_chain;
    localparam integer AW=8;
    reg sys_clk=0,mem_clk=0,sys_reset=1,mem_reset=1;
    always #9.259 sys_clk=~sys_clk;
    always #5 mem_clk=~mem_clk;

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
    wire ctrl_cmd_en,ctrl_cmd_rdy;
    wire [5:0] ctrl_addr;
    reg ctrl_rd_data_valid=0;
    reg [31:0] ctrl_rd_data=0;
    reg [7:0] memory [0:255];
    reg ctrl_pending=0;
    reg [5:0] ctrl_pending_addr=0;
    integer ctrl_delay=0,ctrl_commands=0,observed=0;
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
        .mem_clk(mem_clk),.mem_reset(mem_reset),.controller_ready(!mem_reset),.cache_flush(1'b0),
        .ctrl_cmd(),.ctrl_cmd_en(ctrl_cmd_en),.ctrl_cmd_rdy(ctrl_cmd_rdy),.ctrl_addr(ctrl_addr),
        .ctrl_rd_data(ctrl_rd_data),.ctrl_rd_data_valid(ctrl_rd_data_valid));

    assign ctrl_cmd_rdy=!ctrl_pending && (($time/10)%4!=0);
    always @(posedge mem_clk) begin
        ctrl_rd_data_valid<=0;
        if(ctrl_cmd_en && ctrl_cmd_rdy) begin
            ctrl_pending<=1;
            ctrl_pending_addr<=ctrl_addr;
            ctrl_delay<=ctrl_addr[1:0]+1;
            ctrl_commands<=ctrl_commands+1;
        end
        if(ctrl_pending) begin
            if(ctrl_delay==0) begin
                ctrl_pending<=0;
                ctrl_rd_data_valid<=1;
                ctrl_rd_data<={memory[{ctrl_pending_addr,2'b11}],memory[{ctrl_pending_addr,2'b10}],
                    memory[{ctrl_pending_addr,2'b01}],memory[{ctrl_pending_addr,2'b00}]};
            end else ctrl_delay<=ctrl_delay-1;
        end
    end

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
        for(integer i=0;i<256;i=i+1) memory[i]=0;
        memory[8'h20]=8'd8;   memory[8'h21]=8'd16;
        memory[8'h22]=-8'sd8; memory[8'h23]=-8'sd16;
        memory[8'h24]=8'd24;  memory[8'h25]=-8'sd24;
        memory[8'h26]=8'd32;  memory[8'h27]=-8'sd32;

        repeat(4) @(posedge sys_clk); sys_reset=0;
        repeat(4) @(posedge mem_clk); mem_reset=0;
        wait(cfg_ready[0]); @(negedge sys_clk); cfg_valid[0]=1;
        @(negedge sys_clk); cfg_valid[0]=0;
        wait(pcm_ready[0]);
        if(ctrl_commands!=2) $fatal(1,"eight sequential bytes used %0d controller commands",ctrl_commands);

        @(negedge sys_clk); start_play[0]=1; apply_valid=1;
        @(negedge sys_clk); start_play[0]=0; apply_valid=0;
        wait(apply_done);
        for(integer n=0;n<8;n=n+1) begin
            @(posedge sample_valid); #1;
            if(audio_l!==$signed(memory[8'h20+n]) || audio_r!==$signed(memory[8'h20+n]) || last_cycles!=31)
                $fatal(1,"chain sample %0d got %0d,%0d expected %0d",n,audio_l,audio_r,$signed(memory[8'h20+n]));
            observed=observed+1;
        end
        if(!done_seen || active[0] || underrun || config_error || memory_error)
            $fatal(1,"chain completion/status failed");
        $display("PASS: PSRAM 32-bit model, cache, async CDC, prefetch and PCM mixer; 8 samples in 2 commands");
        $finish;
    end
    initial begin #3000000; $fatal(1,"PSRAM PCM chain timeout"); end
endmodule
