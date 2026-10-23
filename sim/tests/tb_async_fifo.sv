`timescale 1ns/1ps
module tb_async_fifo;
    reg wc=0,rc=0,reset=1,we=0,re=0;
    always #7 wc=~wc;
    always #11 rc=~rc;
    reg [31:0] wd=0;
    wire [31:0] rd;
    wire full,empty,valid,overflow,underflow;
    wire [4:0] level;
    kagura_async_fifo dut(reset,wc,we,wd,full,overflow,rc,re,rd,valid,empty,underflow,level);
    integer sent=0,received=0,phase=0,rcycles=0;
    reg streaming=0,manual_read=0;
    reg [31:0] expected;
    always @(negedge wc) begin
        we=streaming && sent<512 && !full;
        wd=32'h12340000+32'(sent);
    end
    always @(posedge wc) if(!reset && we && !full) sent=sent+1;
    always @(negedge rc) begin
        rcycles=rcycles+1;
        re=manual_read || (streaming && phase!=0 && !empty && (rcycles%5!=0));
    end
    always @(posedge rc) begin
        #1;
        if(!reset && valid) begin
            expected=32'h12340000+32'(received);
            if(rd!==expected) $fatal(1,"FIFO order: got %h expected %h",rd,expected);
            received=received+1;
        end
    end
    initial begin
        #100; reset=0;
        repeat(5) @(negedge wc);
        streaming=1;
        wait(full); // Reader stalled: exactly 16 words fit.
        @(negedge wc);
        if(sent!=16) $fatal(1,"FIFO depth mismatch %0d",sent);
        // Read-side level follows after the two-stage pointer synchronizer.
        repeat(3) @(posedge rc); #1;
        if(level!=16) $fatal(1,"read level %0d",level);
        phase=1;
        wait(received==512);
        streaming=0;
        repeat(8) @(negedge rc);
        if(!empty || overflow || underflow || level!=0) $fatal(1,"Unexpected FIFO flags");
        // Reset a nonempty queue; stale words must not escape after restart.
        reset=1; #40; sent=0;received=0;phase=0; reset=0;
        repeat(5) @(negedge wc);
        streaming=1;
        wait(sent==8);
        streaming=0;
        @(negedge wc);
        reset=1; #40; sent=0;received=0; reset=0;
        repeat(5) @(negedge wc);
        phase=1; streaming=1;
        wait(received==512);
        streaming=0;
        repeat(8) @(negedge rc);
        if(!empty || overflow || underflow) $fatal(1,"Restart flags");
        // Deliberate empty pop must be visible and must not emit valid data.
        @(posedge rc); #2; manual_read=1;
        @(negedge rc);
        @(posedge rc); #2;
        if(!underflow || valid) $fatal(1,"Empty pop handling");
        $display("PASS: async FIFO depth16, 1024 ordered words, wrap and nonempty reset, empty pop");
        $finish;
    end
    initial begin #1000000; $fatal(1,"FIFO timeout"); end
endmodule
