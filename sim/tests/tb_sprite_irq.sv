`timescale 1ns/1ps
module tb_sprite_irq;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,valid=0,write_req=0;
    reg [4:0] addr=0;
    reg [7:0] wdata=0,events=0,ov_line=0;
    reg [7:0] ov_index=0;
    wire ready,rsp_valid,rsp_error,irq;
    wire [7:0] rdata;
    reg [7:0] value;
    kagura_registers dut(.clk(clk),.reset(reset),.init_done(1'b1),.vblank_live(1'b0),
        .irq_events(events),.sprite_overflow_index(ov_index),.sprite_overflow_line(ov_line),.error_events(8'b0),
        .req_valid(valid),.req_ready(ready),.req_write(write_req),.req_addr(addr),.req_wdata(wdata),
        .rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rdata),.rsp_error(rsp_error),.irq(irq),
        .push(),.push_desc(),.push_ready(1'b1),.queue_free(6'd32),.queue_idle(1'b1),.queue_staging(1'b0),
        .engine_busy(1'b0),.read_done(1'b0),.read_data(8'b0),.fence_done(1'b0),.fence_tag(8'b0),.commit_done(1'b0),
        .audio_index(8'b0),.audio_rdata(8'b0),.audio_read_legal(1'b1),.audio_write_legal(1'b0),
        .audio_settings_valid(1'b1),.audio_busy(1'b0),.audio_index_write(),.audio_data_write(),.audio_capture(),.audio_wdata(),
        .display_ctrl(),.scroll_x(),.scroll_y(),.backdrop(),.raster_line());
    task automatic access(input reg wr,input reg[4:0] a,input reg[7:0] d,input reg simultaneous);
        begin
            @(negedge clk); valid=1; write_req=wr; addr=a; wdata=d;
            @(posedge clk); while(!ready) @(posedge clk);
            @(negedge clk); valid=0; if(simultaneous) events=8'h20;
            @(posedge clk); #1;
            if(!rsp_valid || rsp_error) $fatal(1,"register response");
            value=rdata;
            @(negedge clk); events=0;
        end
    endtask
    task automatic pulse(input reg[7:0] n,input reg[7:0] y);
        begin
            @(negedge clk); ov_index=n; ov_line=y; events=8'h20;
            @(negedge clk); events=0;
        end
    endtask
    task automatic expect_capture(input reg[7:0] n,input reg[7:0] y,input reg flag);
        begin
            access(0,5'h1e,0,0); if(value!=n) $fatal(1,"index %d expected %d",value,n);
            access(0,5'h1f,0,0); if(value!=y) $fatal(1,"line %d expected %d",value,y);
            access(0,5'h01,0,0); if(value[5]!=flag) $fatal(1,"IRQ sticky flag");
        end
    endtask
    initial begin
        #100; @(negedge clk); reset=0;
        expect_capture(0,0,0);
        pulse(16,10); expect_capture(16,10,1);
        if(irq) $fatal(1,"IRQ ignores enable");
        access(1,5'h02,8'h20,0); if(!irq) $fatal(1,"enabled pending IRQ");
        pulse(17,11); expect_capture(16,10,1); // first wins across lines
        access(1,5'h01,8'h01,0); expect_capture(16,10,1); // unrelated W1C
        access(1,5'h01,8'h20,0); expect_capture(0,0,0);
        if(irq) $fatal(1,"IRQ not cleared");
        pulse(255,239); expect_capture(255,239,1);
        ov_index=8'd223; ov_line=8'd100;
        access(1,5'h01,8'h20,1); expect_capture(223,100,1); // new event wins clear
        @(negedge clk); reset=1;
        @(negedge clk); reset=0;
        expect_capture(0,0,0);
        $display("PASS: sprite overflow capture, sticky first event, enable, unrelated W1C, clear/event priority and reset");
        $finish;
    end
    initial begin #100000; $fatal(1,"timeout"); end
endmodule
