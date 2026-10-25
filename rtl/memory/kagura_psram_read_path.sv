// SPDX-License-Identifier: Apache-2.0
// Vendor-neutral read side immediately below the PCM prefetcher and above a
// PSRAM_HS-style 32-bit channel (including kagura_hyperram_ctrl with cmd_reg=0).
// The controller and physical I/O stay outside this module.
module kagura_psram_read_path #(
    parameter integer BYTE_ADDR_WIDTH=24,
    parameter integer CTRL_ADDR_WIDTH=21,
    parameter integer CTRL_ADDR_SHIFT=2,
    parameter         READ_CMD=1'b0
) (
    input  wire sys_clk,
    input  wire sys_reset,
    input  wire sys_req_valid,
    output wire sys_req_ready,
    input  wire [BYTE_ADDR_WIDTH-1:0] sys_req_addr,
    output wire sys_rsp_valid,
    output wire [7:0] sys_rsp_data,
    output wire sys_rsp_error,

    input  wire mem_clk,
    input  wire mem_reset,
    input  wire controller_ready,
    input  wire cache_flush,
    output wire ctrl_cmd,
    output wire ctrl_cmd_en,
    input  wire ctrl_cmd_rdy,
    output wire [CTRL_ADDR_WIDTH-1:0] ctrl_addr,
    input  wire [31:0] ctrl_rd_data,
    input  wire ctrl_rd_data_valid
);
    wire byte_req_valid,byte_req_ready;
    wire [BYTE_ADDR_WIDTH-1:0] byte_req_addr;
    wire byte_rsp_valid,byte_rsp_error;
    wire [7:0] byte_rsp_data;

    kagura_psram_read_cdc #(.ADDR_WIDTH(BYTE_ADDR_WIDTH)) cdc(
        .sys_clk(sys_clk),.sys_reset(sys_reset),.sys_req_valid(sys_req_valid),
        .sys_req_ready(sys_req_ready),.sys_req_addr(sys_req_addr),
        .sys_rsp_valid(sys_rsp_valid),.sys_rsp_data(sys_rsp_data),.sys_rsp_error(sys_rsp_error),
        .mem_clk(mem_clk),.mem_reset(mem_reset),.mem_req_valid(byte_req_valid),
        .mem_req_ready(byte_req_ready),.mem_req_addr(byte_req_addr),
        .mem_rsp_valid(byte_rsp_valid),.mem_rsp_data(byte_rsp_data),.mem_rsp_error(byte_rsp_error));

    kagura_psram_byte_bridge #(
        .BYTE_ADDR_WIDTH(BYTE_ADDR_WIDTH),.CTRL_ADDR_WIDTH(CTRL_ADDR_WIDTH),
        .CTRL_ADDR_SHIFT(CTRL_ADDR_SHIFT),.READ_CMD(READ_CMD)
    ) bridge(
        .clk(mem_clk),.reset(mem_reset),.controller_ready(controller_ready),.cache_flush(cache_flush),
        .req_valid(byte_req_valid),.req_ready(byte_req_ready),.req_addr(byte_req_addr),
        .rsp_valid(byte_rsp_valid),.rsp_data(byte_rsp_data),.rsp_error(byte_rsp_error),
        .ctrl_cmd(ctrl_cmd),.ctrl_cmd_en(ctrl_cmd_en),.ctrl_cmd_rdy(ctrl_cmd_rdy),
        .ctrl_addr(ctrl_addr),.ctrl_rd_data(ctrl_rd_data),.ctrl_rd_data_valid(ctrl_rd_data_valid));
endmodule
