// SPDX-License-Identifier: Apache-2.0
// 16-bit single-port RAM with atomic CPU byte writes (map, OAM, palette).
// Word read: response one edge after acceptance. Word write: one edge.
// Byte write: read, register the merged word, write back (3 edges). req_ready
// stays low until the write-back edge, so no other access can interleave.
// alt_read is a renderer read port: the caller asserts it only while the
// request side is idle (no req_valid, no RMW in flight); data appears on
// rsp_rdata one edge later, without rsp_valid.
module kagura_ram_rmw16 #(
    parameter integer DEPTH=1024
) (
    input wire clk, reset,
    input wire req_valid,
    output wire req_ready,
    input wire req_write, req_byte, req_high,
    input wire [$clog2(DEPTH)-1:0] req_addr,
    input wire [15:0] req_wdata, // byte writes use bits 7:0
    output reg rsp_valid,
    output wire [15:0] rsp_rdata,
    output wire ready_next,          // req_ready of the next cycle
    input wire alt_read,
    input wire [$clog2(DEPTH)-1:0] alt_addr
);
    localparam [1:0] IDLE=0, MERGE=1, WRITE=2;
    reg [1:0] state;
    reg [$clog2(DEPTH)-1:0] rmw_addr;
    reg [7:0] rmw_byte;
    reg rmw_high;
    reg [15:0] merged;
    wire accept=req_valid && req_ready;
    assign req_ready=state==IDLE;
    assign ready_next=state==WRITE || (state==IDLE && !(accept && req_write && req_byte));
    wire ram_enable=accept || state==WRITE || alt_read;
    wire ram_write=(accept && req_write && !req_byte) || state==WRITE;
    wire [$clog2(DEPTH)-1:0] ram_addr=state==WRITE ? rmw_addr : alt_read ? alt_addr : req_addr;
    wire [15:0] ram_wdata=state==WRITE ? merged : req_wdata;
    kagura_ram_sp #(.DEPTH(DEPTH),.WIDTH(16)) ram(
        .clk(clk),.enable(ram_enable),.write(ram_write),
        .addr(ram_addr),.wdata(ram_wdata),.rdata(rsp_rdata));
// synthesis translate_off
    always @(posedge clk)
        if(!reset && alt_read && (req_valid || state!=IDLE)) $fatal(1,"rmw16 alt_read during a request");
// synthesis translate_on
    always @(posedge clk)
        if(reset) begin state<=IDLE; rsp_valid<=0; end
        else begin
            rsp_valid<=accept && !req_write;
            case(state)
                IDLE: if(accept && req_write && req_byte) begin
                    state<=MERGE; rmw_addr<=req_addr; rmw_byte<=req_wdata[7:0]; rmw_high<=req_high;
                end
                MERGE: begin
                    merged<=rmw_high ? {rmw_byte,rsp_rdata[7:0]} : {rsp_rdata[15:8],rmw_byte};
                    state<=WRITE;
                end
                default: state<=IDLE;
            endcase
        end
endmodule
