`timescale 1ns/1ps
// End-to-end background frame: VRAM written through the register window,
// COMMIT at VBlank, then every visible pixel of a frame compared with a
// software reference renderer. Real clock periods: VIC1 640x480 (2x2,
// 54/25.2MHz) or VIC4 1280x720 (4x4, 180 logical lines, 54/74.25MHz).
module tb_vdp_frame #(parameter bit SPRITES=0, parameter integer VIC=1);
    localparam integer H_TOTAL=VIC==4 ? 1650 : 800, V_TOTAL=VIC==4 ? 750 : 525;
    localparam integer H_ACTIVE=VIC==4 ? 1280 : 640, V_ACTIVE=VIC==4 ? 720 : 480;
    localparam integer SCALE=VIC==4 ? 4 : 2, LINES=V_ACTIVE/SCALE, XW=VIC==4 ? 11 : 10;
    localparam real PIX_HALF=VIC==4 ? 6.734 : 19.8415;
    reg sys=0, pix=0;
    always #9.259 sys=~sys;
    always #(PIX_HALF) pix=~pix;
    reg sys_reset=1, pix_reset=1;
    reg req_valid=0, req_write=0; reg [4:0] req_addr=0; reg [7:0] req_wdata=0;
    wire req_ready, rsp_valid, rsp_error, irq; wire [7:0] rsp_rdata;
    wire [11:0] render_cycles;
    reg [XW-1:0] cx=0;
    reg [9:0] cy=0;
    wire [23:0] rgb;
    kagura_vdp #(.CAPS(8'h01),.VIDEO_ID_CODE(VIC)) dut(.sys_clk(sys),.sys_reset(sys_reset),
        .audio_full(1'b0),.audio_underflow_toggle(1'b0),.audio_muted(1'b0),.req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.render_cycles(render_cycles),
        .pix_clk(pix),.pix_reset(pix_reset),.cx(cx),.cy(cy),.rgb(rgb));
    // H_TOTAL x V_TOTAL timing, like the HDMI core's cx/cy.
    always @(posedge pix)
        if(pix_reset) begin cx<=0; cy<=0; end
        else if(cx==H_TOTAL-1) begin cx<=0; cy<=cy==V_TOTAL-1 ? 10'd0 : cy+1'b1; end
        else cx<=cx+1'b1;

    localparam [4:0] STATUS=5'h00, IRQ_STATUS=5'h01, DISPLAY_CTRL=5'h03, ADDR_L=5'h04, ADDR_M=5'h05,
        ADDR_H=5'h06, VRAM_WRITE=5'h07, EXT_INDEX=5'h0a, EXT_DATA=5'h0b, COMMAND=5'h0e,
        INC_L=5'h10, ERROR_CODE=5'h17, FRAME_COUNT=5'h1d;
    reg [7:0] last_rdata; reg last_error;
    task automatic access(input reg w,input reg [4:0] a,input reg [7:0] d);
        begin
            @(negedge sys); req_valid=1; req_write=w; req_addr=a; req_wdata=d;
            @(posedge sys); while(!req_ready) @(posedge sys);
            #1; req_valid=0;
            @(posedge sys); #1; // response valid for one cycle after the next edge
            last_rdata=rsp_rdata; last_error=rsp_error;
            // CPU pace: one access per 16 system cycles.
            repeat(14) @(posedge sys);
        end
    endtask
    task automatic wr(input reg [4:0] a,input reg [7:0] d);
        begin access(1,a,d); if(last_error) $fatal(1,"write %02h=%02h refused",a,d); end
    endtask
    task automatic rd(input reg [4:0] a,output reg [7:0] v); begin access(0,a,0); v=last_rdata; end endtask
    task automatic set_addr(input reg [23:0] a); begin wr(ADDR_L,a[7:0]); wr(ADDR_M,a[15:8]); wr(ADDR_H,a[23:16]); end endtask
    task automatic ext(input reg [7:0] i,input reg [7:0] v); begin wr(EXT_INDEX,i); wr(EXT_DATA,v); end endtask

    // Reference memory.
    reg [7:0] pattern [0:2047];        // tiles 0..63
    reg [15:0] map [0:2047];
    reg [11:0] palette [0:255];
    reg [8:0] sx; reg [7:0] sy, backdrop; reg bg_on;
    reg spr_on=0;
    integer sprite_x[0:63],sprite_y[0:63],sprite_tile[0:63],sprite_pal[0:63],sprite_flags[0:63];
    function automatic [23:0] expected(input integer x,input integer y);
        integer lx, ly, px, py, row, col, idx,n,size,eligible,xx,yy,t,cp;
        reg solid,claimed;
        reg [15:0] m; reg [7:0] b; reg [3:0] p; reg [11:0] c;
        begin
            lx=x/SCALE; ly=y/SCALE;
            px=(lx+sx)%512; py=(ly+sy)%256;
            m=map[(py/8)*64+px/8];
            row=m[15] ? 7-(py%8) : py%8;
            col=m[14] ? 7-(px%8) : px%8;
            b=pattern[m[9:0]*32+row*4+col/2];
            p=col%2==0 ? b[7:4] : b[3:0];
            idx=(bg_on && p!=0) ? m[13:10]*16+p : backdrop;
            c=palette[idx];
            solid=bg_on && p!=0; claimed=0; eligible=0;
            if(SPRITES && spr_on) for(n=0;n<64;n=n+1) begin
                size=(sprite_flags[n]&2)!=0 ? 16 : 8;
                if((sprite_flags[n]&1)!=0 && ly>=sprite_y[n] && ly<sprite_y[n]+size) begin
                    eligible=eligible+1;
                    xx=lx-sprite_x[n]; yy=ly-sprite_y[n];
                    if(eligible<=16 && xx>=0 && xx<size && !claimed) begin
                        if((sprite_flags[n]&4)!=0) xx=size-1-xx;
                        if((sprite_flags[n]&8)!=0) yy=size-1-yy;
                        t=size==16 ? (sprite_tile[n]/4)*4+2*(yy/8)+xx/8 : sprite_tile[n];
                        b=pattern[t*32+(yy%8)*4+(xx%8)/2];
                        cp=xx%2==0 ? b[7:4] : b[3:0];
                        if(cp!=0) begin
                            claimed=1;
                            if((sprite_flags[n]&16)==0 || !solid) c=palette[sprite_pal[n]*16+cp];
                        end
                    end
                end
            end
            expected={c[11:8],c[11:8],c[7:4],c[7:4],c[3:0],c[3:0]};
        end
    endfunction

    integer i, x, y, errors_seen, max_cycles=0, renders=0;
    reg [7:0] v, frames_before;
    reg [63:0] sprite_record;
    always @(posedge sys) if(dut.render_done) begin
        renders=renders+1; if(render_cycles>max_cycles) max_cycles=render_cycles;
    end
    task automatic commit_and_wait;
        begin
            wr(IRQ_STATUS,8'h7f); wr(COMMAND,8'h03);
            v=8'h10; while(v[4]) rd(STATUS,v);  // COMMIT_BUSY clears after the copy
            rd(IRQ_STATUS,v); if(!v[4]) $fatal(1,"COMMIT_DONE not raised");
        end
    endtask
    task automatic check_frame(input integer which);
        integer bad;
        begin
            // Wait for the start of a fresh frame, then compare every visible pixel.
            @(negedge pix); while(!(cx==H_TOTAL-1 && cy==V_TOTAL-1)) @(negedge pix);
            bad=0;
            for(y=0;y<V_ACTIVE;y=y+1) for(x=0;x<H_ACTIVE;x=x+1) begin
                @(negedge pix);
                if(cx!==x || cy!==y) $fatal(1,"scan position %0d,%0d at %0d,%0d",cx,cy,x,y);
                if(rgb!==expected(x,y)) begin
                    if(bad<5) $display("frame %0d pixel %0d,%0d: %06h expected %06h",which,x,y,rgb,expected(x,y));
                    bad=bad+1;
                end
                if(x==H_ACTIVE-1) repeat(H_TOTAL-H_ACTIVE) @(negedge pix);
            end
            if(bad!=0) $fatal(1,"frame %0d: %0d pixels differ",which,bad);
        end
    endtask

    initial begin
        // Poison both physical line banks, proving startup uses write-port
        // clearing rather than simulator/default bitstream RAM contents.
        for(i=0;i<512;i=i+1) begin
            dut.display.bank[0].ram.memory[i]=16'hffff;
            dut.display.bank[1].ram.memory[i]=16'hffff;
        end
        #200; sys_reset=0; pix_reset=0;
        wait(dut.init_done);
        for(i=0;i<512;i=i+1)
            if(dut.display.bank[0].ram.memory[i]!==0 || dut.display.bank[1].ram.memory[i]!==0)
                $fatal(1,"line bank not initialized at %d",i);
        repeat(10) @(posedge sys);
        // ABI 0.2: SCREEN_HEIGHT reports the logical line count.
        wr(EXT_INDEX,8'h0a); rd(EXT_DATA,v); if(v!=LINES) $fatal(1,"SCREEN_HEIGHT %0d",v);
        wr(INC_L,8'h01);
        // Palette shadow: 256 RGB444 words.
        set_addr(24'h009400);
        for(i=0;i<256;i=i+1) begin
            palette[i]=12'($urandom); wr(VRAM_WRITE,palette[i][7:0]); wr(VRAM_WRITE,{4'h0,palette[i][11:8]});
        end
        // 64 tiles of random patterns.
        set_addr(24'h000000);
        for(i=0;i<2048;i=i+1) begin pattern[i]=8'($urandom); wr(VRAM_WRITE,pattern[i]); end
        // Map: random tile 0..63, palette, flips.
        set_addr(24'h008000);
        for(i=0;i<2048;i=i+1) begin
            map[i]={2'($urandom),4'($urandom),4'd0,6'($urandom)};
            wr(VRAM_WRITE,map[i][7:0]); wr(VRAM_WRITE,map[i][15:8]);
        end
        if(SPRITES) begin
            set_addr(24'h009000);
            for(i=0;i<64;i=i+1) begin
                sprite_x[i]=i<20 ? 100+(i%5)*2 : (i*19)%350-15;
                sprite_y[i]=i<20 ? 10 : 60+i*2;
                sprite_tile[i]=i%16*4+3; sprite_pal[i]=i%16;
                sprite_flags[i]=3 | ((i%8)*4);
                sprite_record=0;
                sprite_record[9:0]=10'(sprite_x[i]); sprite_record[25:16]=10'(sprite_y[i]);
                sprite_record[41:32]=10'(sprite_tile[i]); sprite_record[45:42]=4'(sprite_pal[i]);
                sprite_record[52:48]=5'(sprite_flags[i]);
                for(integer k=0;k<8;k=k+1) wr(VRAM_WRITE,sprite_record[k*8 +: 8]);
            end
        end
        // Configuration A: scrolled, background on, raster IRQ at line 100.
        sx=9'd13; sy=8'd200; backdrop=8'd37; bg_on=1;
        ext(8'h00,sx[7:0]); ext(8'h01,{7'b0,sx[8]}); ext(8'h02,sy); ext(8'h03,backdrop); ext(8'h04,8'd100);
        spr_on=SPRITES; wr(DISPLAY_CTRL,SPRITES ? 8'h07 : 8'h03);
        commit_and_wait();
        rd(FRAME_COUNT,frames_before);
        check_frame(0);
        if(!dut.frame_ready) $fatal(1,"first line zero never prepared");
        rd(ERROR_CODE,v); if(v!==0) $fatal(1,"ERROR_CODE %02h after frame A",v);
        rd(IRQ_STATUS,v); if(!v[0] || !v[1]) $fatal(1,"VBLANK/RASTER IRQ bits %02h",v);
        rd(FRAME_COUNT,v); if(v==frames_before) $fatal(1,"FRAME_COUNT did not advance");
        if(SPRITES) begin
            rd(IRQ_STATUS,v); if(!v[5]) $fatal(1,"SPR_OVERFLOW not raised");
            rd(5'h1e,v); if(v!=16) $fatal(1,"overflow index %d",v);
            rd(5'h1f,v); if(v!=10) $fatal(1,"overflow line %d",v);
        end
        // Configuration B: X wraps near 512, background off -> backdrop only.
        sx=9'd505; sy=8'd7; backdrop=8'd200; bg_on=0;
        ext(8'h00,sx[7:0]); ext(8'h01,{7'b0,sx[8]}); ext(8'h02,sy); ext(8'h03,backdrop);
        wr(DISPLAY_CTRL,SPRITES ? 8'h05 : 8'h01);
        commit_and_wait();
        check_frame(1);
        // Configuration C: background on again with the same scroll.
        bg_on=1; spr_on=0; wr(DISPLAY_CTRL,8'h03); commit_and_wait(); check_frame(2);
        if(SPRITES) begin
            wr(IRQ_STATUS,8'h20); rd(5'h1e,v); if(v!=0) $fatal(1,"overflow index not cleared");
            rd(5'h1f,v); if(v!=0) $fatal(1,"overflow line not cleared");
            rd(IRQ_STATUS,v); if(v[5]) $fatal(1,"overflow after sprite disable");
        end
        rd(ERROR_CODE,v); if(v!==0) $fatal(1,"ERROR_CODE %02h (underrun?)",v);
        // Reset only the system side while the pixel clock/scan keep running.
        // The line-bank collision checker must remain silent during clearing.
        @(negedge sys); sys_reset=1;
        repeat(5) @(negedge sys);
        sys_reset=0;
        wait(dut.init_done);
        for(i=0;i<256;i=i+1) palette[i]=0;
        bg_on=0; spr_on=0; backdrop=0;
        check_frame(3);
        if(max_cycles>(SPRITES ? 2633 : 697)) $fatal(1,"line render took %0d cycles",max_cycles);
        $display("PASS: VDP frames VIC%0d %0dx%0d (%0dx), SPRITES=%0d, 4 frames x %0d pixels vs reference, %0d line renders, max %0d cycles, VBLANK/RASTER/COMMIT_DONE, poisoned banks and system-only reset",
            VIC,H_ACTIVE,V_ACTIVE,SCALE,SPRITES,H_ACTIVE*V_ACTIVE,renders,max_cycles);
        $finish;
    end
    initial begin #300000000; $fatal(1,"vdp frame timeout"); end
    always @(negedge pix)
        if(!pix_reset && !dut.display.memory_up_sync[1] && rgb!==0)
            $fatal(1,"nonblack output before memory ready");
endmodule
