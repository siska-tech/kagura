// SPDX-License-Identifier: Apache-2.0
// Single-port RAM, one clock, registered read (data valid one edge after the
// address). No reset on the array or read register so it maps to BSRAM.
// A write returns the old word on rdata (read-before-write); callers must not
// rely on read-during-write data.
module kagura_ram_sp #(
    parameter integer DEPTH=1024,
    parameter integer WIDTH=16
) (
    input wire clk,
    input wire enable, write,
    input wire [$clog2(DEPTH)-1:0] addr,
    input wire [WIDTH-1:0] wdata,
    output reg [WIDTH-1:0] rdata
);
    reg [WIDTH-1:0] memory [0:DEPTH-1];
    always @(posedge clk)
        if(enable) begin
            if(write) memory[addr]<=wdata;
            rdata<=memory[addr];
        end
endmodule
