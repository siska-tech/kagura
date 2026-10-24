// SPDX-License-Identifier: Apache-2.0
module tb_boot_window;
    reg clk=0,reset=1,prepare=0,payload_valid=0,req_valid=0,req_write=0,rsp_ready=1;
    reg [7:0] payload_data=0,req_wdata=0;
    reg [4:0] req_addr=0;
    wire payload_ready,req_ready,rsp_valid,rsp_error,vector_high_read;
    wire [7:0] rsp_rdata;
    integer failures=0,payload_consumed=0;
    reg saw_vector_high=0;

    kagura_boot_window dut(clk,reset,prepare,16'h0200,16'h2345,32'd256,
        payload_valid,payload_ready,payload_data,req_valid,req_ready,req_write,
        req_addr,req_wdata,rsp_valid,rsp_ready,rsp_rdata,rsp_error,vector_high_read);
    always #5 clk=~clk;
    always @(posedge clk) begin
        if(payload_valid && payload_ready) payload_consumed=payload_consumed+1;
        if(vector_high_read) saw_vector_high=1;
    end

    task automatic read_byte(input [4:0] address,input [7:0] expected);
        begin
            @(negedge clk);
            while(!req_ready) @(negedge clk);
            req_addr=address; req_write=0; req_valid=1;
            @(posedge clk); @(negedge clk); req_valid=0;
            while(!rsp_valid) @(posedge clk);
            if(rsp_error || rsp_rdata!==expected) begin
                $display("FAIL: read %02x got %02x error=%0d expected %02x",
                    address,rsp_rdata,rsp_error,expected); failures=failures+1;
            end
            @(posedge clk);
        end
    endtask
    task automatic port_payload(input [7:0] value);
        begin
            @(negedge clk); payload_data=value; payload_valid=1;
            read_byte(5'h1a,value);
            @(negedge clk); payload_valid=0;
        end
    endtask

    initial begin
        #100000;
        $fatal(1,"timeout");
    end

    initial begin
        repeat(4) @(posedge clk); reset=0;
        prepare=1; @(posedge clk); prepare=0;
        read_byte(5'h00,8'h64); read_byte(5'h02,8'had);
        read_byte(5'h19,8'h00);
        // A reset-sequence dummy access must not consume the stream.
        read_byte(5'h1a,8'h00);
        if(payload_consumed!=0) begin $display("FAIL: pre-vector consume"); failures=failures+1; end
        read_byte(5'h1c,8'he0); read_byte(5'h1d,8'hff);
        read_byte(5'h1a,8'h02); // destination page
        read_byte(5'h1a,8'h01); // page count

        // The endpoint must stall a payload port request until a byte exists.
        @(negedge clk); req_addr=5'h1a; req_valid=1; repeat(3) @(posedge clk);
        if(req_ready) begin $display("FAIL: missing payload did not stall"); failures=failures+1; end
        @(negedge clk); payload_data=8'h5a; payload_valid=1;
        #1;
        if(!req_ready) begin $display("FAIL: payload did not release stall"); failures=failures+1; end
        @(posedge clk); @(negedge clk); req_valid=0; payload_valid=0;
        while(!rsp_valid) @(posedge clk);
        if(rsp_rdata!=8'h5a) begin $display("FAIL: stalled payload value"); failures=failures+1; end
        @(posedge clk);
        port_payload(8'ha6);
        if(payload_consumed!=2) begin $display("FAIL: payload count %0d",payload_consumed); failures=failures+1; end

        read_byte(5'h1e,8'h45); read_byte(5'h1f,8'h23); @(negedge clk);
        if(!saw_vector_high) begin $display("FAIL: vector high pulse"); failures=failures+1; end

        @(negedge clk); req_addr=0; req_write=1; req_wdata=8'hcc; req_valid=1;
        while(!req_ready) @(negedge clk); @(posedge clk); @(negedge clk); req_valid=0;
        while(!rsp_valid) @(posedge clk);
        if(!rsp_error) begin $display("FAIL: write not rejected"); failures=failures+1; end
        if(failures!=0) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: boot stub, vectors, guarded data port and backpressure");
        $finish;
    end
endmodule
