// SPDX-License-Identifier: Apache-2.0
// W65C02S bus adapter (docs/timing.md). Everything runs on the 54MHz system
// clock; PHI2 is a registered output, never an internal clock. One CPU cycle
// is 16 system cycles (3.375MHz):
//   phase 0  PHI2 falls; read data/OE of the previous cycle still held
//   phase 1  OE released (keeps >=18.5ns of read hold after the fall)
//   phase 3  external IRQ output updated (PHI2 low, outside CPU windows)
//   phase 6  A/CS/RWB sampled; a selected read issues its request at once
//   phase 8  PHI2 rises; a selected read starts driving data
//   phase 10 latest read response (latched into the data output register)
//   phase 13 write data sampled once; the write request issues
//   phase 15 latest write response (checked at the end of phase 15)
// CS low across many system cycles is still one access per CPU cycle.
// RESB release: after `ready`, count RELEASE_CYCLES PHI2 rising edges, then
// release at phase 2 (PHI2 low), so that many complete high pulses ran.
// Any loss of `ready` asserts reset at once.
module kagura_w65c02_adapter #(
    parameter integer RELEASE_CYCLES=8
) (
    input wire clk, reset,
    input wire ready,                  // all domains up, CPU may run
    // CPU pins (registered in/out; tri-state is resolved at the top level)
    output reg phi2,
    output reg cpu_reset_release,      // drives the external RESB gate, high = run
    input wire [4:0] cpu_addr,
    input wire cpu_cs_n, cpu_rwb,
    input wire [7:0] cpu_data_in,
    output reg [7:0] cpu_data_out,
    output reg cpu_data_oe,
    output reg cpu_irq_drive,          // 1 pulls /IRQ low (open drain)
    input wire irq_level,
    // CPU-independent request/response interface (docs/architecture.md)
    output reg req_valid,
    input wire req_ready,
    output reg req_write,
    output reg [4:0] req_addr,
    output reg [7:0] req_wdata,
    input wire rsp_valid,
    output wire rsp_ready,
    input wire [7:0] rsp_rdata,
    input wire rsp_error,
    output reg late                    // sticky: a response missed its phase
);
    reg [3:0] phase;
    reg [4:0] addr_q;
    reg sel_q, read_q, waiting;
    reg [3:0] release_count;
    assign rsp_ready=1'b1;
    always @(posedge clk)
        if(reset) begin
            phase<=0; phi2<=0; cpu_reset_release<=0; release_count<=0;
            cpu_data_out<=0; cpu_data_oe<=0; cpu_irq_drive<=0;
            req_valid<=0; req_write<=0; req_addr<=0; req_wdata<=0;
            addr_q<=0; sel_q<=0; read_q<=0; waiting<=0; late<=0;
        end else begin
            phase<=phase+1'b1;
            // phi2 changes on the edge that starts phase 8 (rise) and 0 (fall).
            if(phase==4'd7) phi2<=1;
            if(phase==4'd15) phi2<=0;
            if(req_valid && req_ready) req_valid<=0;
            if(rsp_valid && waiting) begin
                waiting<=0;
                if(read_q) cpu_data_out<=rsp_rdata;
            end
            // `phase` holds the current phase, so case k acts on the edge that
            // starts phase k+1.
            case(phase)
                4'd0: cpu_data_oe<=0;
                4'd1: if(ready && release_count==RELEASE_CYCLES[3:0]) cpu_reset_release<=1;
                4'd2: cpu_irq_drive<=irq_level;
                4'd5: begin
                    addr_q<=cpu_addr; sel_q<=!cpu_cs_n && cpu_reset_release; read_q<=cpu_rwb;
                    if(!cpu_cs_n && cpu_reset_release && cpu_rwb) begin
                        req_valid<=1; req_write<=0; req_addr<=cpu_addr; waiting<=1;
                    end
                end
                4'd7: begin
                    if(sel_q && read_q) cpu_data_oe<=1;
                    if(ready && release_count!=RELEASE_CYCLES[3:0]) release_count<=release_count+1'b1;
                end
                // A response arriving on the deadline edge itself still counts.
                4'd9: if(waiting && read_q && !rsp_valid) late<=1;
                4'd12: if(sel_q && !read_q) begin
                    req_valid<=1; req_write<=1; req_addr<=addr_q; req_wdata<=cpu_data_in; waiting<=1;
                end
                4'd15: if(waiting && !read_q && !rsp_valid) late<=1;
                default: ;
            endcase
            if(!ready) begin cpu_reset_release<=0; release_count<=0; end
        end
endmodule
