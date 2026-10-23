`timescale 1ns/1ps
// Public register interface + ordered engine + physical wave RAM + synth.
module tb_audio_core;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,valid=0,wr_req=0,vblank=0,full=0,uf=0,muted=0;
    reg [4:0] addr=0; reg [7:0] data=0;
    wire ready,rsp_valid,rsp_error,init_done,sv;
    wire [7:0] rdata,status;
    wire signed [15:0] left_sample,right_sample;
    kagura_core #(.CAPS(8'h13)) dut(.clk(clk),.reset(reset),.req_valid(valid),.req_ready(ready),.req_write(wr_req),
        .req_addr(addr),.req_wdata(data),.rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rdata),.rsp_error(rsp_error),
        .irq(),.init_done(init_done),.audio_full(full),.audio_underflow_toggle(uf),.audio_muted(muted),
        .audio_sample_valid(sv),.audio_left(left_sample),.audio_right(right_sample),.audio_status(status),
        .render_start(1'b0),.render_line(8'b0),.line_write(),.line_addr(),.line_data(),.line_read(),.line_rdata(16'b0),
        .render_done(),.vblank_start(vblank),.vblank_live(1'b0),.underrun_event(1'b0),.line_start(1'b0),.shown_line(8'b0),.render_cycles());
    reg [7:0] value;
    task automatic access(input bit w,input [4:0] a,input [7:0] d,input bit err=0);
        @(negedge clk); valid=1; wr_req=w; addr=a; data=d;
        @(posedge clk); while(!ready) @(posedge clk);
        #1; valid=0; @(posedge clk); #1;
        if(!rsp_valid || rsp_error!==err) $fatal(1,"access w=%0d a=%02h d=%02h error=%b expected=%b",w,a,d,rsp_error,err);
        value=rdata;
    endtask
    task automatic aw(input [7:0] i,input [7:0] d);
        access(1,12,i); access(1,13,d);
    endtask
    task automatic ar(input [7:0] i,input [7:0] expected_value);
        access(1,12,i); access(0,13,0);
        if(value!==expected_value) $fatal(1,"audio index %02h = %02h expected %02h",i,value,expected_value);
    endtask
    task automatic set_addr(input [15:0] a);
        access(1,4,a[7:0]); access(1,5,a[15:8]); access(1,6,0);
    endtask
    task automatic fill_wave(input [15:0] a,input [7:0] d);
        set_addr(a); access(1,18,0); access(1,19,1); access(1,20,d); access(1,14,1);
    endtask
    task automatic fence(input [7:0] tag);
        access(1,21,tag); access(1,14,2);
        do access(0,22,0); while(value!=tag);
    endtask
    task automatic sample_check(input integer l,input integer r,input integer n);
        repeat(n) begin
            @(negedge clk); while(!sv) @(negedge clk);
            if($signed(left_sample)!=l || $signed(right_sample)!=r)
                $fatal(1,"PCM %0d,%0d expected %0d,%0d",left_sample,right_sample,l,r);
        end
    endtask
    task automatic release_commit;
        @(negedge clk); vblank=1; @(negedge clk); vblank=0;
    endtask
    integer swaps=0,checked=0;
    always @(posedge clk) if(!reset && dut.wave_swap) swaps=swaps+1;
    initial begin
        #100; @(negedge clk); reset=0; wait(init_done);
        access(0,28,0); if(value!=8'h13) $fatal(1,"audio/sprite CAPS");
        ar(8'he0,32); ar(8'h47,5); ar(8'h57,5); ar(8'h00,0);
        aw(8'h0f,255); ar(8'h0f,0); // reserved fields ignored
        access(1,12,8'he1); access(1,13,0,1); // RO
        access(1,12,8'he2); access(0,13,0,1); // WO
        access(1,12,8'h60); access(1,13,0,1); access(0,13,0);
        if(value!=0) $fatal(1,"undefined read");
        aw(8'h46,3); aw(8'h47,8'h85); access(1,14,4,1); ar(8'h46,3);
        aw(8'h47,5); aw(8'h42,128); access(1,14,4,1); ar(8'h46,3); aw(8'h42,0);
        access(1,23,255); access(1,1,127);
        fill_wave(16'h9800,64); fill_wave(16'h9900,8'hc0); fence(1);
        aw(8'h40,1); aw(8'h44,255); aw(8'h56,3); aw(8'h50,1); aw(8'h55,255);
        // Block the audio token behind a video COMMIT. Later shadow edits
        // must not affect the admitted snapshot, and refusal retains reset.
        access(1,14,3); access(1,14,4); ar(8'h46,1);
        aw(8'h44,128); aw(8'h46,3); access(1,14,4,1); ar(8'h46,3);
        if(!status[0] || swaps!=0) $fatal(1,"premature apply");
        // These writes must land in the old active bank AFTER the swap.
        fill_wave(16'h9800,8'he0); fill_wave(16'h9900,32);
        release_commit(); fence(2);
        if(status[0] || swaps!=1) $fatal(1,"ordered audio completion");
        sample_check(2040,-2040,8);
        set_addr(16'h9800); access(1,8,0);
        do access(0,0,0); while(!value[2]); access(0,9,0);
        if(value!=8'he0) $fatal(1,"shadow bank read");
        access(1,14,4); ar(8'h46,1); fence(3);
        // Wait for the first post-apply sample to finish (23 cycles).
        repeat(30) @(negedge clk); sample_check(-512,1020,8);
        if(swaps!=2) $fatal(1,"second bank swap");
        // FIFO events clear independently from global ERROR_CODE / IRQ.
        access(1,23,255); access(1,1,127);
        @(negedge clk); full=1; wait(sv); repeat(3) @(negedge clk); full=0;
        uf=1; muted=1; repeat(8) @(negedge clk);
        if(status[3:1]!=7) $fatal(1,"FIFO status %02h",status);
        aw(8'he2,6); if(status[2:1]!=0) $fatal(1,"local clear");
        access(0,23,0); if(value!=64) $fatal(1,"global error independent %02h",value);
        access(0,1,0); if(!value[6]) $fatal(1,"IRQ error missing");
        access(1,23,64); access(1,1,64);
        uf=0; repeat(8) @(negedge clk); if(!status[1]) $fatal(1,"underflow did not rearm");
        aw(8'he2,6); access(1,23,255); access(1,1,127);
        // Fill queue behind a waiting video COMMIT. Rejected AUDIO_COMMIT
        // must leave the phase-reset request and bank untouched.
        access(1,14,3); repeat(32) access(1,14,2);
        aw(8'h46,3); access(1,14,4,1); ar(8'h46,3);
        if(status[0] || swaps!=2) $fatal(1,"full refusal captured snapshot");
        release_commit();
        do access(0,0,0); while(value[7]);
        fence(4);
        $display("PASS: audio register ABI, invalid/full/busy refusal, snapshot, ordered dual wave bank swaps, stereo PCM, FIFO sticky clear/rearm and IRQ");
        $finish;
    end
    initial begin #20000000; $fatal(1,"audio core timeout"); end
endmodule
