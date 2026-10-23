`timescale 1ns/1ps
module tb_sprite_selector;
    reg clk=0;
    always #9.259 clk=~clk;
    reg reset=1,start=0,enable=1,grant=1,ready=1;
    reg [7:0] line=0;
    wire hold,rd,valid,overflow,done;
    wire [9:0] addr;
    reg [15:0] data;
    wire [63:0] selected;
    wire [5:0] index,overflow_index;
    wire [3:0] row;
    wire [4:0] count;
    wire [7:0] overflow_line;
    wire [11:0] cycles;
    kagura_sprite_selector dut(clk,reset,start,line,enable,hold,grant,rd,addr,data,
        valid,ready,selected,index,row,count,overflow,overflow_index,overflow_line,done,cycles);

    reg [15:0] memory [0:1023];
    reg [63:0] records [0:63];
    integer ys [0:63], sizes [0:63];
    reg enabled [0:63];
    integer want_index [0:15],want_row [0:15];
    integer want_count,want_overflow,seen,reads,total_lines=0,total_entries=0;
    integer i,j;
    reg stalled=0;
    reg [73:0] held_output;
    // Independent one-edge RAM model: a disabled read holds its output.
    always @(posedge clk) begin
        if(rd) begin
            if(!hold || !grant || addr<256 || addr>=512) $fatal(1,"bad OAM ownership/address %d",addr);
            data<=memory[addr]; reads=reads+1;
        end
        if(reset) stalled=0;
        else begin
            if(stalled && (!valid || {selected,index,row}!==held_output))
                $fatal(1,"output changed under backpressure");
            stalled=valid && !ready;
            held_output={selected,index,row};
            if(valid && ready) begin
                if(seen>=want_count) $fatal(1,"extra selected sprite");
                if(index!=want_index[seen] || row!=want_row[seen] || selected!==records[want_index[seen]])
                    $fatal(1,"entry %d: index %d row %d expected index %d row %d",seen,index,row,want_index[seen],want_row[seen]);
                seen=seen+1; total_entries=total_entries+1;
            end
        end
    end

    task automatic put(input integer n,x,y,tile,pal,flags);
        reg [63:0] value;
        begin
            value=0;
            value[9:0]=10'(x); value[25:16]=10'(y);
            value[41:32]=10'(tile); value[45:42]=4'(pal); value[52:48]=5'(flags);
            records[n]=value; ys[n]=y; sizes[n]=(flags&2)!=0 ? 16 : 8; enabled[n]=(flags&1)!=0;
            for(integer k=0;k<4;k=k+1) memory[256+4*n+k]=value[16*k +: 16];
        end
    endtask
    task automatic run_line(input integer y,input reg on,input reg stalls);
        integer hit_count,ticks;
        begin
            want_count=0; want_overflow=-1; hit_count=0; seen=0; reads=0;
            for(integer n=0;n<64;n=n+1)
                if(on && enabled[n] && y>=ys[n] && y<=ys[n]+sizes[n]-1) begin
                    if(hit_count<16) begin want_index[hit_count]=n; want_row[hit_count]=y-ys[n]; want_count=want_count+1; end
                    else if(want_overflow<0) want_overflow=n;
                    hit_count=hit_count+1;
                end
            @(negedge clk); line=8'(y); enable=on; start=1; grant=1; ready=1;
            @(negedge clk); start=0; ticks=0;
            while(!done) begin
                if(ticks>2000) $fatal(1,"scan timeout");
                // Grant pauses are independent of downstream backpressure.
                grant=!stalls || ticks%3!=0; ready=!stalls || ticks%4==0;
                @(negedge clk); ticks=ticks+1;
            end
            if(seen!=want_count || count!=want_count || reads!=256) $fatal(1,"count/read mismatch %d/%d, reads %d",seen,want_count,reads);
            if(overflow!=(want_overflow>=0)) $fatal(1,"overflow mismatch");
            if(overflow && (overflow_index!=want_overflow || overflow_line!=y)) $fatal(1,"first overflow mismatch");
            if(!stalls && cycles!=385) $fatal(1,"cycle budget %d",cycles);
            if(hold || valid) $fatal(1,"ownership/output not drained at done");
            grant=1; ready=1; total_lines=total_lines+1;
        end
    endtask

    initial begin
        reads=0; seen=0; want_count=0;
        for(i=0;i<1024;i=i+1) memory[i]=16'hffff; // shadow/unused poison
        for(i=0;i<64;i=i+1) put(i,0,0,0,0,0);
        #100; @(negedge clk); reset=0;
        run_line(0,1,0); // empty
        for(i=0;i<64;i=i+1) put(i,i%2 ? -512 : 511,20,i,15-i%16,31);
        run_line(20,1,0); // all 64 overlap, including completely offscreen X
        run_line(35,1,1); // last row of size16, all flags retained, stalls
        run_line(36,1,0); // exclusive bottom edge
        run_line(20,0,1); // global disable, old overflow must clear
        for(i=0;i<64;i=i+1) put(i,0,511,0,0,1);
        put(0,-1,-7,1023,15,1); put(1,319,-8,1,1,1);
        put(2,320,-15,2,2,3); put(3,-512,-16,3,3,3);
        put(4,511,-512,4,4,3); put(63,0,239,5,5,3);
        run_line(0,1,0); run_line(1,1,1); run_line(239,1,0);
        // Deterministic varied signed positions and flags, across every line.
        for(i=0;i<64;i=i+1) put(i,(i*137)%1024-512,(i*29)%280-20,(i*71)%1024,i%16,(i%5==0 ? 0 : 1) | (i%2)*2 | (i%8)*4);
        for(j=0;j<240;j=j+1) run_line(j,1,j%2);
        // Reset cancels an unconsumed entry and returns ownership.
        for(i=0;i<64;i=i+1) put(i,0,0,0,0,1);
        @(negedge clk); line=0; enable=1; ready=0; start=1;
        @(negedge clk); start=0;
        wait(valid); @(negedge clk); reset=1;
        @(negedge clk); if(valid || hold || done) $fatal(1,"reset did not cancel scan");
        reset=0; ready=1; run_line(0,1,0);
        $display("PASS: sprite selector, %0d lines, %0d entries; signed clipping, 16 limit, overflow, priority, offscreen X, stalls/reset, 385 cycles",total_lines,total_entries);
        $finish;
    end
    initial begin #10000000; $fatal(1,"timeout"); end
endmodule
