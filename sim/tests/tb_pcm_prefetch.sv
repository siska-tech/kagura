// SPDX-License-Identifier: Apache-2.0
module tb_pcm_prefetch;
    localparam integer AW=8;
    reg clk=0,reset=1,sample_tick=0;
    reg [1:0] cfg_valid=0,start_play=0,stop_play=0,cfg_loop_enable=0;
    wire [1:0] cfg_ready,ready,active,done,underrun,config_error,memory_error;
    reg [2*AW-1:0] cfg_start=0,cfg_end=0,cfg_loop=0;
    wire signed [7:0] sample0,sample1;
    wire mem_req_valid;
    reg mem_req_ready=1;
    wire [AW-1:0] mem_req_addr;
    reg mem_rsp_valid=0,mem_rsp_error=0;
    reg [7:0] mem_rsp_data=0;
    reg [7:0] memory [0:255];
    reg pending=0,hold_response=0,inject_error=0;
    reg [7:0] pending_addr;
    reg signed [7:0] expected_sample;
    reg underrun_seen=0,done0_seen=0,memory_error_seen=0;
    integer delay_count=0,seen0=0,seen1=0,cycles=0;

    kagura_pcm_prefetch #(.ADDR_WIDTH(AW),.BUFFER_ADDR_BITS(3),.MEMORY_BYTES(9'd128)) dut(
        .clk(clk),.reset(reset),.sample_tick(sample_tick),
        .cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_start(cfg_start),.cfg_end(cfg_end),
        .cfg_loop(cfg_loop),.cfg_loop_enable(cfg_loop_enable),.start_play(start_play),.stop_play(stop_play),
        .ready(ready),.active(active),.done(done),.underrun(underrun),
        .config_error(config_error),.memory_error(memory_error),.sample0(sample0),.sample1(sample1),
        .mem_req_valid(mem_req_valid),.mem_req_ready(mem_req_ready),.mem_req_addr(mem_req_addr),
        .mem_rsp_valid(mem_rsp_valid),.mem_rsp_data(mem_rsp_data),.mem_rsp_error(mem_rsp_error));
    always #5 clk=~clk;

    always @(posedge clk) begin
        if(underrun[1]) underrun_seen<=1;
        if(done[0]) done0_seen<=1;
        if(done[1]) $fatal(1,"loop channel unexpectedly completed");
        if(memory_error[0]) memory_error_seen<=1;
        mem_rsp_valid<=0;
        mem_rsp_error<=0;
        if(mem_req_valid && mem_req_ready) begin
            if(pending) $fatal(1,"more than one memory request outstanding");
            pending<=1; pending_addr<=mem_req_addr; delay_count<=cycles%4;
        end
        if(pending && !hold_response) begin
            if(delay_count==0) begin
                mem_rsp_valid<=1; mem_rsp_data<=memory[pending_addr];
                mem_rsp_error<=inject_error; inject_error<=0; pending<=0;
            end else delay_count<=delay_count-1;
        end
        cycles<=cycles+1;
    end

    task automatic tick;
        begin
            @(negedge clk); sample_tick=1;
            @(negedge clk); sample_tick=0;
        end
    endtask
    task automatic arm(input integer ch,input [7:0] s,input [7:0] e,input [7:0] l,input bit looped);
        begin
            wait(cfg_ready[ch]); @(negedge clk);
            cfg_start[ch*AW +:AW]=s; cfg_end[ch*AW +:AW]=e; cfg_loop[ch*AW +:AW]=l;
            cfg_loop_enable[ch]=looped; cfg_valid[ch]=1;
            @(negedge clk); cfg_valid[ch]=0;
        end
    endtask
    task automatic start(input bit ch);
        begin wait(ready[ch]); @(negedge clk); start_play[ch]=1; @(negedge clk); start_play[ch]=0; end
    endtask

    initial begin
        for(integer i=0;i<256;i=i+1) memory[i]=i[7:0];
        repeat(4) @(posedge clk); reset=0;

        // Invalid ranges are rejected without issuing memory traffic.
        arm(0,8'd10,8'd10,8'd10,0);
        @(posedge clk); if(!config_error[0]) $fatal(1,"invalid range accepted");
        arm(0,8'd120,8'd129,8'd120,0);
        @(posedge clk); if(!config_error[0]) $fatal(1,"out-of-capacity range accepted");

        // A short one-shot is completely prefetched and ends without underrun.
        arm(0,8'd20,8'd25,8'd20,0); start(0);
        for(integer n=20;n<25;n=n+1) begin
            tick(); #1;
            if(sample0!==$signed(n[7:0])) $fatal(1,"one-shot sample %0d got %0d",n,sample0);
            seen0=seen0+1;
        end
        @(posedge clk); #1;
        if(active[0] || seen0!=5 || underrun[0] || !done0_seen) $fatal(1,"one-shot completion failed");

        // A failed memory response invalidates and stops only its owner.
        inject_error=1;
        arm(0,8'd60,8'd70,8'd60,0);
        wait(memory_error_seen); @(posedge clk);
        if(active[0] || ready[0]) $fatal(1,"memory error left channel usable");

        // Loop data crosses END back to LOOP while requests have varying delay.
        arm(1,8'd40,8'd44,8'd41,1); start(1);
        for(integer n=0;n<14;n=n+1) begin
            expected_sample=8'(n<4 ? 40+n : 41+((n-4)%3));
            tick(); #1;
            if(sample1!==expected_sample)
                $fatal(1,"loop sample %0d got %0d",n,sample1);
            seen1=seen1+1;
        end

        // Starving a running loop is reported and stops only that channel.
        hold_response=1;
        repeat(10) tick();
        #1; if(!underrun_seen || active[1]) $fatal(1,"starvation did not stop playback");
        if(memory_error!=0 || config_error!=0) $fatal(1,"unexpected late pulse");
        $display("PASS: PCM 2ch prefetch, one-shot, loop, memory error and starvation");
        $finish;
    end
endmodule
