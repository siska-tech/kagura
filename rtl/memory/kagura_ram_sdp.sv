// SPDX-License-Identifier: Apache-2.0
// Simple dual-port RAM: one write port and one read port on independent
// clocks, registered read with one edge latency. No array/read reset.
module kagura_ram_sdp #(
    parameter integer DEPTH=512,
    parameter integer WIDTH=32
) (
    input wire write_clk, write_enable,
    input wire [$clog2(DEPTH)-1:0] write_addr,
    input wire [WIDTH-1:0] write_data,
    input wire read_clk, read_enable,
    input wire [$clog2(DEPTH)-1:0] read_addr,
    output reg [WIDTH-1:0] read_data
);
    reg [WIDTH-1:0] memory [0:DEPTH-1];
    always @(posedge write_clk)
        if(write_enable) memory[write_addr]<=write_data;
    always @(posedge read_clk)
        if(read_enable) read_data<=memory[read_addr];
endmodule
