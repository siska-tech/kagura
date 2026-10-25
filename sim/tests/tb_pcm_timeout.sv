// SPDX-License-Identifier: Apache-2.0
module tb_pcm_timeout;
    localparam integer AW=8;
    reg clk=0,reset=1;
    always #5 clk=~clk;
    reg [1:0] cfg_valid=0;
    wire [1:0] cfg_ready,ready,memory_error;
    wire mem_req_valid;
    wire [AW-1:0] mem_req_addr;
    reg mem_rsp_valid=0;
    reg error_seen=0;

    always @(posedge clk) if(memory_error[0]) error_seen<=1;

    kagura_pcm_prefetch #(
        .ADDR_WIDTH(AW),.BUFFER_ADDR_BITS(2),.MEMORY_BYTES(9'd128),.RESPONSE_TIMEOUT(5)
    ) dut(
        .clk(clk),.reset(reset),.sample_tick(1'b0),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),
        .cfg_start({8'b0,8'h20}),.cfg_end({8'b0,8'h24}),.cfg_loop({8'b0,8'h20}),
        .cfg_loop_enable(2'b0),.start_play(2'b0),.stop_play(2'b0),.ready(ready),
        .active(),.done(),.underrun(),.config_error(),.memory_error(memory_error),
        .sample0(),.sample1(),.mem_req_valid(mem_req_valid),.mem_req_ready(1'b1),
        .mem_req_addr(mem_req_addr),.mem_rsp_valid(mem_rsp_valid),.mem_rsp_data(8'haa),
        .mem_rsp_error(1'b0));

    initial begin
        repeat(3) @(posedge clk); reset=0;
        wait(cfg_ready[0]); @(negedge clk); cfg_valid[0]=1;
        @(negedge clk); cfg_valid[0]=0;
        wait(mem_req_valid); repeat(7) @(posedge clk); #1;
        if(!error_seen || ready[0] || cfg_ready[0])
            $fatal(1,"timeout did not invalidate and hold for response drain");

        // The late response is consumed without entering the buffer, after
        // which a fresh configuration can be accepted safely.
        @(negedge clk); mem_rsp_valid=1;
        @(negedge clk); mem_rsp_valid=0;
        wait(cfg_ready[0]);
        if(ready[0] || dut.count[0]!=0) $fatal(1,"late response contaminated buffer");
        @(negedge clk); cfg_valid[0]=1;
        @(negedge clk); cfg_valid[0]=0;
        if(mem_req_addr!=8'h20) $fatal(1,"fresh configuration did not restart at START");

        $display("PASS: PCM response timeout, late-response drain and clean reconfiguration");
        $finish;
    end
endmodule
