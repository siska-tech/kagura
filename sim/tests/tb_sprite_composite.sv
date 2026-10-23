`timescale 1ns/1ps
module tb_sprite_composite;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,start=0,grant=1,enable=1;
    reg [7:0] line=0;
    wire hold,oam_read,valid,ready,overflow,scan_done,row_busy,row_done;
    wire [9:0] oam_addr,pal_addr;
    wire [63:0] entry;
    wire [5:0] index,overflow_index;
    wire [3:0] local_row;
    wire [4:0] count;
    wire [7:0] overflow_line;
    wire [11:0] scan_cycles,row_cycles;
    reg [15:0] oam_data,pal_data,line_rd;
    wire pat_read,pal_read,line_read,line_write;
    wire [14:0] pat_addr;
    wire [8:0] line_addr;
    wire [15:0] line_wd;
    reg [7:0] pat_data;
    kagura_sprite_selector selector(clk,reset,start,line,enable,hold,grant,oam_read,oam_addr,oam_data,
        valid,ready,entry,index,local_row,count,overflow,overflow_index,overflow_line,scan_done,scan_cycles);
    kagura_sprite_row renderer(clk,reset,grant,valid,ready,entry,local_row,row_busy,
        pat_read,pat_addr,pat_data,pal_read,pal_addr,pal_data,line_read,line_write,line_addr,line_wd,line_rd,row_done,row_cycles);

    reg [15:0] oam [0:1023], palette [0:511], bank [0:319], reference_line [0:319];
    reg [7:0] pattern [0:32767];
    integer xs[0:63],ys[0:63],tiles[0:63],pals[0:63],flags[0:63];
    integer i,j,tests=0,max_cycles=0,writes=0;
    always @(posedge clk) if(!reset) begin
        if(oam_read) oam_data<=oam[oam_addr];
        if(pat_read) begin
            if(!grant) $fatal(1,"pattern without grant");
            pat_data<=pattern[pat_addr];
        end
        if(pal_read) begin
            if(pal_addr<256 || pal_addr>=512) $fatal(1,"shadow palette read");
            pal_data<=palette[pal_addr];
        end
        if(line_read || line_write) begin
            if(!grant || line_addr>=320) $fatal(1,"line clipping/ownership");
            if(line_read && line_write) $fatal(1,"simultaneous line read/write");
            if(line_read) line_rd<=bank[line_addr];
            if(line_write) begin bank[line_addr]<=line_wd; writes=writes+1; end
        end
    end
    task automatic put(input integer n,x,y,t,p,f);
        reg [63:0] r;
        begin
            xs[n]=x; ys[n]=y; tiles[n]=t; pals[n]=p; flags[n]=f;
            r=0; r[9:0]=10'(x); r[25:16]=10'(y); r[41:32]=10'(t); r[45:42]=4'(p); r[52:48]=5'(f);
            for(integer k=0;k<4;k=k+1) oam[256+n*4+k]=r[k*16 +:16];
        end
    endtask
    task automatic run_line(input integer y,input reg on,input reg stalls);
        integer selected,first_overflow,size,px,py,t,byte_addr,c,n,x,ticks;
        reg finished;
        begin
            for(x=0;x<320;x=x+1) begin
                bank[x]={3'b000,1'(x%3!=0),12'(x*7+23)};
                reference_line[x]=bank[x];
            end
            selected=0; first_overflow=-1;
            // Reference rasterizer, independent of the pipeline and RAM ports.
            for(n=0;n<64;n=n+1) begin
                size=(flags[n]&2)!=0 ? 16 : 8;
                if(on && (flags[n]&1)!=0 && y>=ys[n] && y<ys[n]+size) begin
                    selected=selected+1;
                    if(selected>16) begin if(first_overflow<0) first_overflow=n; end
                    else for(x=0;x<320;x=x+1) begin
                        px=x-xs[n]; py=y-ys[n];
                        if(px>=0 && px<size) begin
                            if((flags[n]&4)!=0) px=size-1-px;
                            if((flags[n]&8)!=0) py=size-1-py;
                            t=size==16 ? (tiles[n]/4)*4+2*(py/8)+px/8 : tiles[n];
                            byte_addr=t*32+(py%8)*4+(px%8)/2;
                            c=px%2==0 ? pattern[byte_addr]/16 : pattern[byte_addr]%16;
                            if(c!=0 && !reference_line[x][13]) begin
                                reference_line[x][13]=1;
                                if((flags[n]&16)==0 || !reference_line[x][12])
                                    reference_line[x][11:0]=palette[256+pals[n]*16+c][11:0];
                            end
                        end
                    end
                end
            end
            @(negedge clk); line=8'(y); enable=on; grant=1; start=1;
            @(negedge clk); start=0; ticks=0; finished=0;
            while(!finished || row_busy || valid) begin
                grant=!stalls || ticks%3!=0;
                @(negedge clk); ticks=ticks+1;
                if(scan_done) finished=1;
                if(ticks>6000) $fatal(1,"compositor timeout");
            end
            if(!stalls && ticks>1936) $fatal(1,"sprite cycle budget %d",ticks);
            if(!stalls && ticks>max_cycles) max_cycles=ticks;
            if(count!=(selected>16 ? 16 : selected) || overflow!=(first_overflow>=0)) $fatal(1,"selection/overflow");
            if(overflow && (overflow_index!=first_overflow || overflow_line!=y)) $fatal(1,"overflow capture");
            for(x=0;x<320;x=x+1)
                if(bank[x]!==reference_line[x]) $fatal(1,"case %d y%0d x%0d got %04h expected %04h",tests,y,x,bank[x],reference_line[x]);
            tests=tests+1; grant=1;
        end
    endtask
    initial begin
        for(i=0;i<32768;i=i+1) pattern[i]={4'((i*7+i/8)%16),4'((i*3+i/32)%16)};
        for(i=0;i<512;i=i+1) palette[i]=i<256 ? 16'hdead : {4'b0,12'((i-256)*13+7)};
        for(i=0;i<1024;i=i+1) oam[i]=16'hffff;
        for(i=0;i<64;i=i+1) put(i,0,511,0,0,0);
        #100; @(negedge clk); reset=0;
        run_line(0,1,0);
        // Every combination of size, flips and behind; odd 16px base tiles
        // must align down. Negative/right-clipped X and negative Y included.
        for(j=0;j<32;j=j+1) begin
            put(0,j%2 ? -5 : 313,-3,1023,j%16,1+j*2);
            run_line(0,1,0); run_line(4,1,1);
            run_line(12,1,0);
        end
        // Winning behind sprite claims pixels even when hidden by background;
        // a later foreground sprite cannot leak through, but transparent can.
        put(0,100,0,0,1,17); put(1,100,0,1,2,1);
        run_line(0,1,0); run_line(0,0,0);
        // Worst-case line selection/rendering: 64 overlaps, only first 16.
        for(i=0;i<64;i=i+1) put(i,100,0,i*4+3,i%16,3 | ((i%8)*4));
        run_line(7,1,0); run_line(8,1,1); run_line(15,1,0);
        // Offscreen early sprites consume all slots, suppressing visible 17th.
        for(i=0;i<16;i=i+1) put(i,-512,0,i,0,3);
        put(16,20,0,0,1,3); run_line(0,1,0);
        // Varied scenes with non-overlap and clipping at all signed extremes.
        for(j=0;j<32;j=j+1) begin
            for(i=0;i<64;i=i+1) put(i,(i*37+j*11)%1024-512,(i*13+j)%280-20,(i*17+j*3)%1024,i%16,(i*7+j)%32);
            run_line(j*7%240,1,j%2);
        end
        // Reset while a row is in flight and grant is removed, then restart.
        for(i=0;i<64;i=i+1) put(i,100,0,i*4,0,3);
        @(negedge clk); line=0; enable=1; grant=1; start=1;
        @(negedge clk); start=0;
        wait(row_busy); @(negedge clk); grant=0; reset=1;
        @(negedge clk);
        if(row_busy || line_write || pat_read || valid || hold) $fatal(1,"reset did not cancel row");
        reset=0; grant=1; run_line(0,1,0);
        $display("PASS: sprite composite %0d lines x320 pixels, %0d writes, max %0d cycles; 8/16px, flips, transparency, priority, behind, signed clipping, overflow and stalls",tests,writes,max_cycles);
        $finish;
    end
    initial begin #20000000; $fatal(1,"timeout"); end
endmodule
