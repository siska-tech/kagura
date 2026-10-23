`timescale 1ns/1ps
// Real VDP initialization/line-zero readiness drives the real CPU adapter.
module tb_startup_cpu;
    reg sys=0,pix=0;
    always #9.259 sys=~sys;
    always #19.8415 pix=~pix;
    reg reset=1;
    reg [9:0] cx=0,cy=0;
    wire init_done,frame_ready,req_valid,req_ready,req_write,rsp_valid,rsp_ready,rsp_error,irq;
    wire [4:0] req_addr;
    wire [7:0] req_wdata,rsp_rdata,dout;
    wire phi2,cpu_release,oe,irq_drive,late;
    wire [23:0] rgb;
    wire ready=init_done && frame_ready;
    kagura_w65c02_adapter bus(sys,reset,ready,phi2,cpu_release,5'h18,1'b0,1'b1,8'b0,
        dout,oe,irq_drive,irq,req_valid,req_ready,req_write,req_addr,req_wdata,rsp_valid,rsp_ready,rsp_rdata,rsp_error,late);
    kagura_vdp vdp(.sys_clk(sys),.sys_reset(reset),.audio_full(1'b0),.audio_underflow_toggle(1'b0),.audio_muted(1'b0),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(rsp_ready),
        .rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.irq(irq),.init_done(init_done),.frame_ready(frame_ready),.render_cycles(),
        .pix_clk(pix),.pix_reset(reset),.cx(cx),.cy(cy),.rgb(rgb));
    always @(posedge pix)
        if(reset) begin cx<=0; cy<=0; end
        else if(cx==799) begin cx<=0; cy<=cy==524 ? 10'd0 : cy+1'b1; end
        else cx<=cx+1'b1;
    integer rises=0,responses=0;
    always @(posedge phi2) if(!reset && ready) rises=rises+1;
    always @(negedge sys) if(!reset) begin
        if(!ready && (cpu_release || req_valid || oe)) $fatal(1,"CPU operated before RAM/line-zero ready");
        if(cpu_release && rises<8) $fatal(1,"CPU release before eight PHI2 pulses");
        if(rsp_valid) begin
            if(rsp_error || rsp_rdata!=8'h4b) $fatal(1,"ID read after startup");
            responses=responses+1;
        end
        if(!init_done && rgb!==0) $fatal(1,"nonblack startup video");
    end
    task automatic boot;
        begin
            @(negedge sys); reset=1; rises=0; responses=0;
            #200; @(negedge sys); reset=0;
            wait(init_done);
            if(cpu_release || frame_ready) $fatal(1,"line-zero gate bypassed");
            wait(frame_ready); wait(cpu_release); wait(responses>=4);
            if(late) $fatal(1,"bus deadline after startup");
        end
    endtask
    initial begin
        boot(); boot();
        $display("PASS: CPU startup cold/warm reset, RAM clear + first line-zero gate, eight PHI2 pulses, black video and ID reads");
        $finish;
    end
    initial begin #50000000; $fatal(1,"startup CPU timeout"); end
endmodule
