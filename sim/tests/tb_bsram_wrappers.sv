`timescale 1ns/1ps
// P1-06 RAM wrapper contracts: latency, dual-clock transfer, atomic byte RMW,
// TDP collision detection and line-bank handover. Real clock periods.
module tb_bsram_wrappers;
    reg sys=0,pix=0;
    always #9.259 sys=~sys;
    always #19.8415 pix=~pix;
    reg sys_reset=1,pix_reset=1;
    integer i,j,errors=0;

    // A: SP 2048x8, data valid exactly one edge after the address.
    reg sp_en=0,sp_we=0; reg [10:0] sp_addr=0; reg [7:0] sp_wd=0; wire [7:0] sp_rd;
    kagura_ram_sp #(.DEPTH(2048),.WIDTH(8)) sp(sys,sp_en,sp_we,sp_addr,sp_wd,sp_rd);

    // B: SDP 512x32, write on system clock, read on pixel clock.
    reg sdp_we=0,sdp_re=0; reg [8:0] sdp_wa=0,sdp_ra=0; reg [31:0] sdp_wd=0; wire [31:0] sdp_rd;
    kagura_ram_sdp #(.DEPTH(512),.WIDTH(32)) sdp(sys,sdp_we,sdp_wa,sdp_wd,pix,sdp_re,sdp_ra,sdp_rd);

    // C: byte RMW on 1024x16.
    reg rq_valid=0,rq_write=0,rq_byte=0,rq_high=0; reg [9:0] rq_addr=0; reg [15:0] rq_wd=0;
    wire rq_ready,rs_valid; wire [15:0] rs_rd;
    kagura_ram_rmw16 rmw(sys,sys_reset,rq_valid,rq_ready,rq_write,rq_byte,rq_high,rq_addr,rq_wd,rs_valid,rs_rd,,1'b0,10'd0);
    reg [15:0] model [0:1023];

    // D: TDP collision checker in counting mode.
    reg ta_en=0,ta_we=0,tb_en=0; reg [9:0] ta_addr=0,tb_addr=0; reg [15:0] ta_wd=0;
    wire [15:0] ta_rd,tb_rd;
    kagura_ram_tdp #(.DEPTH(1024),.WIDTH(16),.FATAL_ON_COLLISION(0)) tdp(
        sys,ta_en,ta_we,ta_addr,ta_wd,ta_rd,pix,tb_en,tb_addr,tb_rd);

    // E: line banks.
    reg lb_en=0,lb_we=0,lb_done=0,lb_swap=0,lb_pen=0; reg [9:0] lb_addr=0,lb_paddr=0; reg [15:0] lb_wd=0;
    wire lb_can,lb_underrun; wire [15:0] lb_rd,lb_prd;
    kagura_line_banks banks(sys,sys_reset,lb_can,lb_en,lb_we,lb_addr,lb_wd,lb_rd,lb_done,
        pix,pix_reset,lb_swap,lb_pen,lb_paddr,lb_prd,lb_underrun);

    task automatic sys_cycle; begin @(posedge sys); #1; end endtask
    task automatic pix_cycle; begin @(posedge pix); #1; end endtask

    // Byte RMW request; returns after acceptance and checks the busy window.
    task automatic rmw_request(input reg w,input reg b,input reg h,input reg [9:0] a,input reg [15:0] d);
        integer busy;
        begin
            while(!rq_ready) sys_cycle();
            rq_valid=1; rq_write=w; rq_byte=b; rq_high=h; rq_addr=a; rq_wd=d;
            sys_cycle(); rq_valid=0;
            if(w && b) begin
                busy=0;
                while(!rq_ready) begin busy=busy+1; sys_cycle(); end
                if(busy!=2) $fatal(1,"byte RMW busy %0d cycles",busy);
                if(h) model[a][15:8]=d[7:0]; else model[a][7:0]=d[7:0];
            end else if(w) model[a]=d;
            else begin
                if(!rs_valid) $fatal(1,"read response latency");
                if(rs_rd!==model[a]) $fatal(1,"RMW read %0d: %h expected %h",a,rs_rd,model[a]);
            end
        end
    endtask

    // E helpers: system renders a line tag into 320 words, pixel checks them.
    integer sys_line=0, shown_tag=-1, swaps=0, repeats=0;
    reg render_enable=1, run_lines=0;
    always @(posedge sys) if(run_lines && render_enable && lb_can && !sys_reset) begin
        #1;
        for(j=0;j<320;j=j+1) begin
            lb_en=1; lb_we=1; lb_addr=j[9:0]; lb_wd={sys_line[5:0],j[9:0]}; sys_cycle();
        end
        lb_en=0; lb_we=0; lb_done=1; sys_cycle(); lb_done=0;
        sys_line=sys_line+1;
        while(!lb_can) sys_cycle();
    end
    integer px,tag;
    initial begin
        for(i=0;i<1024;i=i+1) model[i]=0;
        #100; sys_reset=0; pix_reset=0;
        // A
        for(i=0;i<2048;i=i+1) begin sp_en=1; sp_we=1; sp_addr=i[10:0]; sp_wd=8'(i*7+3); sys_cycle(); end
        sp_we=0;
        for(i=0;i<2048;i=i+1) begin
            sp_addr=i[10:0]; sys_cycle();
            if(sp_rd!==8'(i*7+3)) $fatal(1,"SP data/latency at %0d",i);
        end
        sp_en=0;
        // B: writes complete long before reads on the other clock.
        for(i=0;i<512;i=i+1) begin sdp_we=1; sdp_wa=i[8:0]; sdp_wd=32'(i)*32'h01010101 ^ 32'h5a5a0000; sys_cycle(); end
        sdp_we=0; repeat(4) pix_cycle();
        for(i=0;i<512;i=i+1) begin
            sdp_re=1; sdp_ra=i[8:0]; pix_cycle();
            if(sdp_rd!==(32'(i)*32'h01010101 ^ 32'h5a5a0000)) $fatal(1,"SDP cross-clock data at %0d",i);
        end
        sdp_re=0;
        // C: word writes, then random mix of byte writes and reads.
        for(i=0;i<1024;i=i+1) rmw_request(1,0,0,i[9:0],16'(i*13));
        for(i=0;i<3000;i=i+1) rmw_request($urandom_range(0,2)!=0,1'b1,1'($urandom),10'($urandom),16'($urandom));
        for(i=0;i<1024;i=i+1) rmw_request(0,0,0,i[9:0],0);
        // D: different addresses never count; same address within the window does.
        for(i=0;i<200;i=i+1) begin
            ta_en=1; ta_we=1; ta_addr=10'(i); ta_wd=16'(i); tb_en=1; tb_addr=10'(i+512);
            sys_cycle();
        end
        ta_en=0; ta_we=0; tb_en=0;
        if(tdp.collisions!=0) $fatal(1,"false TDP collision");
        // 54/25.2 = 15/7: system and pixel edges coincide every 277.8ns, so
        // a continuous same-address write/read must hit the window.
        ta_en=1; ta_we=1; ta_addr=10'd7; tb_en=1; tb_addr=10'd7;
        repeat(20) pix_cycle();
        ta_en=0; ta_we=0; tb_en=0;
        if(tdp.collisions==0) $fatal(1,"TDP same-address collision not detected");
        // E: 40 logical lines (1600 pixel clocks each), then one stalled line.
        run_lines=1;
        repeat(2) begin
            repeat(1599) pix_cycle(); lb_swap=1; pix_cycle(); lb_swap=0;
        end
        for(i=0;i<40;i=i+1) begin
            // Read the displayed line once; every word must carry one tag.
            lb_pen=1;
            for(px=0;px<320;px=px+1) begin
                lb_paddr=10'(px); pix_cycle();
                if(lb_prd[9:0]!==10'(px)) $fatal(1,"line word order");
                if(px==0) tag=lb_prd[15:10];
                else if(lb_prd[15:10]!==tag[5:0]) $fatal(1,"torn line: tag %0d vs %0d",lb_prd[15:10],tag);
            end
            lb_pen=0;
            if(shown_tag>=0 && tag!=((shown_tag+1)%64)) $fatal(1,"line skipped/repeated: %0d after %0d",tag,shown_tag);
            shown_tag=tag;
            repeat(1600-320-1) pix_cycle(); lb_swap=1; pix_cycle(); lb_swap=0;
        end
        if(lb_underrun) $fatal(1,"underrun while the renderer kept up");
        render_enable=0;
        repeat(2) begin repeat(1599) pix_cycle(); lb_swap=1; pix_cycle(); lb_swap=0; end
        if(!lb_underrun) $fatal(1,"stalled renderer not reported as underrun");
        $display("PASS: SP2048x8 latency, SDP512x32 cross-clock, 3000 random byte RMW ops (2-cycle busy), TDP collision detect, 40 line handovers + underrun");
        $finish;
    end
    initial begin #20000000; $fatal(1,"bsram test timeout"); end
endmodule
