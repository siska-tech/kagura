`timescale 1ns/1ps
module tb_pcm_audio_path;
    localparam integer AW=8;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,apply_valid=0;
    wire apply_ready,apply_done,apply_busy,sample_boundary,sample_valid;
    wire signed [15:0] left,right;
    wire [6:0] last_cycles;

    reg [1:0] cfg_valid=0,start_play=0,stop_play=0;
    wire [1:0] cfg_ready,ready,active,done,underrun,config_error,memory_error;
    reg [2*AW-1:0] cfg_start=0,cfg_end=0,cfg_loop=0;
    wire signed [7:0] pcm0,pcm1;
    wire mem_req_valid;
    wire [AW-1:0] mem_req_addr;
    reg mem_rsp_valid=0;
    reg [7:0] mem_rsp_data=0;
    reg pending=0;
    reg [AW-1:0] pending_addr=0;
    reg [7:0] memory [0:255];
    integer observed=0;
    reg done_seen=0;

    kagura_pcm_prefetch #(.ADDR_WIDTH(AW),.BUFFER_ADDR_BITS(2)) prefetch(
        .clk(clk),.reset(reset),.sample_tick(sample_boundary),
        .cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_start(cfg_start),.cfg_end(cfg_end),
        .cfg_loop(cfg_loop),.cfg_loop_enable(2'b0),.start_play(start_play),.stop_play(stop_play),
        .ready(ready),.active(active),.done(done),.underrun(underrun),
        .config_error(config_error),.memory_error(memory_error),.sample0(pcm0),.sample1(pcm1),
        .mem_req_valid(mem_req_valid),.mem_req_ready(!pending),.mem_req_addr(mem_req_addr),
        .mem_rsp_valid(mem_rsp_valid),.mem_rsp_data(mem_rsp_data),.mem_rsp_error(1'b0));

    kagura_audio_synth #(.PCM_ENABLE(1)) synth(
        .clk(clk),.reset(reset),.apply_valid(apply_valid),.apply_ready(apply_ready),
        .cfg_step(144'b0),.cfg_duty(24'b0),.cfg_gain_l(48'b0),.cfg_gain_r(48'b0),
        .cfg_enable(6'b0),.cfg_phase_reset(6'b0),.cfg_wave_len(8'h55),.cfg_master(8'd32),
        .cfg_noise_period(16'b0),.apply_done(apply_done),.apply_error(),.apply_busy(apply_busy),
        .wave_read(),.wave_addr(),.wave_data(8'sd0),.sample_valid(sample_valid),
        .sample_left(left),.sample_right(right),.last_cycles(last_cycles),
        .apply_boundary(),.sample_boundary(sample_boundary),.pcm_sample0(pcm0),.pcm_sample1(pcm1),
        .cfg_pcm_gain_l(16'h0008),.cfg_pcm_gain_r(16'h0008),.cfg_pcm_enable(2'b01));

    always @(posedge clk) begin
        if(done[0]) done_seen<=1;
        mem_rsp_valid<=0;
        if(mem_req_valid && !pending) begin pending<=1; pending_addr<=mem_req_addr; end
        if(pending) begin
            mem_rsp_valid<=1; mem_rsp_data<=memory[pending_addr]; pending<=0;
        end
    end

    task automatic check_sample(input signed [15:0] value);
        begin
            @(posedge sample_valid); #1;
            if(left!==value || right!==value || last_cycles!=31)
                $fatal(1,"integrated sample %0d got %0d,%0d cycles %0d expected %0d",observed,left,right,last_cycles,value);
            observed=observed+1;
        end
    endtask

    initial begin
        memory[8'h20]=8'd8; memory[8'h21]=8'd16;
        memory[8'h22]=-8'sd8; memory[8'h23]=-8'sd16;
        #100; @(negedge clk); reset=0;
        wait(cfg_ready[0]); @(negedge clk);
        cfg_start[7:0]=8'h20; cfg_end[7:0]=8'h24; cfg_loop[7:0]=8'h20;
        repeat(2) @(negedge clk); while(!cfg_ready[0]) @(negedge clk); cfg_valid[0]=1;
        @(negedge clk); cfg_valid[0]=0;
        wait(ready[0]);
        @(negedge clk); start_play[0]=1; apply_valid=1;
        @(negedge clk); start_play[0]=0; apply_valid=0;
        wait(apply_done);
        check_sample(16'sd8); check_sample(16'sd16); check_sample(-16'sd8); check_sample(-16'sd16);
        if(active[0] || !done_seen || underrun || config_error || memory_error)
            $fatal(1,"integrated one-shot status failed");
        $display("PASS: PSRAM-model prefetch to PCM mixer, four signed samples and one-shot completion");
        $finish;
    end
    initial begin #2000000; $fatal(1,"PCM audio path timeout"); end
endmodule
