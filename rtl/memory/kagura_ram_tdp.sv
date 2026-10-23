// SPDX-License-Identifier: Apache-2.0
// Dual-clock RAM for the line banks: port A reads and writes (system), port B
// reads (pixel). Port A needs read and write while port B reads on another
// clock, so this needs the true dual-port BSRAM mode. Registered reads with
// one edge latency. Port A keeps its previous rdata during a write (normal
// mode): GW1NR-9C DPB rejects read-before-write (PA2122).
//
// Callers must never let port B read an address while port A writes it; the
// line-bank ownership protocol guarantees this. Simulation builds count any
// A-write/B-read pair on the same address closer than COLLISION_NS.
module kagura_ram_tdp #(
    parameter integer DEPTH=1024,
    parameter integer WIDTH=16,
    parameter real COLLISION_NS=5.0,
    parameter bit FATAL_ON_COLLISION=1
) (
    input wire clk_a, enable_a, write_a,
    input wire [$clog2(DEPTH)-1:0] addr_a,
    input wire [WIDTH-1:0] wdata_a,
    output reg [WIDTH-1:0] rdata_a,
    input wire clk_b, enable_b,
    input wire [$clog2(DEPTH)-1:0] addr_b,
    output reg [WIDTH-1:0] rdata_b
);
    reg [WIDTH-1:0] memory [0:DEPTH-1];
    always @(posedge clk_a)
        if(enable_a) begin
            if(write_a) memory[addr_a]<=wdata_a;
            else rdata_a<=memory[addr_a];
        end
    always @(posedge clk_b)
        if(enable_b) rdata_b<=memory[addr_b];
`ifndef SYNTHESIS // Gowin does not define SYNTHESIS; the pragma below hides the checker.
// synthesis translate_off
    integer collisions=0;
    realtime last_write=-1.0e9, last_read=-1.0e9;
    reg [$clog2(DEPTH)-1:0] write_addr_seen, read_addr_seen;
    task automatic report_collision(input integer address);
        begin
            collisions=collisions+1;
            if(FATAL_ON_COLLISION) $fatal(1,"TDP same-address A write/B read at %0d",address);
        end
    endtask
    always @(posedge clk_a)
        if(enable_a && write_a) begin
            if(addr_a==read_addr_seen && $realtime-last_read<COLLISION_NS) report_collision(addr_a);
            last_write=$realtime; write_addr_seen=addr_a;
        end
    always @(posedge clk_b)
        if(enable_b) begin
            if(addr_b==write_addr_seen && $realtime-last_write<COLLISION_NS) report_collision(addr_b);
            last_read=$realtime; read_addr_seen=addr_b;
        end
// synthesis translate_on
`endif
endmodule
