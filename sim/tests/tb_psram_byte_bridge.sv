// SPDX-License-Identifier: Apache-2.0
module tb_psram_byte_bridge;
    reg clk=0,reset=1,controller_ready=0,req_valid=0;
    reg [7:0] req_addr=0;
    wire req_ready,rsp_valid,rsp_error,ctrl_cmd,ctrl_cmd_en;
    wire [5:0] ctrl_addr;
    wire [7:0] rsp_data;
    reg ctrl_cmd_rdy=0,ctrl_rd_data_valid=0;
    reg [31:0] ctrl_rd_data=0;
    integer accepted=0;
    reg byte_req_valid=0;
    reg [7:0] byte_req_addr=0;
    wire byte_req_ready,byte_ctrl_cmd_en;
    wire [7:0] byte_ctrl_addr;

    kagura_psram_byte_bridge #(
        .BYTE_ADDR_WIDTH(8),.CTRL_ADDR_WIDTH(6),.CTRL_ADDR_SHIFT(2)
    ) dut(
        .clk(clk),.reset(reset),.controller_ready(controller_ready),.cache_flush(1'b0),
        .req_valid(req_valid),.req_ready(req_ready),.req_addr(req_addr),
        .rsp_valid(rsp_valid),.rsp_data(rsp_data),.rsp_error(rsp_error),
        .ctrl_cmd(ctrl_cmd),.ctrl_cmd_en(ctrl_cmd_en),.ctrl_cmd_rdy(ctrl_cmd_rdy),
        .ctrl_addr(ctrl_addr),.ctrl_rd_data(ctrl_rd_data),
        .ctrl_rd_data_valid(ctrl_rd_data_valid));

    kagura_psram_byte_bridge #(
        .BYTE_ADDR_WIDTH(8),.CTRL_ADDR_WIDTH(8),.CTRL_ADDR_SHIFT(0)
    ) byte_addressed_dut(
        .clk(clk),.reset(reset),.controller_ready(controller_ready),.cache_flush(1'b0),
        .req_valid(byte_req_valid),.req_ready(byte_req_ready),.req_addr(byte_req_addr),
        .rsp_valid(),.rsp_data(),.rsp_error(),.ctrl_cmd(),.ctrl_cmd_en(byte_ctrl_cmd_en),
        .ctrl_cmd_rdy(1'b1),.ctrl_addr(byte_ctrl_addr),.ctrl_rd_data(32'b0),
        .ctrl_rd_data_valid(1'b0));

    always #5 clk=~clk;
    always @(posedge clk) if(ctrl_cmd_en) accepted<=accepted+1;

    task automatic request(input [7:0] address);
        begin
            @(negedge clk); req_addr=address; req_valid=1;
            wait(req_ready); @(negedge clk); req_valid=0;
        end
    endtask
    task automatic respond(input [31:0] word);
        begin
            @(negedge clk); ctrl_rd_data=word; ctrl_rd_data_valid=1;
            @(negedge clk); ctrl_rd_data_valid=0;
        end
    endtask

    initial begin
        repeat(3) @(posedge clk); reset=0;
        @(negedge clk); controller_ready=1;

        // Controller backpressure must propagate without accepting repeatedly.
        req_addr=8'h0b; req_valid=1;
        repeat(3) @(posedge clk);
        if(req_ready || ctrl_cmd_en || accepted!=0) $fatal(1,"request bypassed controller backpressure");
        @(negedge clk); ctrl_cmd_rdy=1;
        @(posedge clk); #1;
        if(ctrl_addr!=6'h02 || ctrl_cmd!=1'b0 || accepted!=1)
            $fatal(1,"address or command mapping failed");
        @(negedge clk); req_valid=0;
        if(req_ready) $fatal(1,"second request accepted while response pending");
        respond(32'hd3c2b1a0);
        #1;
        if(!rsp_valid || rsp_error || rsp_data!=8'hd3) $fatal(1,"byte lane 3 failed");

        // Remaining bytes in the same word are served without new commands,
        // even when the controller command port is backpressured.
        ctrl_cmd_rdy=0;
        request(8'h08);
        #1;
        if(!rsp_valid || rsp_data!=8'ha0) $fatal(1,"byte lane 0 cache hit failed");
        request(8'h09);
        #1;
        if(!rsp_valid || rsp_data!=8'hb1) $fatal(1,"byte lane 1 cache hit failed");
        request(8'h0a);
        #1;
        if(!rsp_valid || rsp_data!=8'hc2 || accepted!=1)
            $fatal(1,"byte lane 2 cache hit issued another command");

        // Losing calibration converts the pending operation to an error.
        ctrl_cmd_rdy=1;
        request(8'h10);
        @(negedge clk); controller_ready=0;
        @(posedge clk); #1;
        if(!rsp_valid || !rsp_error) $fatal(1,"controller loss did not fail pending read");

        // A byte-addressed controller still receives an aligned word address.
        @(negedge clk); controller_ready=1; byte_req_addr=8'h0b; byte_req_valid=1; #1;
        if(!byte_ctrl_cmd_en || byte_ctrl_addr!=8'h08)
            $fatal(1,"byte-addressed controller request was not word aligned");
        @(negedge clk); byte_req_valid=0;

        $display("PASS: PSRAM byte bridge backpressure, four-byte cache, alignment and controller loss");
        $finish;
    end
endmodule
