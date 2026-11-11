`timescale 1ns/1ps
// kagura_boot_reset_ctl with the W65C02S adapter: every CPU reset re-runs the boot.
//   RESB at the CPU = release AND external (supervisor / GreenPAK), 5 ns after the FPGA pin. A small model stands in for the
//   boot controller: boot_ready drops while boot_reset is asserted and returns 200 clocks after it ends.
// Checks: (1) a reset request in any of the 16 phases drops the release only while PHI2 is low, sets BOOT_MAP at a phase-2
// edge and holds the boot controller in reset until the request ends; (2) an external RESB pulse (also 1 ns) while released
// restarts the boot, BOOT_MAP back to 1 at the next phase 2; (3) KAGURA's own hold and the release edge are not taken as
// external resets; (4) request storms and request / RESB races end in one consistent restart; (5) ready loss restarts the boot;
// (6) vector_ok = {fewer than VECTOR_CYCLES valid cycles since release, >= 3 non-selected valid cycles just before}.
module tb_boot_reset_ctl;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1, base_ready=0, req_n=1, ext_n=1, cs_n=1;
    wire phi2, release_n, oe, irq_drive, late, req_valid, req_write; wire [4:0] req_addr; wire [7:0] dout, req_wdata;
    wire boot_map, boot_reset, run_ok; wire [1:0] vector_ok;
    reg boot_ready=0; integer brc=0;
    always @(posedge clk) if(boot_reset) begin boot_ready<=0; brc<=0; end else if(brc<200) brc<=brc+1; else boot_ready<=1;
    kagura_w65c02_adapter adapter(clk,reset,base_ready && boot_ready && run_ok,phi2,release_n,5'h00,cs_n,1'b1,8'h00,
        dout,oe,irq_drive,1'b0,req_valid,1'b1,req_write,req_addr,req_wdata,rsp_valid,,8'h00,1'b0,late);
    reg rsp_valid=0; always @(posedge clk) rsp_valid <= req_valid;
    reg rel_d=0; always @(release_n) rel_d <= #5 release_n;   // FPGA pin -> U10, 5 ns
    wire resb = rel_d & ext_n;                                // the external pulse reaches RESB undelayed (any width)
    integer resb_falls=0; always @(negedge resb) resb_falls++;
    reg unmap=0;
    kagura_boot_reset_ctl #(.VECTOR_CYCLES(64)) ctl(clk,reset,phi2,release_n,cs_n,req_n,resb,unmap,boot_map,boot_reset,run_ok,vector_ok);
    integer failures=0, restarts=0, rel_falls_high=0; reg req_test=0;
    always @(posedge boot_reset) if(!reset) restarts++;
    always @(negedge release_n) if(!reset && req_test && phi2!==1'b0) rel_falls_high++;   // request path: never while PHI2 is high
    always @(posedge boot_map) if(!reset) begin #0.1; if(adapter.phase!==4'd2) begin $display("FAIL: BOOT_MAP rose in phase %0d",adapter.phase); failures++; end end
    task automatic wait_running(); begin wait(release_n===1'b1); repeat(4) @(negedge phi2); end endtask
    task automatic leave_boot_map(); begin unmap=1; repeat(2) @(negedge phi2); unmap=0; @(negedge phi2);
        if(boot_map!==1'b0) begin $display("FAIL: BOOT_MAP did not leave"); failures++; end end endtask
    task automatic fail(input string s); begin $display("FAIL: %s",s); failures++; end endtask
    integer ph, r0, t, k;
    initial begin
        #200; reset=0; base_ready=1;
        wait_running();
        // (1) a request in each of the 16 phases
        req_test=1;
        for(ph=0;ph<16;ph++) begin
            leave_boot_map();
            @(negedge phi2); repeat(ph) @(posedge clk); #3;
            r0=restarts; req_n=0;
            t=0; while(release_n===1'b1 && t<40) begin @(posedge clk); t++; end
            if(release_n!==1'b0) fail($sformatf("request in phase %0d: release not dropped within 40 clocks",ph));
            if(t>22) fail($sformatf("request in phase %0d: release dropped after %0d clocks (> 2 sync + 16 + 4)",ph,t));
            if(boot_map!==1'b1 || boot_reset!==1'b1) fail($sformatf("request in phase %0d: BOOT_MAP %0b, boot controller reset %0b",ph,boot_map,boot_reset));
            #3000; if(boot_reset!==1'b1 || release_n!==1'b0) fail("held request: boot controller not held / CPU released");
            req_n=1; wait_running();
            if(restarts==r0) fail("request: no restart");
        end
        req_test=0;
        // (2) external RESB pulses while released, 1 ns and 100 ns, in random phases
        for(k=0;k<8;k++) begin
            leave_boot_map();
            @(negedge phi2); repeat(k*2) @(posedge clk); #2.3;
            r0=restarts; ext_n=0; #(k%2 ? 1 : 100); ext_n=1;
            repeat(8) @(posedge clk);
            if(restarts==r0 || release_n!==1'b0) fail($sformatf("external RESB pulse %0d: restart %0d, release %0b, RESB falls %0d",k,restarts-r0,release_n,resb_falls));
            repeat(2) @(negedge phi2); if(boot_map!==1'b1) fail("external RESB pulse: BOOT_MAP not back to 1");
            wait_running();
        end
        // (3) no false external event from KAGURA's own hold / release
        r0=restarts; repeat(200) @(negedge phi2);
        if(restarts!=r0) fail($sformatf("%0d spurious restart(s) while running",restarts-r0));
        // (4) request storm: 6 short requests, 700 ns apart, then one more during the restarted boot
        for(k=0;k<6;k++) begin req_n=0; #300; req_n=1; #400; end
        #2000; req_n=0; #500; req_n=1;
        wait_running(); r0=restarts; repeat(50) @(negedge phi2);
        if(restarts!=r0 || release_n!==1'b1 || boot_map!==1'b1) fail("request storm: not settled");
        // race: request and external RESB at the same time
        @(negedge phi2); #50; req_n=0; ext_n=0; #200; ext_n=1; #500; req_n=1;
        wait_running(); r0=restarts; repeat(50) @(negedge phi2);
        if(restarts!=r0) fail("request / RESB race: did not settle");
        // (5) ready loss restarts the boot
        r0=restarts; @(posedge phi2); #30; base_ready=0; @(posedge clk); @(posedge clk); base_ready=1;
        repeat(4) @(posedge clk);
        if(restarts==r0) fail("ready loss: no restart");
        wait_running();
        // (6) vector_ok: after a fresh release, 2 selected (dummy reads in the window), 3 not selected (stack), then the vector
        req_n=0; #2000; req_n=1; wait(release_n===1'b1); @(negedge phi2);
        cs_n=0; repeat(2) @(negedge phi2); cs_n=1; repeat(3) @(negedge phi2); cs_n=0; #120;
        if(vector_ok!==2'b11) fail($sformatf("reset vector cycle: vector_ok %b (want 11)",vector_ok));
        @(negedge phi2); #120; if(vector_ok[0]!==1'b0) fail("second selected cycle: stack bit should be 0");
        cs_n=0; repeat(70) @(negedge phi2); #120; if(vector_ok[1]!==1'b0) fail("after 64 valid cycles: early bit should be 0");
        cs_n=1;
        if(rel_falls_high) fail($sformatf("release fell while PHI2 was high %0d time(s)",rel_falls_high));
        if(late) fail("late");
        if(failures) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: reset request in all 16 phases drops RESB only while PHI2 is low and sets BOOT_MAP at phase 2; external RESB pulses down to 1 ns restart the boot; no spurious restart; storm and race settle; ready loss restarts; vector_ok signature");
        $finish;
    end
    initial begin #3000000; $fatal(1,"timeout"); end
endmodule
