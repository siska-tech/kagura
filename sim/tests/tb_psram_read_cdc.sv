// SPDX-License-Identifier: Apache-2.0
module tb_psram_read_cdc;
    localparam integer AW=12;
    reg sys_clk=0,mem_clk=0,sys_reset=1,mem_reset=1;
    always #7 sys_clk=~sys_clk;
    always #11 mem_clk=~mem_clk;
    reg sys_req_valid=0;
    reg [AW-1:0] sys_req_addr=0;
    wire sys_req_ready,sys_rsp_valid,sys_rsp_error;
    wire [7:0] sys_rsp_data;
    wire mem_req_valid;
    reg mem_req_ready=0;
    wire [AW-1:0] mem_req_addr;
    reg mem_rsp_valid=0,mem_rsp_error=0;
    reg [7:0] mem_rsp_data=0;
    reg pending=0;
    reg [AW-1:0] pending_addr=0;
    integer delay_count=0,accepted=0,completed=0;

    kagura_psram_read_cdc #(.ADDR_WIDTH(AW)) dut(
        .sys_clk(sys_clk),.sys_reset(sys_reset),.sys_req_valid(sys_req_valid),
        .sys_req_ready(sys_req_ready),.sys_req_addr(sys_req_addr),
        .sys_rsp_valid(sys_rsp_valid),.sys_rsp_data(sys_rsp_data),.sys_rsp_error(sys_rsp_error),
        .mem_clk(mem_clk),.mem_reset(mem_reset),.mem_req_valid(mem_req_valid),
        .mem_req_ready(mem_req_ready),.mem_req_addr(mem_req_addr),
        .mem_rsp_valid(mem_rsp_valid),.mem_rsp_data(mem_rsp_data),.mem_rsp_error(mem_rsp_error));

    always @(posedge mem_clk) begin
        mem_req_ready<=($time%5)!=0;
        mem_rsp_valid<=0;
        mem_rsp_error<=0;
        if(mem_req_valid && mem_req_ready) begin
            if(pending) $fatal(1,"second controller request while pending");
            pending<=1;
            pending_addr<=mem_req_addr;
            delay_count<=int'(mem_req_addr[2:0])%5;
            accepted<=accepted+1;
        end
        if(pending) begin
            if(delay_count==0) begin
                pending<=0;
                mem_rsp_valid<=1;
                mem_rsp_data<=pending_addr[7:0]^8'h5a;
                mem_rsp_error<=pending_addr==12'hbad;
            end else delay_count<=delay_count-1;
        end
    end

    task automatic read_check(input [AW-1:0] address);
        begin
            @(negedge sys_clk); wait(sys_req_ready);
            sys_req_addr=address; sys_req_valid=1;
            @(negedge sys_clk); sys_req_valid=0;
            if(sys_req_ready) $fatal(1,"CDC accepted a second outstanding request");
            do @(negedge sys_clk); while(!sys_rsp_valid);
            if(sys_rsp_data!==(address[7:0]^8'h5a) || sys_rsp_error!==(address==12'hbad))
                $fatal(1,"CDC response mismatch for %h",address);
            completed=completed+1;
        end
    endtask

    initial begin
        repeat(4) @(posedge sys_clk); sys_reset=0;
        repeat(3) @(posedge mem_clk); mem_reset=0;
        for(integer i=0;i<300;i=i+1) read_check(12'((i*73)^12'h5a3));
        read_check(12'hbad);
        if(accepted!=301 || completed!=301) $fatal(1,"CDC request count %0d/%0d",accepted,completed);

        // A simultaneous reset clears both toggle epochs and permits reuse.
        @(negedge sys_clk); sys_reset=1; mem_reset=1;
        repeat(3) @(posedge sys_clk); sys_reset=0;
        repeat(3) @(posedge mem_clk); mem_reset=0;
        read_check(12'h123);
        $display("PASS: PSRAM read CDC, 302 requests, async clocks, backpressure, latency, error and reset");
        $finish;
    end
    initial begin #2000000; $fatal(1,"PSRAM CDC timeout"); end
endmodule
