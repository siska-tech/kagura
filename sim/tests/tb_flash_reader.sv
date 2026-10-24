// SPDX-License-Identifier: Apache-2.0
module tb_flash_reader;
    reg clk=0,reset=1,cmd_valid=0,cmd_jedec_id=0,data_ready=0;
    reg [23:0] cmd_addr=0,cmd_byte_count=0;
    wire cmd_ready,data_valid,done,error,cs_n,sclk,mosi;
    wire [7:0] data;
    reg miso=0;
    integer failures=0,received=0;
    reg [7:0] got [0:15];

    kagura_flash_reader #(.CLK_DIV(2)) dut(clk,reset,cmd_valid,cmd_ready,
        cmd_jedec_id,cmd_addr,cmd_byte_count,data_valid,data_ready,data,done,error,
        cs_n,sclk,mosi,miso);
    always #5 clk=~clk;

    // Small mode-0 flash model: decode 9f or 03/address, then shift bytes.
    reg prev_sclk=0;
    reg [7:0] in_shift=0,out_shift=0;
    reg [5:0] in_bits=0;
    reg [2:0] out_bit=0;
    reg [1:0] id_index=0;
    reg outputting=0;
    reg [23:0] address=0;
    reg [7:0] command=0;
    function automatic [7:0] flash_byte(input [23:0] a);
        flash_byte=(a[7:0] ^ 8'h5a);
    endfunction
    always @(posedge clk) begin
        prev_sclk<=sclk;
        if(cs_n) begin
            in_shift<=0; in_bits<=0; out_bit<=0; id_index<=0;
            address<=0; command<=0; outputting<=0; miso<=0;
        end else begin
            if(!prev_sclk && sclk) begin
                in_shift<={in_shift[6:0],mosi};
                in_bits<=in_bits+1'b1;
                if(in_bits==7) begin
                    command<={in_shift[6:0],mosi};
                    if({in_shift[6:0],mosi}==8'h9f) begin
                        out_shift<=8'h85; outputting<=1;
                    end
                end else if(command==8'h03 && in_bits>=8 && in_bits<=31) begin
                    address<={address[22:0],mosi};
                    if(in_bits==31) begin
                        out_shift<=flash_byte({address[22:0],mosi});
                        outputting<=1;
                    end
                end
            end
            if(prev_sclk && !sclk && outputting) begin
                miso<=out_shift[7];
                if(out_bit==7) begin
                    out_bit<=0;
                    if(command==8'h9f) begin
                        id_index<=id_index+1'b1;
                        if(id_index==0) out_shift<=8'h60;
                        else out_shift<=8'h16;
                    end else begin
                        address<=address+1'b1;
                        out_shift<=flash_byte(address+1'b1);
                    end
                end else begin
                    out_shift<={out_shift[6:0],1'b0};
                    out_bit<=out_bit+1'b1;
                end
            end
        end
    end

    always @(posedge clk) if(data_valid && data_ready) begin
        got[received]=data; received=received+1;
    end

    task automatic start(input id, input [23:0] addr, input [23:0] count);
        begin
            while(!cmd_ready) @(posedge clk);
            cmd_jedec_id=id; cmd_addr=addr; cmd_byte_count=count; cmd_valid=1;
            @(posedge clk); cmd_valid=0;
        end
    endtask
    task automatic wait_done;
        begin while(!done) @(posedge clk); @(posedge clk); end
    endtask
    task automatic expect_byte(input integer index,input [7:0] expected);
        begin if(got[index]!==expected) begin
            $display("FAIL: byte %0d got %02x expected %02x",index,got[index],expected);
            failures=failures+1;
        end end
    endtask

    initial begin
        repeat(4) @(posedge clk); reset=0; data_ready=1;
        start(1,0,0); wait_done();
        if(received!=3) begin $display("FAIL: JEDEC count %0d",received); failures=failures+1; end
        expect_byte(0,8'h85); expect_byte(1,8'h60); expect_byte(2,8'h16);

        received=0;
        start(0,24'h100123,4);
        // Exercise backpressure while SCLK must be parked low.
        wait(data_valid); data_ready=0; repeat(7) @(posedge clk);
        if(sclk!==0 || !data_valid) begin $display("FAIL: backpressure"); failures=failures+1; end
        data_ready=1; wait_done();
        if(received!=4) begin $display("FAIL: READ count %0d",received); failures=failures+1; end
        expect_byte(0,8'h79); expect_byte(1,8'h7e); expect_byte(2,8'h7f); expect_byte(3,8'h7c);

        received=0; start(0,0,0); wait_done();
        if(!error) begin $display("FAIL: zero-length command accepted"); failures=failures+1; end
        if(failures!=0) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: SPI flash reader commands and backpressure");
        $finish;
    end
endmodule
