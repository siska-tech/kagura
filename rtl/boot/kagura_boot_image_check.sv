// SPDX-License-Identifier: Apache-2.0
// Streaming validator for the ROM-less boot image format documented in
// docs/romless-boot-feasibility.md section 9.  Feed the 32-byte header followed
// immediately by its payload.  No payload storage is required.
module kagura_boot_image_check (
    input wire clk,
    input wire reset,
    input wire start,
    input wire in_valid,
    output wire in_ready,
    input wire [7:0] in_data,
    output reg done,
    output reg accepted,
    output reg [3:0] error_code,
    output reg [15:0] load_addr,
    output reg [15:0] entry_addr,
    output reg [31:0] payload_length,
    output reg [31:0] payload_crc32
);
    localparam [2:0] IDLE=0, HEADER=1, VALIDATE=2, PAYLOAD=3, FINISH=4;
    localparam [3:0] ERR_NONE=0, ERR_MAGIC=1, ERR_FORMAT=2,
        ERR_RESERVED=3, ERR_HEADER_CRC=4, ERR_RANGE=5,
        ERR_ENTRY=6, ERR_PAYLOAD_CRC=7;
    reg [2:0] state;
    reg [4:0] header_index;
    reg bad_magic,bad_format,bad_reserved;
    reg [31:0] stored_header_crc;
    reg [31:0] crc;
    reg [31:0] payload_index;

    function automatic [31:0] crc32_byte(input [31:0] current,input [7:0] value);
        reg [31:0] c;
        integer bit_index;
        begin
            c=current;
            for(bit_index=0;bit_index<8;bit_index=bit_index+1) begin
                if(c[0]^value[bit_index]) c=(c>>1)^32'hedb88320;
                else c=c>>1;
            end
            crc32_byte=c;
        end
    endfunction

    wire [16:0] range_end={1'b0,load_addr}+payload_length[16:0];
    wire range_low=(load_addr>=16'h0200 && range_end<=17'h09f00);
    wire range_high=(load_addr>=16'ha000 && range_end<=17'h0ff00);
    assign in_ready=(state==HEADER || state==PAYLOAD);

    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE; header_index<=0; crc<=32'hffffffff; payload_index<=0;
            done<=0; accepted<=0; error_code<=ERR_NONE;
            load_addr<=0; entry_addr<=0; payload_length<=0; payload_crc32<=0;
            bad_magic<=0; bad_format<=0; bad_reserved<=0; stored_header_crc<=0;
        end else begin
            done<=0;
            case(state)
                IDLE: if(start) begin
                    header_index<=0; crc<=32'hffffffff; payload_index<=0;
                    accepted<=0; error_code<=ERR_NONE; state<=HEADER;
                    bad_magic<=0; bad_format<=0; bad_reserved<=0; stored_header_crc<=0;
                    load_addr<=0; entry_addr<=0; payload_length<=0; payload_crc32<=0;
                end
                HEADER: if(in_valid) begin
                    if(header_index<28) crc<=crc32_byte(crc,in_data);
                    case(header_index)
                        0: if(in_data!=8'h4b) bad_magic<=1;
                        1: if(in_data!=8'h39) bad_magic<=1;
                        2: if(in_data!=8'h42) bad_magic<=1;
                        3: if(in_data!=8'h54) bad_magic<=1;
                        4: if(in_data!=1) bad_format<=1;
                        5: if(in_data!=32) bad_format<=1;
                        6: if(in_data!=0) bad_format<=1;
                        7: if(in_data!=1) bad_format<=1;
                        20,21,22,23,24,25,26,27: if(in_data!=0) bad_reserved<=1;
                        28: stored_header_crc[7:0]<=in_data;
                        29: stored_header_crc[15:8]<=in_data;
                        30: stored_header_crc[23:16]<=in_data;
                        31: stored_header_crc[31:24]<=in_data;
                        default: ;
                    endcase
                    if(header_index==8) load_addr[7:0]<=in_data;
                    if(header_index==9) load_addr[15:8]<=in_data;
                    if(header_index==10) entry_addr[7:0]<=in_data;
                    if(header_index==11) entry_addr[15:8]<=in_data;
                    if(header_index>=12 && header_index<=15)
                        payload_length<={in_data,payload_length[31:8]};
                    if(header_index>=16 && header_index<=19)
                        payload_crc32<={in_data,payload_crc32[31:8]};
                    if(header_index==31) state<=VALIDATE;
                    else header_index<=header_index+1'b1;
                end
                VALIDATE: begin
                    if(bad_magic) begin
                        error_code<=ERR_MAGIC; state<=FINISH;
                    end else if(bad_format) begin
                        error_code<=ERR_FORMAT; state<=FINISH;
                    end else if(bad_reserved) begin
                        error_code<=ERR_RESERVED; state<=FINISH;
                    end else if((~crc)!=stored_header_crc) begin
                        error_code<=ERR_HEADER_CRC; state<=FINISH;
                    end else if(load_addr[7:0]!=0 || payload_length[7:0]!=0 ||
                                payload_length<256 || payload_length>32'h00009d00 ||
                                payload_length[31:17]!=0 || !(range_low || range_high)) begin
                        error_code<=ERR_RANGE; state<=FINISH;
                    end else if(entry_addr<load_addr || {1'b0,entry_addr}>=range_end) begin
                        error_code<=ERR_ENTRY; state<=FINISH;
                    end else begin
                        crc<=32'hffffffff; payload_index<=0; state<=PAYLOAD;
                    end
                end
                PAYLOAD: if(in_valid) begin
                    if(payload_index+1'b1==payload_length) begin
                        if((~crc32_byte(crc,in_data))==payload_crc32) begin
                            accepted<=1; error_code<=ERR_NONE;
                        end else error_code<=ERR_PAYLOAD_CRC;
                        state<=FINISH;
                    end else begin
                        crc<=crc32_byte(crc,in_data);
                        payload_index<=payload_index+1'b1;
                    end
                end
                FINISH: begin done<=1; state<=IDLE; end
                default: begin error_code<=ERR_FORMAT; state<=FINISH; end
            endcase
        end
    end
endmodule
