// SPDX-License-Identifier: Apache-2.0
// Boot window: stray reads (CPU held in reset, reset-sequence dummy reads at an undefined PC) must neither arm the data port
// nor end the boot. The port arms only on $FFFD directly after $FFFC; the unmap pulse needs $FFFF directly after $FFFE, armed.
module tb_boot_window_order;
    reg clk=0,reset=1,prepare=0,payload_valid=0,req_valid=0,req_write=0,rsp_ready=1;
    reg [7:0] payload_data=0,req_wdata=0;
    reg [4:0] req_addr=0;
    wire payload_ready,req_ready,rsp_valid,rsp_error,vector_high_read;
    wire [7:0] rsp_rdata;
    integer failures=0,payload_consumed=0,pulses=0;

    kagura_boot_window dut(clk,reset,prepare,16'h0200,16'h2345,32'd256,
        payload_valid,payload_ready,payload_data,req_valid,req_ready,req_write,
        req_addr,req_wdata,rsp_valid,rsp_ready,rsp_rdata,rsp_error,vector_high_read,2'b11);
    always #5 clk=~clk;
    always @(posedge clk) begin
        if(payload_valid && payload_ready) payload_consumed=payload_consumed+1;
        if(vector_high_read) pulses=pulses+1;
    end
    task automatic read_byte(input [4:0] address,input [7:0] expected);
        begin
            @(negedge clk);
            while(!req_ready) @(negedge clk);
            req_addr=address; req_write=0; req_valid=1;
            @(posedge clk); @(negedge clk); req_valid=0;
            while(!rsp_valid) @(posedge clk);
            if(rsp_error || rsp_rdata!==expected) begin
                $display("FAIL: read %02x got %02x error=%0d expected %02x",address,rsp_rdata,rsp_error,expected); failures=failures+1;
            end
            @(posedge clk);
        end
    endtask
    task automatic expect_state(input integer want_pulses,input integer want_consumed,input string what);
        begin
            @(negedge clk);
            if(pulses!=want_pulses || payload_consumed!=want_consumed) begin
                $display("FAIL: %s: unmap pulses %0d (want %0d), payload consumed %0d (want %0d)",what,pulses,want_pulses,payload_consumed,want_consumed);
                failures=failures+1;
            end
        end
    endtask
    task automatic fresh();
        begin @(negedge clk); reset=1; repeat(2) @(posedge clk); @(negedge clk); reset=0; prepare=1; @(posedge clk); @(negedge clk); prepare=0;
            pulses=0; payload_consumed=0; end
    endtask
    integer a, b;
    initial begin
        // 1. any single stray read, and every ordered pair of stray reads, before the reset vector: no pulse, no arming
        for(a=5'h19;a<=5'h1f;a=a+1) begin   // $FFF9 (stub BRK) .. $FFFF
            fresh();
            read_byte(a[4:0], a==5'h1c ? 8'he0 : a==5'h1d ? 8'hff : a==5'h1e ? 8'h45 : a==5'h1f ? 8'h23 : 8'h00);
            read_byte(5'h1a,8'h00);   // port still disarmed: returns 0, consumes nothing
            expect_state(0,0,$sformatf("single stray read of offset %02x",a));
        end
        // dummy reads repeat one address (65C02 reset sequence at an undefined PC), then the real vector fetch
        for(a=5'h1a;a<=5'h1f;a=a+1) begin
            fresh();
            read_byte(a[4:0], a==5'h1c ? 8'he0 : a==5'h1d ? 8'hff : a==5'h1e ? 8'h45 : a==5'h1f ? 8'h23 : 8'h00);
            read_byte(a[4:0], a==5'h1c ? 8'he0 : a==5'h1d ? 8'hff : a==5'h1e ? 8'h45 : a==5'h1f ? 8'h23 : 8'h00);
            expect_state(0,0,$sformatf("dummy reads at PC = offset %02x twice",a));
            read_byte(5'h1c,8'he0); read_byte(5'h1d,8'hff);                     // reset vector -> armed
            read_byte(5'h1a,8'h02); read_byte(5'h1a,8'h01);                     // destination page, page count
            expect_state(0,0,$sformatf("after dummy %02x x2 + reset vector: armed, no pulse",a));
        end
        // 2. $FFFE, $FFFF before arming: no pulse; $FFFD without $FFFC: no arming
        fresh();
        read_byte(5'h1e,8'h45); read_byte(5'h1f,8'h23);
        read_byte(5'h1d,8'hff); read_byte(5'h1a,8'h00);
        expect_state(0,0,"BRK vector order before arming, $FFFD alone");
        // 3. normal order still works: reset vector arms, BRK vector ends the boot (exactly one pulse)
        read_byte(5'h1c,8'he0); read_byte(5'h1d,8'hff);
        read_byte(5'h1a,8'h02); read_byte(5'h1a,8'h01);
        for(b=0;b<3;b=b+1) begin @(negedge clk); payload_data=8'h10+b; payload_valid=1; read_byte(5'h1a,8'h10+b); @(negedge clk); payload_valid=0; end
        read_byte(5'h1f,8'h23);                                                    // $FFFF after a port read: no pulse
        expect_state(0,3,"armed, $FFFF not after $FFFE");
        read_byte(5'h1e,8'h45); read_byte(5'h1f,8'h23);
        expect_state(1,3,"armed, $FFFE then $FFFF: one unmap pulse");
        // 4. a write between $FFFE and $FFFF breaks the pair
        fresh();
        read_byte(5'h1c,8'he0); read_byte(5'h1d,8'hff);
        read_byte(5'h1e,8'h45);
        @(negedge clk); req_addr=5'h1e; req_write=1; req_valid=1; while(!req_ready) @(negedge clk); @(posedge clk); @(negedge clk); req_valid=0; req_write=0;
        while(!rsp_valid) @(posedge clk); @(posedge clk);
        read_byte(5'h1f,8'h23);
        expect_state(0,0,"write between $FFFE and $FFFF: no pulse");
        if(failures!=0) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: boot window vector order: stray single / repeated reads before the reset vector neither arm nor unmap; reset vector arms; BRK vector order unmaps once");
        $finish;
    end
    initial begin #2000000; $fatal(1,"timeout"); end
endmodule
