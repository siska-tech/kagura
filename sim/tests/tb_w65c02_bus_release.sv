`timescale 1ns/1ps
// RESB release cycle: the adapter releases RESB in phase 2 of a PHI2 cycle that began while the CPU was held in reset.
// Whatever the CPU drives during reset (the W65C02S data sheet does not specify it), that cycle must not be served.
// Here the CPU side presents a selected read of $FFFF (offset $1F) during and after reset, the worst case for the boot window.
// Checks: no request between the release and the next PHI2 fall; the first request is issued at phase 6 of the first cycle that
// begins after the release; then exactly one request per cycle; the same after a ready loss and a second release.
module tb_w65c02_bus_release;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1, ready=0;
    wire phi2, release_n, oe, irq_drive, late;
    wire [7:0] dout;
    reg [4:0] cpu_a=5'h1f; reg cpu_cs_n=0, cpu_rwb=1;
    wire req_valid, req_write; wire [4:0] req_addr; wire [7:0] req_wdata;
    reg rsp_valid=0; reg [7:0] rsp_rdata=0;
    kagura_w65c02_adapter adapter(clk,reset,ready,phi2,release_n,cpu_a,cpu_cs_n,cpu_rwb,8'h00,
        dout,oe,irq_drive,1'b0,req_valid,1'b1,req_write,req_addr,req_wdata,rsp_valid,,rsp_rdata,1'b0,late);
    always @(posedge clk) begin rsp_valid <= req_valid; rsp_rdata <= {3'b0, req_addr}; end
    integer failures=0, reqs=0, falls_since_release=0, req_phase=-1;
    realtime t_release=0, t_first=-1;
    always @(posedge clk) if(req_valid) begin reqs=reqs+1; if(t_first<0) begin t_first=$realtime; req_phase=adapter.phase; end end
    always @(negedge phi2) if(release_n) falls_since_release=falls_since_release+1;
    task automatic check_release(input string tag);
        integer r0, f0;
        begin
            reqs=0; t_first=-1; falls_since_release=0;
            @(posedge release_n); t_release=$realtime;
            if(phi2!==0 || adapter.phase!==4'd2) begin $display("FAIL: %s: release not in phase 2 with PHI2 low (phase %0d)",tag,adapter.phase); failures++; end
            @(negedge phi2);
            if(reqs!=0) begin $display("FAIL: %s: %0d request(s) in the release cycle (CPU still in reset when the cycle began)",tag,reqs); failures++; end
            @(negedge phi2);
            if(reqs!=1 || req_phase!=6) begin $display("FAIL: %s: first full cycle: %0d request(s), issued in phase %0d (want 1 in phase 6)",tag,reqs,req_phase); failures++; end
            r0=reqs; repeat(10) @(negedge phi2);
            if(reqs-r0!=10) begin $display("FAIL: %s: %0d requests in 10 cycles (want 10)",tag,reqs-r0); failures++; end
            if(oe===1'bx) begin $display("FAIL: %s: OE unknown",tag); failures++; end
        end
    endtask
    initial begin
        #200; reset=0; #300; ready=1;
        check_release("first release");
        // ready loss in the middle of a cycle: reset at once, no request while released is low
        @(posedge phi2); #20; ready=0; @(posedge clk); #1;
        if(release_n) begin $display("FAIL: release not dropped on ready loss"); failures++; end
        @(negedge phi2);
        begin integer r1; r1=reqs; repeat(4) @(negedge phi2);
            if(reqs!=r1) begin $display("FAIL: %0d request(s) while the CPU is held in reset",reqs-r1); failures++; end end
        ready=1;
        check_release("second release (after ready loss)");
        if(late) begin $display("FAIL: late"); failures++; end
        if(failures) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: RESB release cycle not served (selected $FFFF read held during reset); first request in phase 6 of the next cycle, then one per cycle; same after a ready loss");
        $finish;
    end
    initial begin #400000; $fatal(1,"timeout"); end
endmodule
