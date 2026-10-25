`timescale 1ns/1ps
// W65C02S bus model against kagura_w65c02_adapter + kagura_registers.
// CPU timing (W65C02S 3.3V, docs/timing.md): address/RWB hold 10ns and valid
// 40ns after PHI2 falls, write data valid 40ns after PHI2 rises and held 10ns
// after it falls, read data needs 15ns setup / 10ns hold around the fall.
// Board wiring adds BOARD_NS each way and the external decode adds DECODE_NS
// to CS. Any overlap of CPU and FPGA data drivers is a failure.
module tb_w65c02_bus;
    localparam real BOARD_NS=3.0, DECODE_NS=10.0;
    reg clk=0;
    always #9.259 clk=~clk;
    reg reset=1, ready=0;
    wire phi2, release_n, oe, irq_drive, late;
    wire [7:0] dout;
    reg [4:0] cpu_a=0; reg cpu_cs_n=1, cpu_rwb=1;
    reg cpu_drive=0; reg [7:0] cpu_dout=0;
    // Board delays.
    wire #(BOARD_NS) phi2_pin=phi2;
    wire #(BOARD_NS) fpga_oe_pin=oe;
    wire [7:0] #(BOARD_NS) fpga_d_pin=dout;
    wire [4:0] #(BOARD_NS) a_in=cpu_a;
    wire #(BOARD_NS) cs_in=cpu_cs_n, rwb_in=cpu_rwb;
    wire [7:0] bus=cpu_drive ? cpu_dout : fpga_oe_pin ? fpga_d_pin : 8'hzz;
    wire [7:0] #(BOARD_NS) d_in=bus;
    always @* if(cpu_drive && fpga_oe_pin) $fatal(1,"data bus contention at %0t",$realtime);

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

    // Count accepted requests; each selected CPU cycle must make exactly one.
    integer requests=0, selected=0;
    always @(posedge clk) if(!reset && req_valid && req_ready) requests=requests+1;
    // /IRQ may only change at the start of phase 3.
    reg irq_prev=0;
    always @(posedge clk) begin
        #0.1;
        if(irq_drive!==irq_prev && adapter.phase!==4'd3) $fatal(1,"IRQ changed outside phase 3");
        irq_prev=irq_drive;
    end
    // OE must stay low for unselected and write cycles.
    reg expect_no_drive=1;
    always @(posedge fpga_oe_pin) if(expect_no_drive) $fatal(1,"FPGA drove data in an unselected/write cycle");

    // Track bus stability for the read setup/hold check.
    realtime last_bus_change=0;
    always @(bus) last_bus_change=$realtime;

    // One CPU cycle, starting just after a PHI2 fall seen at the CPU pin.
    task automatic cpu_cycle(input reg sel,input reg rw,input reg [4:0] a,input reg [7:0] wd,output reg [7:0] rd);
        realtime fall;
        begin
            #10; cpu_a=5'bx; cpu_rwb=1'bx; cpu_cs_n=1'bx;
            #30; cpu_a=a; cpu_rwb=rw;
            #(DECODE_NS); cpu_cs_n=!sel;
            if(sel) selected=selected+1;
            expect_no_drive=!(sel && rw);
            @(posedge phi2_pin);
            if(!rw) begin #5; cpu_drive=1; cpu_dout=8'hxx; #35; cpu_dout=wd; end
            @(negedge phi2_pin); fall=$realtime;
            rd=bus;
            if(sel && rw) begin
                if(fall-last_bus_change<15.0) $fatal(1,"read setup %0.2fns",fall-last_bus_change);
                #10;
                if(bus!==rd || $realtime-last_bus_change<10.0) $fatal(1,"read hold");
            end else #10;
            cpu_drive=0;
            expect_no_drive=1;
        end
    endtask
    task automatic cpu_read(input reg [4:0] a,input reg [7:0] expect_v);
        reg [7:0] v;
        begin
            cpu_cycle(1,1,a,0,v);
            if(v!==expect_v) $fatal(1,"read $9F%02h: %02h expected %02h",a,v,expect_v);
        end
    endtask
    task automatic cpu_write(input reg [4:0] a,input reg [7:0] v);
        reg [7:0] dummy;
        begin cpu_cycle(1,0,a,v,dummy); end
    endtask
    task automatic idle(input reg rw);
        reg [7:0] dummy;
        begin cpu_cycle(0,rw,5'h18,8'h5a,dummy); end
    endtask

    integer i, op, phi2_after_ready=0;
    reg counting=0;
    always @(posedge phi2) if(counting) phi2_after_ready=phi2_after_ready+1;
    reg [7:0] model_enable=0, v;
    initial begin
        #200; reset=0;
        #500; wait(core.init_done); ready=1; counting=1;
        @(posedge release_n); counting=0;
        if(phi2!==0) $fatal(1,"reset released with PHI2 high");
        if(phi2_after_ready<8) $fatal(1,"only %0d PHI2 cycles before reset release",phi2_after_ready);
        @(negedge phi2_pin);
        // ID/ABI/CAPS and STATUS.
        cpu_read(5'h18,8'h4b); cpu_read(5'h19,8'h39); cpu_read(5'h1a,8'h00);
        cpu_read(5'h1b,8'h04); cpu_read(5'h1c,8'h01); cpu_read(5'h00,8'h01);
        // Read/write register and unselected cycles in between.
        cpu_write(5'h02,8'h15); idle(1); idle(0); cpu_read(5'h02,8'h15);
        // Writing a read-only register is BAD_ACCESS with IRQ.ERROR.
        cpu_write(5'h18,8'hff);
        cpu_read(5'h17,8'h04); cpu_read(5'h01,8'h40); cpu_read(5'h00,8'h41);
        if(irq_drive) $fatal(1,"IRQ while disabled");
        cpu_write(5'h02,8'h40); idle(1);
        if(!irq_drive) $fatal(1,"IRQ not driven");
        // W1C: clearing the cause does not clear the IRQ bit, and vice versa.
        cpu_write(5'h17,8'h04); cpu_read(5'h17,8'h00); cpu_read(5'h01,8'h40);
        cpu_write(5'h01,8'h40); idle(1); cpu_read(5'h01,8'h00);
        if(irq_drive) $fatal(1,"IRQ not released");
        cpu_read(5'h00,8'h01);
        // Random mix against a model of IRQ_ENABLE and the ID block.
        model_enable=8'h40;
        for(i=0;i<300;i=i+1) begin
            op=$urandom_range(0,4);
            v=8'($urandom)&8'h7f;
            case(op)
                0: begin cpu_write(5'h02,v); model_enable=v; end
                1: cpu_read(5'h02,model_enable);
                2: cpu_read(5'h19,8'h39);
                3: idle(1'b1);
                default: idle(1'b0);
            endcase
        end
        if(late) $fatal(1,"adapter response deadline missed");
        if(requests!=selected) $fatal(1,"%0d requests for %0d selected cycles",requests,selected);
        // Losing ready asserts CPU reset at once.
        ready=0; @(posedge clk); #1;
        if(release_n) $fatal(1,"reset not asserted on ready loss");
        $display("PASS: W65C02S bus model, %0d selected cycles (one request each), read setup/hold, no contention, IRQ phase, W1C, reset release after %0d PHI2 cycles",selected,phi2_after_ready);
        $finish;
    end
    initial begin #2000000; $fatal(1,"bus test timeout"); end
endmodule
