// SPDX-License-Identifier: Apache-2.0
// Raster scroll (docs/raster-scroll.md). Up to 8 entries {line, x, y}, strictly
// ascending by line. An entry applies from its logical line on and stays in
// effect until the next entry; before the first entry and at line 0 without a
// hit the frame SCROLL_X/Y apply. The shadow table is copied on `load`
// (COMMIT completion), so the active table only changes at VBlank.
// Each background line start is delayed by four cycles to resolve the scroll
// in registered stages; a logical line lasts thousands of cycles. Entry layout:
// {y[7:0], x[8:0], line[7:0]}.
module kagura_raster_scroll (
    input wire clk, reset,
    input wire start,                 // renderer start, `line` valid
    input wire [7:0] line,
    input wire [8:0] frame_x,
    input wire [7:0] frame_y,
    input wire load,
    input wire [3:0] count_in,
    input wire [199:0] table_in,
    output wire start_o,
    output reg [8:0] x_o,
    output reg [7:0] y_o
);
    reg [3:0] count;
    reg [199:0] tbl;
    // Next entry to compare and the scroll in effect for the last line.
    reg [3:0] ptr;
    reg [8:0] cur_x;
    reg [7:0] cur_y;
    reg d1, d2, d3;
    reg [7:0] line_q;
    reg [3:0] pe_q;
    reg [8:0] cx_q;
    reg [7:0] cy_q;
    reg [24:0] e_q;
    reg inrange_q;
    assign start_o=d3;
    wire hit=inrange_q && line_q>=e_q[7:0];
    wire [8:0] nx=hit ? e_q[16:8] : cx_q;
    wire [7:0] ny=hit ? e_q[24:17] : cy_q;
    always @(posedge clk)
        if(reset) begin
            count<=0; tbl<=0; ptr<=0; cur_x<=0; cur_y<=0; d1<=0; d2<=0; d3<=0;
            line_q<=0; pe_q<=0; cx_q<=0; cy_q<=0; e_q<=0; inrange_q<=0; x_o<=0; y_o<=0;
        end else begin
            if(load) begin count<=count_in; tbl<=table_in; end
            d1<=start; d2<=d1; d3<=d2;
            if(start) begin
                line_q<=line;
                if(line==0 || count==0) begin pe_q<=0; cx_q<=frame_x; cy_q<=frame_y; end
                else begin pe_q<=ptr; cx_q<=cur_x; cy_q<=cur_y; end
            end
            if(d1) begin
                e_q<=tbl[25*pe_q[2:0] +: 25];
                inrange_q<=pe_q<count;
            end
            if(d2) begin
                x_o<=nx; y_o<=ny; cur_x<=nx; cur_y<=ny;
                ptr<=pe_q+{3'b0,hit};
            end
        end
endmodule
