`timescale 1ns/1ps
// kagura_core through the CPU-independent request interface: register checks,
// command queue order, VRAM engine and the public VRAM regions, against a
// byte model that tracks only bytes written so far.
module tb_vram_core;
    reg clk=0;
    always #9.259 clk=~clk;
    reg reset=1;
    reg req_valid=0, req_write=0; reg [4:0] req_addr=0; reg [7:0] req_wdata=0;
    wire req_ready, rsp_valid, rsp_error, irq; wire [7:0] rsp_rdata;
    reg vblank=0;
    kagura_core #(.CAPS(8'h01)) dut(.clk(clk),.reset(reset),.audio_full(1'b0),.audio_underflow_toggle(1'b0),.audio_muted(1'b0),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),
        .rsp_ready(1'b1),.rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.irq(irq),
        .render_start(1'b0),.render_line(8'd0),.line_write(),.line_addr(),.line_data(),.render_done(),
        .vblank_start(vblank),.vblank_live(1'b0),.underrun_event(1'b0),.line_start(1'b0),.shown_line(8'd0),
        .render_cycles());

    localparam [4:0] STATUS=5'h00, IRQ_STATUS=5'h01, IRQ_ENABLE=5'h02, ADDR_L=5'h04, ADDR_M=5'h05,
        ADDR_H=5'h06, VRAM_WRITE=5'h07, READ_REQUEST=5'h08, READ_RESULT=5'h09, EXT_INDEX=5'h0a,
        EXT_DATA=5'h0b, AUDIO_INDEX=5'h0c, COMMAND=5'h0e, FIFO_STATUS=5'h0f, INC_L=5'h10, INC_H=5'h11,
        LENGTH_L=5'h12, LENGTH_H=5'h13, FILL_VALUE=5'h14, FENCE_TAG=5'h15, DONE_TAG=5'h16,
        ERROR_CODE=5'h17, ID0=5'h18;
    integer spacing=16; // system cycles between accesses (CPU pace); 0 = back-to-back
    reg [7:0] last_rdata; reg last_error;
    task automatic access(input reg w,input reg [4:0] a,input reg [7:0] d);
        begin
            // Back-to-back: the next payload follows 1ns after the accepting
            // edge, so it can be accepted on the very next edge.
            if(spacing!=0) @(negedge clk);
            req_valid=1; req_write=w; req_addr=a; req_wdata=d;
            @(posedge clk); while(!req_ready) @(posedge clk);
            // Processed in the next cycle; the response is valid after the
            // following edge for one cycle.
            #1; req_valid=0; // drop valid right after acceptance (no second capture)
            @(posedge clk); #1;
            if(!rsp_valid) $fatal(1,"no response");
            last_rdata=rsp_rdata; last_error=rsp_error;
            if(spacing!=0) begin
                @(negedge clk); req_valid=0;
                repeat(spacing-1) @(posedge clk);
            end
        end
    endtask
    task automatic wr(input reg [4:0] a,input reg [7:0] d,input reg expect_error);
        begin access(1,a,d); if(last_error!==expect_error) $fatal(1,"write %02h=%02h error %0d",a,d,last_error); end
    endtask
    task automatic rd(input reg [4:0] a,input reg expect_error,output reg [7:0] v);
        begin access(0,a,0); v=last_rdata; if(last_error!==expect_error) $fatal(1,"read %02h error %0d",a,last_error); end
    endtask
    task automatic expect_reg(input reg [4:0] a,input reg [7:0] e);
        reg [7:0] v; begin rd(a,0,v); if(v!==e) $fatal(1,"reg %02h=%02h expected %02h",a,v,e); end
    endtask
    task automatic set_addr(input reg [23:0] a);
        begin wr(ADDR_L,a[7:0],0); wr(ADDR_M,a[15:8],0); wr(ADDR_H,a[23:16],0); end
    endtask
    task automatic set_inc(input reg [15:0] v); begin wr(INC_L,v[7:0],0); wr(INC_H,v[15:8],0); end endtask
    task automatic clear_errors; reg [7:0] v; begin rd(ERROR_CODE,0,v); wr(ERROR_CODE,v,0); wr(IRQ_STATUS,8'h7f,0); end endtask
    task automatic wait_idle; reg [7:0] v; begin v=8'h80; while(v[7]) rd(STATUS,0,v); end endtask

    // Byte model of the public regions (indexed by VRAM address).
    reg [7:0] mem [0:16'ha7ff];
    reg known [0:16'ha7ff];
    function automatic bit public(input [23:0] a);
        public=a<24'h009000 || (a>=24'h00a000 && a<24'h00a800) || (a>=24'h009400 && a<24'h009600)
            || (a>=24'h009800 && a<24'h009a00);
    endfunction
    function automatic [7:0] stored(input [23:0] a,input [7:0] d);
        begin
            stored=(a>=24'h009400 && a<24'h009600 && a[0]) ? {4'h0,d[3:0]} : d;
            if(a>=24'h00a000 && a<24'h00a800) case(a%8)
                1: stored=d & 8'h03;
                3: stored=d & 8'h7f;
                5: stored=d & 8'h3f;
                6,7: stored=0;
                default: ;
            endcase
        end
    endfunction
    reg [23:0] cur_addr; reg [15:0] cur_inc;
    task automatic model_write(input reg [7:0] d);
        begin
            wr(VRAM_WRITE,d,!public(cur_addr));
            if(public(cur_addr)) begin
                mem[cur_addr[15:0]]=stored(cur_addr,d); known[cur_addr[15:0]]=1;
                cur_addr=cur_addr+{8'h00,cur_inc};
            end
        end
    endtask
    integer checked_reads=0;
    task automatic model_read;
        reg [7:0] v, expect_v; reg have; reg [23:0] a;
        begin
            a=cur_addr; have=known[a[15:0]]; expect_v=mem[a[15:0]];
            wr(READ_REQUEST,8'h00,0);
            cur_addr=cur_addr+{8'h00,cur_inc};
            v=8'h00; while(!v[2]) rd(STATUS,0,v);
            rd(READ_RESULT,0,v);
            if(have) begin
                if(v!==expect_v) $fatal(1,"VRAM %06h read %02h expected %02h",a,v,expect_v);
                checked_reads=checked_reads+1;
            end
        end
    endtask
    task automatic do_fill(input reg [23:0] a,input reg [15:0] n,input reg [7:0] value,input reg expect_error);
        integer k;
        begin
            set_addr(a); wr(LENGTH_L,n[7:0],0); wr(LENGTH_H,n[15:8],0); wr(FILL_VALUE,value,0);
            wr(COMMAND,8'h01,expect_error);
            if(!expect_error) for(k=0;k<n;k=k+1) begin
                mem[a[15:0]+k[15:0]]=stored(a+k,value); known[a[15:0]+k[15:0]]=1;
            end
            cur_addr=a; // FILL does not move the address register
        end
    endtask

    integer i, n, burst_ok, burst_refused, stalls=0;
    always @(posedge clk) if(!reset && req_valid && !req_ready) stalls=stalls+1;
    reg [7:0] v;
    reg [23:0] a;
    initial begin
        for(i=0;i<=16'ha7ff;i=i+1) known[i]=0;
        #100; reset=0; repeat(4) @(posedge clk);
        expect_reg(STATUS,8'h00);
        wr(VRAM_WRITE,8'hff,1); expect_reg(ERROR_CODE,8'h10); expect_reg(ADDR_L,0);
        wr(READ_REQUEST,0,1); wr(COMMAND,8'h03,1);
        wait(dut.init_done); clear_errors();
        expect_reg(ID0,8'h4b); expect_reg(STATUS,8'h01); expect_reg(FIFO_STATUS,8'd32); expect_reg(INC_L,8'h01);
        // Direction and undefined accesses.
        rd(VRAM_WRITE,1,v); clear_errors();
        wr(ID0,8'h00,1); expect_reg(ERROR_CODE,8'h04); clear_errors();
        wr(AUDIO_INDEX,8'h60,0); wr(5'h0d,8'h00,1); wr(COMMAND,8'h7f,1); clear_errors();
        rd(READ_RESULT,1,v); if(v!==0) $fatal(1,"READ_RESULT without READY"); expect_reg(ERROR_CODE,8'h10); clear_errors();
        wr(READ_REQUEST,8'h01,1); expect_reg(ERROR_CODE,8'h04); clear_errors();
        // Extended registers: RW shadow, RO constants, undefined index.
        wr(EXT_INDEX,8'h04,0); expect_reg(EXT_DATA,8'd255); wr(EXT_DATA,8'd17,0); expect_reg(EXT_DATA,8'd17);
        wr(EXT_INDEX,8'h05,0); expect_reg(EXT_DATA,8'd0); wr(EXT_DATA,8'd1,1); // MAX_SPRITES 256 reads 0
        wr(EXT_INDEX,8'h0a,0); expect_reg(EXT_DATA,8'd240); wr(EXT_DATA,8'd1,1); clear_errors();
        wr(EXT_INDEX,8'h0b,0); expect_reg(EXT_DATA,8'd0); wr(EXT_DATA,8'd1,1); clear_errors();
        // Invalid addresses: refused, address register unchanged.
        cur_inc=1; set_inc(1);
        cur_addr=24'h00a800; set_addr(cur_addr); model_write(8'h11); expect_reg(ERROR_CODE,8'h02);
        expect_reg(ADDR_L,8'h00); expect_reg(ADDR_M,8'ha8); clear_errors();
        cur_addr=24'h009000; set_addr(cur_addr); model_write(8'h12); expect_reg(ERROR_CODE,8'h02); clear_errors();
        cur_addr=24'h010000; set_addr(cur_addr); wr(READ_REQUEST,8'h00,1); clear_errors();
        // FILL range checks: crossing a region end is refused without partial effect.
        do_fill(24'h008ffe,16'd3,8'haa,1); clear_errors();
        do_fill(24'h00a7f0,16'd32,8'h55,1); clear_errors();
        do_fill(24'h000000,16'd0,8'h00,0);
        // Every OAM record/byte lane: FILL uses the same reserved-bit masks
        // as single writes, and reserved bytes must read back as zero.
        do_fill(24'h00a000,16'd2048,8'hff,0); wait_idle();
        cur_addr=24'h00a000; set_addr(cur_addr);
        for(i=0;i<2048;i=i+1) model_read();
        // Region boundaries, palette masking, wave, map halves.
        foreach_case: begin
            reg [23:0] edges [0:11];
            edges[0]=24'h000000; edges[1]=24'h007fff; edges[2]=24'h008000; edges[3]=24'h0087ff;
            edges[4]=24'h008800; edges[5]=24'h008fff; edges[6]=24'h00a000; edges[7]=24'h00a7ff;
            edges[8]=24'h009400; edges[9]=24'h0095ff; edges[10]=24'h009800; edges[11]=24'h0099ff;
            for(i=0;i<12;i=i+1) begin cur_addr=edges[i]; set_addr(cur_addr); model_write(8'hf0^i[7:0]); end
            for(i=0;i<12;i=i+1) begin cur_addr=edges[i]; set_addr(cur_addr); model_read(); end
        end
        // FILL and FENCE: DONE_TAG and IRQ.FENCE_DONE after completion.
        do_fill(24'h004000,16'd700,8'h3c,0);
        wr(FENCE_TAG,8'h5a,0); wr(COMMAND,8'h02,0); wait_idle();
        expect_reg(DONE_TAG,8'h5a); rd(IRQ_STATUS,0,v); if(!v[2] || !v[3]) $fatal(1,"FENCE/READ_DONE IRQ bits %02h",v);
        wr(IRQ_ENABLE,8'h04,0); if(!irq) $fatal(1,"FENCE IRQ not raised"); wr(IRQ_STATUS,8'h0c,0);
        if(irq) $fatal(1,"IRQ not cleared"); wr(IRQ_ENABLE,8'h00,0);
        for(i=0;i<20;i=i+1) begin cur_addr=24'h004000+$urandom_range(0,699); set_addr(cur_addr); model_read(); end
        // READ_COLLISION: a second request before the result is consumed.
        cur_addr=24'h004000; set_addr(cur_addr); wr(READ_REQUEST,8'h00,0);
        v=0; while(!v[2]) rd(STATUS,0,v);
        wr(READ_REQUEST,8'h00,1); expect_reg(ERROR_CODE,8'h08); expect_reg(ADDR_L,8'h01);
        rd(READ_RESULT,0,v); if(v!==8'h3c) $fatal(1,"collision overwrote result"); clear_errors();
        // INC: 0 keeps the address, larger steps stride.
        cur_inc=0; set_inc(0); cur_addr=24'h001234; set_addr(cur_addr);
        model_write(8'h01); model_write(8'h02); model_read();
        cur_inc=16'd257; set_inc(16'd257); cur_addr=24'h000100; set_addr(cur_addr);
        for(i=0;i<16;i=i+1) model_write(8'(i*5));
        cur_addr=24'h000100; set_addr(cur_addr); for(i=0;i<16;i=i+1) model_read();
        // FIFO full: a long FILL occupies the engine while writes queue up.
        cur_inc=1; set_inc(1);
        do_fill(24'h000000,16'd16384,8'h77,0);
        spacing=6; burst_ok=0; burst_refused=0;
        cur_addr=24'h009800; set_addr(cur_addr);
        for(i=0;i<40;i=i+1) begin
            access(1,VRAM_WRITE,8'(i));
            if(last_error) burst_refused=burst_refused+1;
            else begin
                if(burst_refused!=0) $fatal(1,"write accepted after a refusal while the FILL still runs");
                mem[16'h9800+burst_ok]=8'(i); known[16'h9800+burst_ok]=1; burst_ok=burst_ok+1;
            end
        end
        spacing=16;
        if(burst_ok!=32) $fatal(1,"%0d writes accepted, expected 32 (queue depth incl. staging)",burst_ok);
        rd(ERROR_CODE,0,v); if(v!==8'h01) $fatal(1,"ERROR_CODE %02h after full queue",v);
        expect_reg(FIFO_STATUS,8'h80); expect_reg(ADDR_L,8'(burst_ok)); clear_errors();
        wait_idle(); expect_reg(FIFO_STATUS,8'd32);
        for(i=0;i<16384;i=i+1) begin mem[i]=8'h77; known[i]=1; end
        for(i=0;i<burst_ok;i=i+1) begin cur_addr=24'h009800+i; set_addr(cur_addr); model_read(); end
        n=burst_ok;
        // Back-to-back requests: address/INC changes and enqueues stall the
        // next request for one cycle, so checks and the queue are never stale.
        stalls=0; spacing=0;
        cur_addr=24'h005000; set_addr(cur_addr);
        for(i=0;i<8;i=i+1) model_write(8'h90+i[7:0]);
        cur_addr=24'h005000; set_addr(cur_addr);
        for(i=0;i<8;i=i+1) model_read();
        cur_addr=24'h009200; set_addr(cur_addr); model_write(8'h00); clear_errors();
        @(negedge clk); req_valid=0; spacing=16;
        if(stalls==0) $fatal(1,"back-to-back requests never stalled");
        // Random traffic over all public regions.
        for(i=0;i<1500;i=i+1) begin
            case($urandom_range(0,2))
                0: begin
                    a=24'($urandom_range(0,16'h99ff)); cur_addr=a; set_addr(a); model_write(8'($urandom));
                    if(!public(a)) clear_errors();
                end
                1: begin
                    a=24'($urandom_range(0,16'h99ff));
                    if(public(a)) begin cur_addr=a; set_addr(a); model_read(); end
                end
                default: begin cur_addr=24'($urandom_range(0,16'h7fff)); set_addr(cur_addr); model_read(); end
            endcase
        end
        expect_reg(ERROR_CODE,8'h00);
        $display("PASS: VRAM core, %0d model-checked reads, regions/palette mask, FILL/FENCE/INC, FIFO full (%0d accepted), errors and EXT registers",checked_reads,n);
        $finish;
    end
    initial begin #400000000; $fatal(1,"vram core timeout"); end
endmodule
