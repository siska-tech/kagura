`timescale 1ns/1ps
// SPI / QSPI host model against kagura_spi_adapter + kagura_core
// (docs/host-interface.md). Mode 0 at f_SCK=10MHz with the minimum t_CSS,
// t_CSH and t_CSW. Board wiring adds BOARD_NS each way, SCK SKEW_NS more.
// The host samples on SCK rising edges and requires SETUP_NS/HOLD_NS around
// them; any overlap of host and FPGA drivers on an IO line is a failure.
module tb_host_bus #(parameter integer LANES=1);
    localparam real SCK_NS=100.0, CSS_NS=200.0, CSH_NS=20.0, CSW_NS=200.0;
    localparam real BOARD_NS=3.0, SKEW_NS=2.0, SETUP_NS=5.0, HOLD_NS=5.0;
    localparam integer CHUNKS=8/LANES;
    localparam [3:0] RX=LANES==1 ? 4'b0010 : 4'b1111;
    reg clk=0;
    always #9.259 clk=~clk;
    reg reset=1;

    // Host side pins and board delays.
    reg sck=0, cs_n=1;
    reg [3:0] host_out=0, host_oe=0;
    wire [3:0] fpga_out, fpga_oe;
    wire busy, irq_drive, late;
    wire #(BOARD_NS+SKEW_NS) sck_in=sck;
    wire #(BOARD_NS) cs_in=cs_n;
    wire [3:0] #(BOARD_NS) fpga_out_pin=fpga_out;
    wire [3:0] #(BOARD_NS) fpga_oe_pin=fpga_oe;
    wire [3:0] #(BOARD_NS) host_out_pin=host_out;
    wire [3:0] #(BOARD_NS) host_oe_pin=host_oe;
    wire #(BOARD_NS) busy_pin=busy;
    wire #(BOARD_NS) irq_pin=irq_drive;
    wire [3:0] host_bus, fpga_bus;
    genvar g;
    generate for(g=0;g<4;g=g+1) begin: line
        assign host_bus[g]=host_oe[g] ? host_out[g] : fpga_oe_pin[g] ? fpga_out_pin[g] : 1'b0;
        assign fpga_bus[g]=host_oe_pin[g] ? host_out_pin[g] : fpga_oe[g] ? fpga_out[g] : 1'b0;
    end endgenerate
    always @* if((host_oe & fpga_oe_pin)!=0 || (host_oe_pin & fpga_oe)!=0)
        $fatal(1,"IO contention at %0t",$realtime);

    wire req_valid,req_ready,req_write,rsp_valid,rsp_ready,rsp_error,irq;
    wire [4:0] req_addr; wire [7:0] req_wdata,rsp_rdata;
    wire [5:0] queue_free;
    kagura_spi_adapter #(.LANES(LANES)) adapter(.clk(clk),.reset(reset),
        .spi_sck(sck_in),.spi_cs_n(cs_in),.spi_io_in(fpga_bus),.spi_io_out(fpga_out),.spi_io_oe(fpga_oe),
        .busy(busy),.irq_drive(irq_drive),.irq_level(irq),.queue_free(queue_free),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.late(late));
    kagura_core #(.CAPS(8'h01)) core(.clk(clk),.reset(reset),.audio_full(1'b0),.audio_underflow_toggle(1'b0),.audio_muted(1'b0),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),
        .rsp_ready(rsp_ready),.rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.irq(irq),
        .render_start(1'b0),.render_line(8'd0),.line_write(),.line_addr(),.line_data(),.render_done(),
        .vblank_start(1'b0),.vblank_live(1'b0),.underrun_event(1'b0),.line_start(1'b0),.shown_line(8'd0),
        .render_cycles(),.queue_free(queue_free));

    // Every expected request must be accepted exactly once.
    integer requests=0, expected=0, busy_seen=0;
    always @(posedge clk) if(!reset && req_valid && req_ready) requests=requests+1;
    // Host setup/hold on the lines it reads.
    realtime last_rx_change=0;
    always @(host_bus & RX) last_rx_change=$realtime;

    // One SCK period: data set after the falling edge, sampled on the rise.
    task automatic chunk(input [3:0] tx, output [3:0] rx, input check, input wait_busy);
        realtime rise_time;
        begin
            host_out=tx;
            #(SCK_NS/2-1.0);
            // Queue-consuming byte: BUSY must be low just before its first rise.
            if(wait_busy) while(busy_pin) begin busy_seen=busy_seen+1; @(negedge busy_pin); #(SCK_NS/2); end
            #1.0;
            sck=1; rise_time=$realtime;
            rx=host_bus;
            if(check && rise_time-last_rx_change<SETUP_NS) $fatal(1,"host setup %0.2fns",rise_time-last_rx_change);
            #(HOLD_NS);
            if(check && last_rx_change>rise_time) $fatal(1,"host hold");
            #(SCK_NS/2-HOLD_NS);
            sck=0;
        end
    endtask
    task automatic xfer_byte(input [7:0] tx, output [7:0] rx, input check, input wait_busy);
        reg [3:0] r;
        integer k;
        begin
            for(k=0;k<CHUNKS;k=k+1) begin
                chunk(LANES==1 ? {3'b000,tx[7-k]} : tx[7-4*k -: 4],r,check,wait_busy && k==0);
                if(LANES==1) rx[7-k]=r[1]; else rx[7-4*k -: 4]=r;
            end
        end
    endtask
    task automatic begin_txn;
        begin
            cs_n=0; host_oe=LANES==1 ? 4'b0001 : 4'b1111;
            #(CSS_NS-SCK_NS/2);
        end
    endtask
    task automatic end_txn;
        begin #(CSH_NS); cs_n=1; host_oe=0; #(CSW_NS); end
    endtask

    reg [7:0] wbuf [0:255], rbuf [0:255];
    reg [7:0] status;
    task automatic txn_write(input [4:0] off, input inc, input integer n, input wait_busy);
        reg [7:0] d;
        integer i;
        begin
            begin_txn;
            xfer_byte({1'b0,inc,1'b0,off},status,LANES==1,0);
            for(i=0;i<n;i=i+1) xfer_byte(wbuf[i],d,0,wait_busy);
            end_txn;
            expected=expected+n+(LANES==1);
        end
    endtask
    task automatic txn_read(input [4:0] off, input inc, input integer n, input integer extra);
        reg [7:0] d;
        integer i;
        begin
            begin_txn;
            xfer_byte({1'b1,inc,1'b0,off},status,LANES==1,0);
            xfer_byte(8'(n),d,0,0);
            if(LANES!=1) host_oe=0;            // turnaround after the count byte
            xfer_byte(8'h00,d,0,0);            // dummy
            for(i=0;i<n+extra;i=i+1) xfer_byte(8'h00,rbuf[i],1,0);
            end_txn;
            expected=expected+n+(LANES==1);
        end
    endtask
    task automatic write1(input [4:0] off, input [7:0] v);
        begin wbuf[0]=v; txn_write(off,0,1,0); end
    endtask
    // Queue-consuming register writes wait for BUSY like the streams.
    task automatic command(input [7:0] op);
        begin wbuf[0]=op; txn_write(5'h0e,0,1,1); end
    endtask
    task automatic read_expect(input [4:0] off, input [7:0] v);
        begin
            txn_read(off,0,1,0);
            if(rbuf[0]!==v) $fatal(1,"read %02h: %02h expected %02h",off,rbuf[0],v);
        end
    endtask
    task automatic set_addr(input [23:0] a);
        begin wbuf[0]=a[7:0]; wbuf[1]=a[15:8]; wbuf[2]=a[23:16]; txn_write(5'h04,1,3,0); end
    endtask
    task automatic vram_read(input [23:0] a, output [7:0] v);
        begin
            set_addr(a); wbuf[0]=8'h00; txn_write(5'h08,0,1,1);
            rbuf[0]=0;
            while(!rbuf[0][2]) txn_read(5'h00,0,1,0);
            txn_read(5'h09,0,1,0); v=rbuf[0];
        end
    endtask

    integer i, j, n, op, vram_checked=0;
    reg [7:0] model_enable=0, model_fill=0, model_fence=0, v;
    reg [7:0] pattern [0:95];
    initial begin
        #200; reset=0;
        wait(core.init_done);
        #500;
        // ID/ABI/CAPS as one incrementing read; SPI header status = 32 free.
        txn_read(5'h18,1,5,0);
        if({rbuf[0],rbuf[1],rbuf[2],rbuf[3],rbuf[4]}!==40'h4b39000301) $fatal(1,"ID block");
        if(LANES==1 && status!==8'h20) $fatal(1,"header FIFO_STATUS %02h",status);
        // Bytes after the count return 0 without consuming requests.
        txn_read(5'h18,0,2,3);
        if({rbuf[0],rbuf[1],rbuf[2],rbuf[3],rbuf[4]}!==40'h4b4b000000) $fatal(1,"read past count");
        read_expect(5'h00,8'h01);
        // Single and incrementing writes.
        write1(5'h02,8'h15); read_expect(5'h02,8'h15); model_enable=8'h15;
        wbuf[0]=8'haa; wbuf[1]=8'h55; txn_write(5'h14,1,2,0); model_fill=8'haa; model_fence=8'h55;
        txn_read(5'h14,1,2,0);
        if(rbuf[0]!==8'haa || rbuf[1]!==8'h55) $fatal(1,"incrementing write/read");
        // Random mix against a model of IRQ_ENABLE/FILL_VALUE/FENCE_TAG.
        for(i=0;i<150;i=i+1) begin
            op=$urandom_range(0,3);
            v=8'($urandom);
            case(op)
                0: begin write1(5'h02,v&8'h7f); model_enable=v&8'h7f; end
                1: begin
                    n=$urandom_range(1,8);
                    for(j=0;j<n;j=j+1) wbuf[j]=8'($urandom);
                    txn_write(5'h14,0,n,0); model_fill=wbuf[n-1];
                end
                2: begin
                    wbuf[0]=v; wbuf[1]=~v; txn_write(5'h14,1,2,0); model_fill=v; model_fence=~v;
                end
                default: begin
                    txn_read(5'h14,1,2,0);
                    if(rbuf[0]!==model_fill || rbuf[1]!==model_fence) $fatal(1,"model FILL/FENCE");
                    read_expect(5'h02,model_enable);
                end
            endcase
        end
        // VRAM: stream 64 bytes into one data port, then read them back.
        set_addr(24'h001000);
        for(i=0;i<64;i=i+1) begin pattern[i]=8'($urandom); wbuf[i]=pattern[i]; end
        txn_write(5'h07,0,64,1);
        for(i=0;i<64;i=i+1) begin
            vram_read(24'h001000+i,v);
            if(v!==pattern[i]) $fatal(1,"VRAM %0d: %02h expected %02h",i,v,pattern[i]);
            vram_checked=vram_checked+1;
        end
        // A long FILL holds the queue; streamed writes then wait on BUSY.
        wbuf[0]=8'h30; wbuf[1]=8'h75; wbuf[2]=8'h5a; txn_write(5'h12,1,3,0);
        set_addr(24'h000000); command(8'h01);
        set_addr(24'h000100);
        for(i=0;i<96;i=i+1) begin pattern[i]=8'($urandom); wbuf[i]=pattern[i]; end
        txn_write(5'h07,0,96,1);
        if(busy_seen==0) $fatal(1,"BUSY never asserted");
        write1(5'h15,8'h77); command(8'h02);
        rbuf[0]=0;
        while(rbuf[0]!==8'h77) txn_read(5'h16,0,1,0);
        read_expect(5'h17,8'h00);
        for(i=0;i<96;i=i+8) begin
            vram_read(24'h000100+i,v);
            if(v!==pattern[i]) $fatal(1,"VRAM after FILL %0d",i);
            vram_checked=vram_checked+1;
        end
        vram_read(24'h000000,v); if(v!==8'h5a) $fatal(1,"FILL start");
        vram_read(24'h00752f,v); if(v!==8'h5a) $fatal(1,"FILL end");
        vram_read(24'h007530,v); if(v!==8'h00) $fatal(1,"FILL overrun");
        // Short FILLs drain slower than they arrive: BUSY toggles at the margin.
        wbuf[0]=8'd200; wbuf[1]=8'h00; wbuf[2]=8'ha5; txn_write(5'h12,1,3,0);
        set_addr(24'h002000);
        n=busy_seen;
        for(i=0;i<80;i=i+1) wbuf[i]=8'h01;
        txn_write(5'h0e,0,80,1);
        if(busy_seen-n<10) $fatal(1,"only %0d BUSY waits in the FILL stream",busy_seen-n);
        write1(5'h15,8'h78); command(8'h02);
        while(rbuf[0]!==8'h78) txn_read(5'h16,0,1,0);
        read_expect(5'h17,8'h00);
        vram_read(24'h0020c7,v); if(v!==8'ha5) $fatal(1,"FILL stream");
        // Aborts: inside a data byte and inside the header issue nothing.
        begin_txn; xfer_byte(8'h02,status,0,0);
        for(j=0;j<CHUNKS-1;j=j+1) chunk(4'hf,v[3:0],0,0);
        end_txn; expected=expected+(LANES==1);
        begin_txn; for(j=0;j<CHUNKS-1;j=j+1) chunk(4'h0,v[3:0],0,0);
        end_txn; expected=expected+(LANES==1);
        // A reserved header bit discards the whole transaction.
        wbuf[0]=8'h7f; begin_txn; xfer_byte(8'h22,status,0,0); xfer_byte(8'h7f,v,0,0);
        end_txn; expected=expected+(LANES==1);
        read_expect(5'h02,model_enable);
        // IRQ: BAD_ACCESS with IRQ.ERROR enabled pulls /IRQ, W1C releases it.
        write1(5'h02,8'h40); write1(5'h18,8'hff);
        #200; if(!irq_pin) $fatal(1,"IRQ not driven");
        read_expect(5'h17,8'h04);
        write1(5'h17,8'h04); write1(5'h01,8'h40);
        #200; if(irq_pin) $fatal(1,"IRQ not released");
        if(late) $fatal(1,"adapter deadline missed");
        if(requests!=expected) $fatal(1,"%0d requests, %0d expected",requests,expected);
        $display("PASS: %0s host bus, %0d requests, %0d VRAM bytes checked, BUSY waits %0d, host setup/hold, no contention, aborts, IRQ",
            LANES==1 ? "SPI" : "QSPI",requests,vram_checked,busy_seen);
        $finish;
    end
    initial begin #50000000; $fatal(1,"host bus test timeout"); end
endmodule

module tb_spi_bus; tb_host_bus #(.LANES(1)) tb(); endmodule
module tb_qspi_bus; tb_host_bus #(.LANES(4)) tb(); endmodule
