`timescale 1ns/1ps
// Back-to-back requests at the register window's maximum rate: a FILL right
// after the VRAM_ADDR/LENGTH writes, and right after a VRAM_WRITE advanced
// the address, must be judged on the new range. Guards the two-stage FILL
// range check in kagura_registers (and its settle assertion).
module tb_fill_timing;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,valid=0,write_req=0;
    reg [4:0] addr=0;
    reg [7:0] wdata=0;
    wire ready,rsp_valid,rsp_error,push;
    wire [63:0] push_desc;
    wire [7:0] rdata;
    integer pushes=0;
    always @(posedge clk) if(push) pushes=pushes+1;
    kagura_registers dut(.clk(clk),.reset(reset),.init_done(1'b1),.vblank_live(1'b0),
        .irq_events(8'b0),.sprite_overflow_index(8'b0),.sprite_overflow_line(8'b0),.error_events(8'b0),
        .req_valid(valid),.req_ready(ready),.req_write(write_req),.req_addr(addr),.req_wdata(wdata),
        .rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rdata),.rsp_error(rsp_error),.irq(),
        .push(push),.push_desc(push_desc),.push_ready(1'b1),.queue_free(6'd32),.queue_idle(1'b1),.queue_staging(1'b0),
        .engine_busy(1'b0),.read_done(1'b0),.read_data(8'b0),.fence_done(1'b0),.fence_tag(8'b0),.commit_done(1'b0),
        .audio_index(8'b0),.audio_rdata(8'b0),.audio_read_legal(1'b1),.audio_write_legal(1'b0),
        .audio_settings_valid(1'b1),.audio_busy(1'b0),.audio_index_write(),.audio_data_write(),.audio_capture(),.audio_wdata(),
        .display_ctrl(),.scroll_x(),.scroll_y(),.backdrop(),.raster_line());
    // Hold valid continuously; a new request goes out the cycle after acceptance.
    reg err;
    task automatic write1(input reg[4:0] a,input reg[7:0] d);
        begin
            valid=1; write_req=1; addr=a; wdata=d;
            @(posedge clk); while(!ready) @(posedge clk);
            #1; valid=0;
            while(!rsp_valid) @(posedge clk);
            #1; err=rsp_error;
        end
    endtask
    task automatic fill_at(input [23:0] a,input [15:0] len,input expect_ok);
        integer pushes0;
        begin
            write1(5'h04,a[7:0]); write1(5'h05,a[15:8]); write1(5'h06,a[23:16]);
            write1(5'h12,len[7:0]); write1(5'h13,len[15:8]);
            pushes0=pushes;
            write1(5'h0e,8'h01);
            if(err==expect_ok) $fatal(1,"FILL at %06h len %0d: error %b",a,len,err);
            @(posedge clk); @(posedge clk);
            if((pushes-pushes0)!=(expect_ok ? 1 : 0)) $fatal(1,"FILL at %06h: %0d pushes",a,pushes-pushes0);
            write1(5'h17,8'hff);
        end
    endtask
    initial begin
        #100; @(negedge clk); reset=0;
        repeat(4) @(posedge clk);
        // Alternate valid and invalid ranges so a stale check gives the wrong answer.
        fill_at(24'h007f00,16'd256,1);   // ends at 007FFF
        fill_at(24'h007f00,16'd257,0);   // crosses into map
        fill_at(24'h008000,16'd4096,1);  // whole map
        fill_at(24'h009000,16'd256,1);   // complete BG tile-bit10 table
        fill_at(24'h0090ff,16'd2,0);     // table into hole
        fill_at(24'h009100,16'd1,0);     // unimplemented
        fill_at(24'h00b000,16'd5632,1);  // all 176 extra patterns
        fill_at(24'h00c5ff,16'd2,0);     // extra patterns into hole
        fill_at(24'h007fff,16'h3002,0);  // cannot bridge map/table/palette holes
        fill_at(24'h009400,16'd512,1);   // palette shadow
        fill_at(24'h00a7ff,16'd2,0);     // OAM shadow into active OAM
        // VRAM_WRITE advances the address; the FILL right after uses the new one.
        write1(5'h10,8'h01); write1(5'h11,8'h00);
        write1(5'h04,8'hff); write1(5'h05,8'h7f); write1(5'h06,8'h00);
        write1(5'h12,8'h01); write1(5'h13,8'h00);
        write1(5'h07,8'h55);               // 007FFF -> 008000
        write1(5'h0e,8'h01);               // 1-byte FILL at 008000: valid
        if(err) $fatal(1,"FILL after VRAM_WRITE advance refused");
        write1(5'h12,8'h00); write1(5'h13,8'h10);
        write1(5'h07,8'h55);               // 008000 -> 008001
        write1(5'h0e,8'h01);               // 4096 bytes from 008001 crosses the map end
        if(!err) $fatal(1,"FILL after VRAM_WRITE advance accepted a crossing range");
        $display("PASS: back-to-back FILL range checks after ADDR/LENGTH writes and VRAM_WRITE advance, %0d pushes",pushes);
        $finish;
    end
endmodule
