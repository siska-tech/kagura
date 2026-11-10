`timescale 1ns/1ps
// Data bus handover after a KAGURA read (docs/timing.md, phase table).
// The adapter keeps its read data and OE for two system cycles after the PHI2
// fall (released on the edge that starts phase 2) so that the CPU read hold
// survives the PHI2 output delay and an external PHI2 buffer.  This test pins
// that behaviour down at RTL level and checks that the longer hold never
// overlaps the next bus driver:
//   - OE falls exactly on the edge that starts phase 2 (2 system cycles after
//     the internal PHI2 fall) and is never high with PHI2 low in phase >= 2;
//   - read data does not change between the PHI2 fall and the OE release;
//   - back-to-back KAGURA read -> other device read, CPU write, KAGURA write,
//     KAGURA read: at most one driver at any time, and the gap between the
//     FPGA releasing the bus and the next driver is reported and checked;
//   - losing `ready` with OE high asserts CPU reset at once, still releases OE
//     at phase 2, and no read is driven until the CPU is released again;
//   - system reset with OE high releases OE on the next clock.
// The other devices and the CPU write driver start driving at the PHI2 rise
// at their pins (no tMDS / enable delay credited), the other device holds its
// data EXT_HOLD_NS after the PHI2 fall.  Board delays are lumped, as in
// tb_w65c02_bus.  This is a logic/ordering check; the nanosecond margins on
// silicon come from STA and board measurement, not from this test.
module tb_w65c02_bus_handover;
    localparam real TSYS=18.518, BOARD_NS=3.0, DECODE_NS=10.0, EXT_HOLD_NS=20.0;
    // Release at phase 2, next driver no earlier than the PHI2 rise (phase 8):
    // 6 system cycles at the pins with equal board delays.
    localparam real MIN_GAP_NS=6*TSYS-0.01;
    reg clk=0;
    always #9.259 clk=~clk;
    reg reset=1, ready=0;
    wire phi2, release_n, oe, irq_drive, late;
    wire [7:0] dout;
    reg [4:0] cpu_a=0; reg cpu_cs_n=1, cpu_rwb=1;
    reg cpu_drive=0; reg [7:0] cpu_dout=0;
    reg ext_drive=0; reg [7:0] ext_dout=0;
    wire #(BOARD_NS) phi2_pin=phi2;
    wire #(BOARD_NS) fpga_oe_pin=oe;
    wire [7:0] #(BOARD_NS) fpga_d_pin=dout;
    wire [4:0] #(BOARD_NS) a_in=cpu_a;
    wire #(BOARD_NS) cs_in=cpu_cs_n, rwb_in=cpu_rwb;
    wire [7:0] bus=cpu_drive ? cpu_dout : ext_drive ? ext_dout : fpga_oe_pin ? fpga_d_pin : 8'hzz;
    wire [7:0] #(BOARD_NS) d_in=bus;
    always @* if(32'(cpu_drive)+32'(ext_drive)+32'(fpga_oe_pin===1'b1)>1)
        $fatal(1,"data bus contention at %0t (cpu %0b ext %0b fpga %0b)",$realtime,cpu_drive,ext_drive,fpga_oe_pin);

    wire req_valid,req_ready,req_write,rsp_valid,rsp_ready,rsp_error,irq;
    wire [4:0] req_addr; wire [7:0] req_wdata,rsp_rdata;
    kagura_w65c02_adapter adapter(clk,reset,ready,phi2,release_n,a_in,cs_in,rwb_in,d_in,
        dout,oe,irq_drive,irq,req_valid,req_ready,req_write,req_addr,req_wdata,
        rsp_valid,rsp_ready,rsp_rdata,rsp_error,late);
    kagura_core #(.CAPS(8'h01)) core(.clk(clk),.reset(reset),.audio_full(1'b0),.audio_underflow_toggle(1'b0),.audio_muted(1'b0),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),
        .rsp_ready(rsp_ready),.rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.irq(irq),
        .render_start(1'b0),.render_line(8'd0),.line_write(),.line_addr(),.line_data(),.render_done(),
        .vblank_start(1'b0),.vblank_live(1'b0),.underrun_event(1'b0),.line_start(1'b0),.shown_line(8'd0),
        .render_cycles());

    // --- RTL-level release point ------------------------------------------
    realtime phi2_fall=0, dout_change=0;
    integer releases=0;
    always @(negedge phi2) phi2_fall=$realtime;
    always @(dout) dout_change=$realtime;
    always @(negedge oe) if(!reset) begin
        #0.1;
        if(adapter.phase!==4'd2) $fatal(1,"OE released in phase %0d, expected 2",adapter.phase);
        if($realtime-0.1-phi2_fall<2*TSYS-0.01 || $realtime-0.1-phi2_fall>2*TSYS+0.01)
            $fatal(1,"OE released %0.3fns after the PHI2 fall, expected %0.3f",$realtime-0.1-phi2_fall,2*TSYS);
        if(dout_change>phi2_fall) $fatal(1,"read data changed between the PHI2 fall and the OE release");
        releases=releases+1;
    end
    // OE may only be high with PHI2 low in phases 0 and 1 (the hold extension).
    always @(posedge clk) begin
        #0.1;
        if(oe && !phi2 && adapter.phase!==4'd0 && adapter.phase!==4'd1)
            $fatal(1,"OE high with PHI2 low in phase %0d",adapter.phase);
    end

    // --- pin-level handover gaps ------------------------------------------
    realtime fpga_off=0, cpu_fall=0, min_gap=1.0e9, min_hold=1.0e9;
    reg fpga_released=0;
    always @(negedge fpga_oe_pin) begin fpga_off=$realtime; fpga_released=1; end
    always @(negedge phi2_pin) cpu_fall=$realtime;
    always @(posedge cpu_drive or posedge ext_drive or posedge fpga_oe_pin) if(fpga_released) begin
        if($realtime-fpga_off<min_gap) min_gap=$realtime-fpga_off;
        fpga_released=0;
    end

    realtime last_bus_change=0;
    always @(bus) last_bus_change=$realtime;

    // kind: 0 other device read, 1 other device / CPU write (unselected),
    //       2 KAGURA read, 3 KAGURA write
    reg expect_no_drive=1;
    always @(posedge fpga_oe_pin) if(expect_no_drive) $fatal(1,"FPGA drove data outside a selected read");
    integer selected=0;
    task automatic cpu_cycle(input integer kind,input reg [4:0] a,input reg [7:0] wd,output reg [7:0] rd);
        realtime fall, hold;
        reg sel, rw;
        begin
            sel=(kind>=2); rw=(kind==0 || kind==2);
            #10; cpu_a=5'bx; cpu_rwb=1'bx; cpu_cs_n=1'bx;
            #30; cpu_a=a; cpu_rwb=rw;
            #(DECODE_NS); cpu_cs_n=!sel;
            if(sel && release_n) selected=selected+1;
            expect_no_drive=!(sel && rw && release_n);
            @(posedge phi2_pin);
            if(!rw) begin cpu_drive=1; cpu_dout=8'hxx; #40; cpu_dout=wd; end
            if(kind==0) begin ext_drive=1; ext_dout=8'hxx; #40; ext_dout=wd; end
            @(negedge phi2_pin); fall=$realtime;
            rd=bus;
            if(kind==2 && !expect_no_drive) begin
                if(fall-last_bus_change<15.0) $fatal(1,"read setup %0.2fns",fall-last_bus_change);
                @(bus or negedge fpga_oe_pin);
                hold=$realtime-fall;
                if(hold<10.0) $fatal(1,"read hold %0.2fns",hold);
                if(hold<min_hold) min_hold=hold;
            end else if(kind==0) #(EXT_HOLD_NS);
            else #10;
            cpu_drive=0; ext_drive=0;
            expect_no_drive=1;
        end
    endtask
    task automatic kread(input reg [4:0] a,input reg [7:0] expect_v);
        reg [7:0] v;
        begin
            cpu_cycle(2,a,0,v);
            if(v!==expect_v) $fatal(1,"read $9F%02h: %02h expected %02h",a,v,expect_v);
        end
    endtask
    task automatic cycle(input integer kind,input reg [4:0] a,input reg [7:0] wd);
        reg [7:0] dummy;
        begin cpu_cycle(kind,a,wd,dummy); end
    endtask

    integer i, k, rel_before;
    reg [7:0] model_enable;
    initial begin
        #200; reset=0;
        #500; wait(core.init_done); ready=1;
        @(posedge release_n);
        @(negedge phi2_pin);
        // Every ordered pair (KAGURA read, next kind), with a known value on the bus.
        cycle(3,5'h02,8'h15);
        for(k=0;k<4;k=k+1) begin
            kread(5'h02,8'h15);
            cycle(k,k==3 ? 5'h02 : 5'h18,8'h15);
            kread(5'h19,8'h39);
        end
        // Random back-to-back mix weighted towards reads.
        model_enable=8'h15;
        for(i=0;i<400;i=i+1) begin
            k=$urandom_range(0,5);
            case(k)
                0: cycle(0,5'h18,8'($urandom));
                1: cycle(1,5'h18,8'($urandom));
                2: begin model_enable=8'($urandom)&8'h7f; cycle(3,5'h02,model_enable); end
                default: kread(5'h02,model_enable);
            endcase
        end
        if(late) $fatal(1,"adapter response deadline missed");
        // Ready loss in the PHI2-high half of a KAGURA read, OE already driving.
        fork
            kread(5'h19,8'h39);
            begin @(posedge oe); #(3*TSYS); ready=0; @(posedge clk); #1;
                if(release_n) $fatal(1,"reset not asserted on ready loss"); end
        join
        if(oe) $fatal(1,"OE still high after ready loss");
        rel_before=releases;
        // The CPU is in reset now; decode may still select KAGURA, which must not drive.
        for(i=0;i<6;i=i+1) cycle(i%2 ? 2 : 0,5'h19,8'h00);
        if(oe || releases!==rel_before) $fatal(1,"OE driven while the CPU was held in reset");
        cpu_cs_n=1;   // bus idle (deselected) while waiting for the release
        ready=1; @(posedge release_n); @(negedge phi2_pin);
        kread(5'h19,8'h39); cycle(0,5'h18,8'h5a); kread(5'h18,8'h4b);
        // System reset with OE high: a selected read held on the pins, no CPU
        // cycle task (reset also restarts PHI2, so setup/hold do not apply).
        #10; cpu_a=5'h18; cpu_rwb=1; cpu_cs_n=0; expect_no_drive=0;
        @(posedge oe); #(2*TSYS); reset=1; @(posedge clk); #1;
        if(oe) $fatal(1,"OE not released by system reset");
        if(min_gap<MIN_GAP_NS) $fatal(1,"FPGA release -> next driver gap %0.2fns < %0.1f",min_gap,MIN_GAP_NS);
        $display("PASS: bus handover, %0d selected cycles, %0d OE releases all at phase 2 (%0.2fns after PHI2 fall), min read hold at CPU %0.2fns, min FPGA release -> next driver %0.2fns, ready loss/system reset release OE",
            selected,releases,2*TSYS,min_hold,min_gap);
        $finish;
    end
    initial begin #3000000; $fatal(1,"handover test timeout"); end
endmodule
