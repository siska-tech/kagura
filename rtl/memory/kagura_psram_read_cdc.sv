// SPDX-License-Identifier: Apache-2.0
// One-outstanding read mailbox between the system and PSRAM user clocks.
// Multi-bit payloads remain stable until their synchronized toggle is seen.
module kagura_psram_read_cdc #(
    parameter integer ADDR_WIDTH=24
) (
    input  wire sys_clk,
    input  wire sys_reset,
    input  wire sys_req_valid,
    output wire sys_req_ready,
    input  wire [ADDR_WIDTH-1:0] sys_req_addr,
    output reg  sys_rsp_valid,
    output reg  [7:0] sys_rsp_data,
    output reg  sys_rsp_error,

    input  wire mem_clk,
    input  wire mem_reset,
    output wire mem_req_valid,
    input  wire mem_req_ready,
    output wire [ADDR_WIDTH-1:0] mem_req_addr,
    input  wire mem_rsp_valid,
    input  wire [7:0] mem_rsp_data,
    input  wire mem_rsp_error
);
    reg [ADDR_WIDTH-1:0] req_addr_hold;
    reg req_toggle;
    reg sys_busy;
    reg rsp_seen;
    (* async_reg = "true", syn_preserve = 1 *) reg rsp_sync1,rsp_sync2;

    (* async_reg = "true", syn_preserve = 1 *) reg req_sync1,req_sync2;
    reg req_seen;
    reg mem_waiting;
    reg [7:0] rsp_data_hold;
    reg rsp_error_hold;
    reg rsp_toggle;

    assign sys_req_ready=!sys_busy;
    assign mem_req_valid=(req_sync2!=req_seen) && !mem_waiting;
    assign mem_req_addr=req_addr_hold;

    always @(posedge sys_clk) begin
        if(sys_reset) begin
            req_addr_hold<=0;
            req_toggle<=0;
            sys_busy<=0;
            rsp_sync1<=0;
            rsp_sync2<=0;
            rsp_seen<=0;
            sys_rsp_valid<=0;
            sys_rsp_data<=0;
            sys_rsp_error<=0;
        end else begin
            rsp_sync1<=rsp_toggle;
            rsp_sync2<=rsp_sync1;
            sys_rsp_valid<=0;
            sys_rsp_error<=0;
            if(sys_req_valid && sys_req_ready) begin
                req_addr_hold<=sys_req_addr;
                req_toggle<=~req_toggle;
                sys_busy<=1;
            end
            if(rsp_sync2!=rsp_seen) begin
                rsp_seen<=rsp_sync2;
                sys_busy<=0;
                sys_rsp_valid<=1;
                sys_rsp_data<=rsp_data_hold;
                sys_rsp_error<=rsp_error_hold;
            end
        end
    end

    always @(posedge mem_clk) begin
        if(mem_reset) begin
            req_sync1<=0;
            req_sync2<=0;
            req_seen<=0;
            mem_waiting<=0;
            rsp_data_hold<=0;
            rsp_error_hold<=0;
            rsp_toggle<=0;
        end else begin
            req_sync1<=req_toggle;
            req_sync2<=req_sync1;
            if(mem_req_valid && mem_req_ready) begin
                req_seen<=req_sync2;
                mem_waiting<=1;
            end
            if(mem_rsp_valid && mem_waiting) begin
                mem_waiting<=0;
                rsp_data_hold<=mem_rsp_data;
                rsp_error_hold<=mem_rsp_error;
                rsp_toggle<=~rsp_toggle;
            end
        end
    end

// synthesis translate_off
    always @(posedge mem_clk)
        if(!mem_reset && mem_rsp_valid && !mem_waiting)
            $fatal(1,"PSRAM CDC response without request");
// synthesis translate_on
endmodule
