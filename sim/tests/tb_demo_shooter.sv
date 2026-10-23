// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
// kagura_demo_sequencer SCENE=1 AUDIO=1 + kagura_vdp: frames at several
// anim values k are compared pixel by pixel with an independent model of
// the shooter scene (map hash, sprite motion, sine, palette, song-row flap,
// title, enemy wall with optional rotation) including the VDP rule that a
// line shows only the first 16 sprites in OAM order that cross it.
// START=0 checks updates 0,1,2,16,45 (+long adds 100) and requires that
// no frame drops sprites; START>0 begins inside a wall phase, checks four
// consecutive updates and requires the sequencer to report the overflow.
// Tile art comes from sim/tests/demo_art.hex (tools/gen-demo-art.py).
// VIC=4 runs the 16:9 build: 320x180 shown 4x4 on 1280x720, ship at y=136.
module tb_demo_shooter #(parameter integer START=0, parameter integer VIC=1);
    localparam integer H_TOTAL=VIC==4 ? 1650 : 800, V_TOTAL=VIC==4 ? 750 : 525;
    localparam integer H_ACTIVE=VIC==4 ? 1280 : 640, V_ACTIVE=VIC==4 ? 720 : 480;
    localparam integer SCALE=VIC==4 ? 4 : 2, LINES=V_ACTIVE/SCALE, XW=VIC==4 ? 11 : 10;
    localparam integer SHIP_Y=LINES-44;
    reg sys=0, pix=0;
    always #9.261 sys=~sys;
    always #(VIC==4 ? 6.734 : 19.845) pix=~pix;
    reg sys_reset=1, pix_reset=1;
    wire req_valid, req_ready, req_write, rsp_valid, rsp_error, irq, configured, map_bad, data_bad, sprite_overflow;
    wire [4:0] req_addr; wire [7:0] req_wdata, rsp_rdata;
    wire [15:0] frames; wire [11:0] render_cycles;
    reg [XW-1:0] cx=0;
    reg [9:0] cy=0;
    wire [23:0] rgb;
    wire audio_valid;
    wire signed [15:0] audio_l,audio_r;
    kagura_demo_sequencer #(.SPRITES(1),.AUDIO(1),.SCENE(1),.ANIM_START(START),.LINES(LINES)) seq(.clk(sys),.reset(sys_reset),
        .req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),
        .rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.configured(configured),.frames(frames),
        .map_bad(map_bad),.data_bad(data_bad),.sprite_overflow(sprite_overflow),.map_readback(),.map_written());
    kagura_vdp #(.CAPS(VIC==4 ? 8'h33 : 8'h13),.VIDEO_ID_CODE(VIC)) dut(.sys_clk(sys),.sys_reset(sys_reset),
        .audio_full(1'b0),.audio_underflow_toggle(1'b0),.audio_muted(1'b0),
        .audio_sample_valid(audio_valid),.audio_left(audio_l),.audio_right(audio_r),.req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.render_cycles(render_cycles),
        .pix_clk(pix),.pix_reset(pix_reset),.cx(cx),.cy(cy),.rgb(rgb));
    always @(posedge pix)
        if(pix_reset) begin cx<=0; cy<=0; end
        else if(cx==H_TOTAL-1) begin cx<=0; cy<=cy==V_TOTAL-1 ? 10'd0 : cy+1'b1; end
        else cx<=cx+1'b1;

    reg [31:0] art[0:511];
    function automatic integer art_pixel(input integer tile,input integer x,input integer y);
        art_pixel=(art[tile*8+y]>>(28-4*x))&15;
    endfunction
    function automatic integer sine(input integer i);
        integer h, v;
        begin h=i&127; v=(h*(127-h))>>5; sine=(i&128)!=0 ? -v : v; end
    endfunction
    function automatic integer twinkle(input integer p);
        integer t[0:7];
        begin t='{3,6,9,12,15,12,9,6}; twinkle=t[p&7]; end
    endfunction
    function automatic [11:0] rainbow(input integer h);
        reg [11:0] t[0:15];
        begin
            t='{12'hf00,12'hf60,12'hfb0,12'hff0,12'h9f0,12'h3f3,12'h0f8,12'h0ff,
                12'h0af,12'h05f,12'h33f,12'h80f,12'hd0f,12'hf0c,12'hf07,12'hf03};
            rainbow=t[h&15];
        end
    endfunction
    integer k;  // anim value of the update shown in the frame being checked
    integer u;  // updates since configuration (song ticks are u-1)
    function automatic [11:0] colour(input integer p,input integer i);
        integer v6, v7;
        begin
            v6=twinkle(k>>2); v7=twinkle((k>>2)+4);
            colour=0;
            case(p)
                0: case(i)
                    0: colour=12'h002; 3: colour=12'h445; 4: colour=12'h889; 5: colour=12'hfff;
                    6: colour={4'(v6),4'(v6),4'hf}; 7: colour={4'(v7),4'(v7),4'(v7)};
                    8: colour=12'h213; 9: colour=12'h425; 10: colour=12'h637; 11: colour=12'h96a; 12: colour=12'hcad;
                    default: ;
                endcase
                1: case(i)
                    1: colour=12'heef; 2: colour=12'haab; 3: colour=12'h557; 4: colour=12'h4af;
                    5: colour=12'he33; 6: colour=12'hf90; 7: colour=12'hff4; default: ;
                endcase
                2: case(i) 1: colour=12'h7f5; 2: colour=12'h3a3; 3: colour=12'h152; 4: colour=12'hf22; 5: colour=12'hfff; default: ; endcase
                3: case(i) 1: colour=12'hf6c; 2: colour=12'ha38; 3: colour=12'h515; 4: colour=12'hff0; 5: colour=12'hfff; default: ; endcase
                4: case(i) 1: colour=12'hfff; 2: colour=12'h8ff; 3: colour=12'h4af; 4: colour=12'hf84; 5: colour=12'hff8; default: ; endcase
                5: case(i) 1: colour=12'hfc4; 2: colour=12'hc72; 3: colour=12'h630; 4: colour=12'hf22; 5: colour=12'hfff; default: ; endcase
                6: case(i) 1: colour=rainbow(k>>2); 2: colour=12'h225; default: ; endcase
                default: ;
            endcase
        end
    endfunction

    // Sprites of the shown update, in OAM order, and the per-line selection.
    integer spx[0:63], spy[0:63], spt[0:63], spp[0:63], spw[0:63], spe[0:63];
    reg shown[0:239][0:63];
    integer dropped;
    task automatic build_sprites;
        integer n, a, t, q, c, r, l, s1, s2, song_row, phase, m, ly, cnt;
        integer title[0:11];
        begin
            title='{48,49,50,51,52,49,53,54,55,56,57,58};
            song_row=u==0 ? 0 : ((u-1)/7)&127;
            for(n=0;n<64;n=n+1) begin spw[n]=8; spe[n]=1; spp[n]=0; spx[n]=0; spy[n]=0; spt[n]=0; end
            s1=sine((3*k)&255); s2=sine((8*k)&255);
            spx[0]=152+((s1*5)>>>3); spy[0]=SHIP_Y+(s2>>>5); spt[0]=12; spp[0]=1; spw[0]=16;
            spx[1]=156+((s1*5)>>>3); spy[1]=SHIP_Y+15+(s2>>>5); spt[1]=9+((k>>1)&1); spp[1]=1;
            for(n=0;n<4;n=n+1) begin
                a=(k+8*n)&31;
                spx[2+n]=156+((sine(((k-a)*3)&255)*5)>>>3); spy[2+n]=SHIP_Y-4-5*a; spt[2+n]=7; spp[2+n]=4; spe[2+n]=a<=24;
            end
            for(n=0;n<4;n=n+1) begin
                t=(k+32*n)&65535; a=t&127; q=t>>7; c=((q&7)*3+2*n)&7; l=k-a;
                spx[6+n]=72+24*c+((sine(l&255)*3)>>>3); spy[6+n]=74+(sine((4*l+32*c)&255)>>>4)+2*a;
                spt[6+n]=8; spp[6+n]=4;
            end
            for(n=0;n<16;n=n+1) begin
                r=n>>3; c=n&7;
                spx[10+n]=68+24*c+((sine(k&255)*3)>>>3); spy[10+n]=36+24*r+(sine((4*k+32*c)&255)>>>4);
                spt[10+n]=(r!=0 ? 16 : 24)+4*(((song_row>>1)&1)^(c&1)); spp[10+n]=r!=0 ? 2 : 3; spw[10+n]=16;
            end
            for(n=0;n<4;n=n+1) begin
                spx[26+n]=80*n+37; spy[26+n]=((67*n+3*k)&255)-8; spt[26+n]=6;
            end
            for(n=0;n<12;n=n+1) begin
                spx[30+n]=108+8*(n<8 ? n : n+1); spy[30+n]=12; spt[30+n]=title[n]; spp[30+n]=6;
            end
            phase=(k>>8)&3;
            for(n=0;n<22;n=n+1) begin
                m=phase==2 ? (n+(8*k)%22)%22 : n;
                spx[42+n]=5+14*m; spy[42+n]=(k&255)-16; spt[42+n]=16+4*(((song_row>>1)&1)^(m&1));
                spp[42+n]=5; spw[42+n]=16; spe[42+n]=phase==1 || phase==2;
            end
            dropped=0;
            for(ly=0;ly<LINES;ly=ly+1) begin
                cnt=0;
                for(n=0;n<64;n=n+1) begin
                    shown[ly][n]=0;
                    if(spe[n]!=0 && ly>=spy[n] && ly<spy[n]+spw[n]) begin
                        if(cnt<16) shown[ly][n]=1; else dropped=dropped+1;
                        cnt=cnt+1;
                    end
                end
            end
        end
    endtask
    function automatic integer star_tile(input integer h);
        star_tile=h<200 ? 0 : h<220 ? 1 : h<235 ? 2 : h<242 ? 4 : h<248 ? 5 : 3;
    endfunction
    function automatic [23:0] expected(input integer x,input integer y);
        integer lx, ly, py, row, col, tile, h, hf, vf, p, n, xx, yy, done;
        reg [11:0] c;
        begin
            lx=x/SCALE; ly=y/SCALE; py=(ly-k)&255;
            row=py/8; col=lx/8;
            if(row>=6 && row<10 && col>=26 && col<30) begin tile=32+(row-6)*4+(col-26); hf=0; vf=0; end
            else begin h=((row*64+col)*40503)&65535; tile=star_tile(h>>8); vf=(h>>7)&1; hf=(h>>6)&1; end
            p=art_pixel(tile,hf!=0 ? 7-lx%8 : lx%8,vf!=0 ? 7-py%8 : py%8);
            c=colour(0,p);
            done=0;
            for(n=0;n<64;n=n+1) if(done==0 && shown[ly][n]) begin
                xx=lx-spx[n]; yy=ly-spy[n];
                if(xx>=0 && xx<spw[n]) begin
                    p=art_pixel(spt[n]+2*(yy/8)+xx/8,xx%8,yy%8);
                    if(p!=0) begin c=colour(spp[n],p); done=1; end
                end
            end
            expected={c[11:8],c[11:8],c[7:4],c[7:4],c[3:0],c[3:0]};
        end
    endfunction
    integer x, y;
    // Each checked frame is also saved as build/verilator/shooter-<k>.ppm.
    task automatic check_frame;
        integer bad, fd;
        begin
            build_sprites;
            fd=$fopen($sformatf("build/verilator/shooter-%0d.ppm",k),"wb");
            $fwrite(fd,"P6\n%0d %0d\n255\n",H_ACTIVE,V_ACTIVE);
            @(negedge pix); while(!(cx==H_TOTAL-1 && cy==V_TOTAL-1)) @(negedge pix);
            bad=0;
            for(y=0;y<V_ACTIVE;y=y+1) for(x=0;x<H_ACTIVE;x=x+1) begin
                @(negedge pix);
                $fwrite(fd,"%c%c%c",rgb[23:16],rgb[15:8],rgb[7:0]);
                if(rgb!==expected(x,y)) begin
                    if(bad<4) $display("anim %0d pixel %0d,%0d: %06h expected %06h",k,x,y,rgb,expected(x,y));
                    bad=bad+1;
                end
                if(x==H_ACTIVE-1) repeat(H_TOTAL-H_ACTIVE) @(negedge pix);
            end
            $fclose(fd);
            if(bad!=0) $fatal(1,"anim %0d: %0d pixels differ",k,bad);
            $display("anim %0d: %0d pixels match, %0d sprite rows dropped by the line limit",k,H_ACTIVE*V_ACTIVE,dropped);
            if(START==0 && dropped!=0) $fatal(1,"normal scene exceeds 16 sprites/line");
            if(START!=0 && dropped==0) $fatal(1,"wall phase does not exceed the line limit");
        end
    endtask
    // The frame after line V_TOTAL-2 (523 or 748) carries the update committed before it.
    task automatic check_at(input integer at_least);
        begin
            @(negedge pix); while(!(cx==H_TOTAL-1 && cy==V_TOTAL-2 && frames>=at_least)) @(negedge pix);
            u=frames; k=START+u; check_frame;
        end
    endtask

    integer checks;
    initial begin
        $readmemh("sim/tests/demo_art.hex",art);
        #200; sys_reset=0; pix_reset=0;
        wait(configured);
        u=0; k=START; check_frame; checks=1;
        if(START==0) begin
            // Shots in flight and hidden, a flap (song row 2 at u=15), planet
            // rows on screen; +long adds the enemy-shot cycle wrap (k=96+).
            check_at(1); check_at(2); check_at(16); check_at(45); checks=5;
            if($test$plusargs("long")) begin check_at(100); checks=6; end
            if(seq.sprite_overflow) $fatal(1,"sequencer reports overflow in the normal scene");
        end else begin
            check_at(1); check_at(2); check_at(3); checks=4;
            if(!seq.sprite_overflow) $fatal(1,"sequencer did not report the wall overflow");
        end
        if(map_bad || data_bad) $fatal(1,"read-back flags set in scene mode");
        if(dut.core.registers.error_code!==0) $fatal(1,"ERROR_CODE %02h",dut.core.registers.error_code);
        $display("PASS: shooter scene VIC%0d from anim %0d, %0d frames x %0d pixels vs model, %0d updates",VIC,START,checks,H_ACTIVE*V_ACTIVE,frames);
        $finish;
    end
    initial begin repeat(4) #1000000000; $fatal(1,"shooter demo timeout"); end
endmodule
