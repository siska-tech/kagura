// SPDX-License-Identifier: Apache-2.0
// Synthesis-only resource check for the Gowin PSRAM_HS 2-channel IP.
module kagura_psram_eval_top (
    input  logic        clk,
    input  logic        memory_clk,
    input  logic        rst_n,
    input  logic        pll_lock,
    input  logic        cmd_en,
    input  logic        cmd,
    input  logic [20:0] addr,
    input  logic [31:0] wr_data,
    input  logic [3:0]  data_mask,
    output logic        cmd_rdy,
    output logic [31:0] rd_data,
    output logic        rd_data_valid,
    output logic        init_calib,
    output logic        clk_out,
    output logic [1:0]  O_psram_ck,
    output logic [1:0]  O_psram_ck_n,
    inout  wire  [1:0]  IO_psram_rwds,
    output logic [1:0]  O_psram_reset_n,
    inout  wire  [15:0] IO_psram_dq,
    output logic [1:0]  O_psram_cs_n
);
    logic cmd_rdy0;
    logic cmd_rdy1;
    logic [31:0] rd_data0;
    logic [31:0] rd_data1;
    logic rd_data_valid0;
    logic rd_data_valid1;
    logic init_calib0;
    logic init_calib1;

    kagura_psram_hs u_psram (
        .clk,
        .rst_n,
        .memory_clk,
        .pll_lock,
        .O_psram_ck,
        .O_psram_ck_n,
        .IO_psram_rwds,
        .O_psram_reset_n,
        .IO_psram_dq,
        .O_psram_cs_n,
        .init_calib0,
        .init_calib1,
        .clk_out,
        .cmd0(cmd),
        .cmd1(cmd),
        .cmd_en0(cmd_en),
        .cmd_en1(cmd_en),
        .cmd_rdy0,
        .cmd_rdy1,
        .addr0(addr),
        .addr1(addr),
        .wr_data0(wr_data),
        .wr_data1(wr_data),
        .rd_data0,
        .rd_data1,
        .rd_data_valid0,
        .rd_data_valid1,
        .data_mask0(data_mask),
        .data_mask1(data_mask)
    );

    // Keep both channel datapaths observable in this small evaluation design.
    always_comb begin
        rd_data = rd_data0;
        rd_data_valid = rd_data_valid0;
        if (rd_data_valid1) begin
            rd_data = rd_data1;
            rd_data_valid = 1'b1;
        end
        init_calib = init_calib0 & init_calib1;
        cmd_rdy = cmd_rdy0 & cmd_rdy1;
    end
endmodule
