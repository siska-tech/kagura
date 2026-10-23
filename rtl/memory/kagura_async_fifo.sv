// SPDX-License-Identifier: Apache-2.0
// Common reset asserts asynchronously; release synchronizes in each domain.
// Registered read data is valid one read edge after an accepted pop.
// Generic storage: physical BSRAM mapping must be checked separately.
module kagura_async_fifo #(
    parameter integer WIDTH=32,
    parameter integer ADDR_BITS=4
) (
    input wire reset,
    input wire write_clk, write_enable,
    input wire [WIDTH-1:0] write_data,
    output reg full,
    output reg overflow,
    input wire read_clk, read_enable,
    output reg [WIDTH-1:0] read_data,
    output reg read_valid,
    output reg empty,
    output reg underflow,
    output wire [ADDR_BITS:0] read_level
);
    localparam integer PTR=ADDR_BITS+1;
    reg [WIDTH-1:0] memory [0:(1<<ADDR_BITS)-1];
    reg [PTR-1:0] wb,wg,rb,rg;
    (* ASYNC_REG="TRUE" *) reg [PTR-1:0] rg_sync1,rg_sync2,wg_sync1,wg_sync2;
    (* ASYNC_REG="TRUE" *) reg [1:0] wr_reset,rd_reset;
    always @(posedge write_clk or posedge reset)
        if(reset) wr_reset<=2'b11; else wr_reset<={wr_reset[0],1'b0};
    always @(posedge read_clk or posedge reset)
        if(reset) rd_reset<=2'b11; else rd_reset<={rd_reset[0],1'b0};
    wire push=write_enable && !full;
    wire pop=read_enable && !empty;
    // Both outcomes are prepared from registers and push/pop only selects,
    // keeping the flag update short behind the pop decision (74.25MHz).
    // rg/wg always equal the Gray code of rb/wb.
    wire [PTR-1:0] wb_inc=wb+1'b1, rb_inc=rb+1'b1;
    wire [PTR-1:0] wg_inc=(wb_inc>>1)^wb_inc;
    wire [PTR-1:0] rg_inc=(rb_inc>>1)^rb_inc;
    localparam [PTR-1:0] FULL_MASK={2'b11,{(ADDR_BITS-1){1'b0}}};
    wire [PTR-1:0] full_compare=rg_sync2 ^ FULL_MASK;
    always @(posedge write_clk or posedge wr_reset[1]) begin
        if(wr_reset[1]) begin wb<=0; wg<=0; rg_sync1<=0; rg_sync2<=0; full<=1; overflow<=0; end
        else begin
            rg_sync1<=rg; rg_sync2<=rg_sync1;
            if(push) begin wb<=wb_inc; wg<=wg_inc; end
            full<=push ? wg_inc==full_compare : wg==full_compare;
            if(write_enable && full) overflow<=1;
        end
    end
    // Read-side occupancy from the synchronized write pointer. It lags real
    // writes by the synchronizer delay, so it never over-reports.
    function automatic [PTR-1:0] gray_to_binary(input [PTR-1:0] gray);
        integer k;
        begin
            gray_to_binary[PTR-1]=gray[PTR-1];
            for(k=PTR-2;k>=0;k=k-1) gray_to_binary[k]=gray_to_binary[k+1]^gray[k];
        end
    endfunction
    assign read_level=gray_to_binary(wg_sync2)-rb;
    // Keep array free of reset logic so it remains inferable as RAM.
    always @(posedge write_clk)
        if(!wr_reset[1] && push) memory[wb[ADDR_BITS-1:0]]<=write_data;
    always @(posedge read_clk or posedge rd_reset[1]) begin
        if(rd_reset[1]) begin rb<=0; rg<=0; wg_sync1<=0; wg_sync2<=0; empty<=1; read_valid<=0; read_data<=0; underflow<=0; end
        else begin
            wg_sync1<=wg; wg_sync2<=wg_sync1;
            if(pop) begin rb<=rb_inc; rg<=rg_inc; end
            empty<=pop ? rg_inc==wg_sync2 : rg==wg_sync2;
            read_valid<=pop;
            if(pop) read_data<=memory[rb[ADDR_BITS-1:0]];
            if(read_enable && empty) underflow<=1;
        end
    end
endmodule
