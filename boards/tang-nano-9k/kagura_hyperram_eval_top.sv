// SPDX-License-Identifier: Apache-2.0
// Synthesis-only check of kagura_hyperram_ctrl + Gowin PHY on one die of the
// GW1NR-9 in-package PSRAM. The second die is left idle.
module kagura_hyperram_eval_top (
    input  logic        clk,
    input  logic        clk_ck,
    input  logic        rst_n,
    input  logic        cmd_en,
    input  logic        cmd,
    input  logic [19:0] addr,
    input  logic [31:0] wr_data,
    input  logic [3:0]  data_mask,
    output logic        cmd_rdy,
    output logic [31:0] rd_data,
    output logic        rd_data_valid,
    output logic        init_calib,
    output logic [1:0]  O_psram_ck,
    output logic [1:0]  O_psram_ck_n,
    inout  wire  [1:0]  IO_psram_rwds,
    output logic [1:0]  O_psram_reset_n,
    inout  wire  [15:0] IO_psram_dq,
    output logic [1:0]  O_psram_cs_n
);
    logic phy_reset_n,phy_cs_n,phy_ck_en,phy_dq_oe,phy_rwds_oe,phy_rwds_o_rise,phy_rwds_o_fall;
    logic [7:0] o_rise,o_fall,i_rise,i_fall;

    kagura_hyperram_ctrl #(.ADDR_WIDTH(20)) ctrl(
        .clk,.rst_n,.lat_cycles(5'd12),.rd_latency(3'd2),.cmd,.cmd_reg(1'b0),.cmd_en,.cmd_rdy,.addr,.wr_data,.data_mask,.rd_data,
        .rd_data_valid,.init_calib,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall));

    kagura_hyperram_phy_gowin phy(
        .clk,.clk_ck,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall),
        .O_psram_ck(O_psram_ck[0]),.O_psram_ck_n(O_psram_ck_n[0]),
        .O_psram_reset_n(O_psram_reset_n[0]),.O_psram_cs_n(O_psram_cs_n[0]),
        .IO_psram_rwds(IO_psram_rwds[0]),.IO_psram_dq(IO_psram_dq[7:0]));

    assign O_psram_ck[1]=1'b0;
    assign O_psram_ck_n[1]=1'b1;
    assign O_psram_reset_n[1]=1'b0;
    assign O_psram_cs_n[1]=1'b1;
    assign IO_psram_rwds[1]=1'bz;
    assign IO_psram_dq[15:8]=8'bz;
endmodule
