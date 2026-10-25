// SPDX-License-Identifier: Apache-2.0
// Two requesters on one 1-outstanding PSRAM_HS-style controller
// (kagura_hyperram_ctrl with cmd_reg=0).
//
// p_*: PCM read path (kagura_psram_read_path). It raises p_cmd_en only while
//      p_cmd_rdy is high, as kagura_psram_byte_bridge does.
// h_*: host upload/readback. h_cmd_en is a valid that must not depend on
//      h_cmd_rdy and is held with cmd/addr/data until accepted
//      (h_cmd_en && h_cmd_rdy).
//
// PCM wins by default. When the previous grant went to PCM and the host is
// waiting, the host wins once, so neither side waits more than one command of
// the other. The controller completes a command before it is ready again,
// so a read response always belongs to the last read granted.
module kagura_psram_arbiter #(
    parameter integer ADDR_WIDTH=20
) (
    input  wire clk,
    input  wire reset,

    input  wire p_cmd,
    input  wire p_cmd_en,
    output wire p_cmd_rdy,
    input  wire [ADDR_WIDTH-1:0] p_addr,
    output wire [31:0] p_rd_data,
    output wire p_rd_data_valid,

    input  wire h_cmd,
    input  wire h_cmd_en,
    output wire h_cmd_rdy,
    input  wire [ADDR_WIDTH-1:0] h_addr,
    input  wire [31:0] h_wr_data,
    input  wire [3:0]  h_data_mask,
    output wire [31:0] h_rd_data,
    output wire h_rd_data_valid,

    output wire c_cmd,
    output wire c_cmd_en,
    input  wire c_cmd_rdy,
    output wire [ADDR_WIDTH-1:0] c_addr,
    output wire [31:0] c_wr_data,
    output wire [3:0]  c_data_mask,
    input  wire [31:0] c_rd_data,
    input  wire c_rd_data_valid
);
    reg host_turn,rd_owner_host;
    assign p_cmd_rdy=c_cmd_rdy && !(host_turn && h_cmd_en);
    wire p_fire=p_cmd_en && p_cmd_rdy;
    assign h_cmd_rdy=c_cmd_rdy && !p_fire;
    wire h_fire=h_cmd_en && h_cmd_rdy;

    assign c_cmd_en=p_fire || h_fire;
    assign c_cmd=p_fire ? p_cmd : h_cmd;
    assign c_addr=p_fire ? p_addr : h_addr;
    assign c_wr_data=h_wr_data;
    assign c_data_mask=p_fire ? 4'b0 : h_data_mask;

    assign p_rd_data=c_rd_data;
    assign h_rd_data=c_rd_data;
    assign p_rd_data_valid=c_rd_data_valid && !rd_owner_host;
    assign h_rd_data_valid=c_rd_data_valid && rd_owner_host;

    always @(posedge clk) begin
        if(reset) begin
            host_turn<=0;
            rd_owner_host<=0;
        end else begin
            if(p_fire) host_turn<=1;
            else if(h_fire) host_turn<=0;
            if(p_fire && !p_cmd) rd_owner_host<=0;
            else if(h_fire && !h_cmd) rd_owner_host<=1;
        end
    end
endmodule
