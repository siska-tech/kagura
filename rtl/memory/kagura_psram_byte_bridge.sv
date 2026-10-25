// SPDX-License-Identifier: Apache-2.0
// Adapt the PCM byte-read interface to a Gowin PSRAM_HS-style 32-bit port.
//
// CTRL_ADDR_SHIFT remains configurable until the generated controller's
// address unit is confirmed on hardware. A value of 2 presents word addresses;
// a value of 0 presents an aligned byte address. One returned word is cached,
// so sequential PCM reads normally issue one controller command per four bytes.
module kagura_psram_byte_bridge #(
    parameter integer BYTE_ADDR_WIDTH=24,
    parameter integer CTRL_ADDR_WIDTH=21,
    parameter integer CTRL_ADDR_SHIFT=2,
    parameter         READ_CMD=1'b0
) (
    input  wire clk,
    input  wire reset,
    input  wire controller_ready,
    input  wire cache_flush,      // drop the cached word (memory may have changed)

    input  wire req_valid,
    output wire req_ready,
    input  wire [BYTE_ADDR_WIDTH-1:0] req_addr,
    output reg  rsp_valid,
    output reg  [7:0] rsp_data,
    output reg  rsp_error,

    output wire ctrl_cmd,
    output wire ctrl_cmd_en,
    input  wire ctrl_cmd_rdy,
    output wire [CTRL_ADDR_WIDTH-1:0] ctrl_addr,
    input  wire [31:0] ctrl_rd_data,
    input  wire ctrl_rd_data_valid
);
    reg outstanding;
    reg [1:0] byte_lane;
    reg cache_valid;
    reg [BYTE_ADDR_WIDTH-3:0] cache_tag;
    reg [31:0] cache_data;
    wire [BYTE_ADDR_WIDTH-1:0] aligned_addr={req_addr[BYTE_ADDR_WIDTH-1:2],2'b00};
    wire cache_hit=cache_valid && cache_tag==req_addr[BYTE_ADDR_WIDTH-1:2];

    assign req_ready=controller_ready && !outstanding && (cache_hit || ctrl_cmd_rdy);
    assign ctrl_cmd=READ_CMD;
    assign ctrl_cmd_en=req_valid && req_ready && !cache_hit;
    assign ctrl_addr=CTRL_ADDR_WIDTH'(aligned_addr >> CTRL_ADDR_SHIFT);

    function automatic [7:0] select_byte(input [31:0] word,input [1:0] lane);
        case(lane)
            2'd0: select_byte=word[7:0];
            2'd1: select_byte=word[15:8];
            2'd2: select_byte=word[23:16];
            default: select_byte=word[31:24];
        endcase
    endfunction

    always @(posedge clk) begin
        if(reset) begin
            outstanding<=0;
            byte_lane<=0;
            cache_valid<=0;
            cache_tag<=0;
            cache_data<=0;
            rsp_valid<=0;
            rsp_data<=0;
            rsp_error<=0;
        end else begin
            rsp_valid<=0;
            rsp_error<=0;

            if(!controller_ready || cache_flush) cache_valid<=0;

            if(req_valid && req_ready && cache_hit) begin
                rsp_valid<=1;
                rsp_data<=select_byte(cache_data,req_addr[1:0]);
            end

            if(ctrl_cmd_en) begin
                outstanding<=1;
                byte_lane<=req_addr[1:0];
                cache_tag<=req_addr[BYTE_ADDR_WIDTH-1:2];
            end

            if(ctrl_rd_data_valid && outstanding) begin
                outstanding<=0;
                rsp_valid<=1;
                rsp_data<=select_byte(ctrl_rd_data,byte_lane);
                cache_valid<=controller_ready && !cache_flush;
                cache_data<=ctrl_rd_data;
            end else if(outstanding && !controller_ready) begin
                outstanding<=0;
                cache_valid<=0;
                rsp_valid<=1;
                rsp_data<=0;
                rsp_error<=1;
            end
        end
    end

// synthesis translate_off
    always @(posedge clk) begin
        if(!reset && ctrl_rd_data_valid && !outstanding)
            $fatal(1,"PSRAM response without an outstanding byte read");
    end
// synthesis translate_on
endmodule
