// SPDX-License-Identifier: Apache-2.0
// ROM-less boot orchestration: identify the SPI NOR, validate the image in a
// first pass, then stream it again through the W65C02S boot window.
module kagura_boot_controller #(
    parameter [23:0] IMAGE_OFFSET=24'h100000,
    parameter integer FLASH_CLK_DIV=4
) (
    input wire clk,
    input wire reset,
    output wire flash_cs_n,
    output wire flash_sclk,
    output wire flash_mosi,
    input wire flash_miso,
    output reg boot_ready,
    output reg boot_error,
    output reg [3:0] error_code,
    output reg [23:0] jedec_id,
    output reg unmap_request,
    input wire req_valid,
    output wire req_ready,
    input wire req_write,
    input wire [4:0] req_addr,
    input wire [7:0] req_wdata,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [7:0] rsp_rdata,
    output wire rsp_error
);
    localparam [3:0] ID_CMD=0, ID_DATA=1, HEADER_CMD=2, HEADER_DATA=3,
        HEADER_RESULT=4, PAYLOAD_CMD=5, PAYLOAD_DATA=6, PAYLOAD_RESULT=7,
        TRANSFER_CMD=8, TRANSFER_PREFETCH=9, BOOT=10, ERROR_STATE=11;
    reg [3:0] state;
    reg [1:0] id_index;
    reg checker_start,window_prepare;
    reg check_result_valid,check_result_accepted;
    reg [3:0] check_result_error;

    wire flash_cmd_ready,flash_data_valid,flash_done,flash_error;
    wire [7:0] flash_data;
    wire checker_ready,checker_done,checker_accepted;
    wire [3:0] checker_error;
    wire [15:0] load_addr,entry_addr;
    wire [31:0] payload_length,payload_crc32;
    wire window_payload_ready,vector_high_read;

    wire flash_cmd_valid=(state==ID_CMD || state==HEADER_CMD ||
                          state==PAYLOAD_CMD || state==TRANSFER_CMD);
    wire flash_cmd_jedec=(state==ID_CMD);
    wire [23:0] flash_cmd_addr=(state==HEADER_CMD) ? IMAGE_OFFSET : IMAGE_OFFSET+24'd32;
    wire [23:0] flash_cmd_count=(state==HEADER_CMD) ? 24'd32 : payload_length[23:0];
    wire checking=(state==HEADER_DATA || state==PAYLOAD_DATA);
    wire transferring=(state==TRANSFER_PREFETCH || state==BOOT);
    wire flash_data_ready=(state==ID_DATA) || (checking && checker_ready) ||
                          (transferring && window_payload_ready);

    kagura_flash_reader #(.CLK_DIV(FLASH_CLK_DIV)) reader(
        clk,reset,flash_cmd_valid,flash_cmd_ready,flash_cmd_jedec,
        flash_cmd_addr,flash_cmd_count,flash_data_valid,flash_data_ready,
        flash_data,flash_done,flash_error,flash_cs_n,flash_sclk,flash_mosi,flash_miso);

    kagura_boot_image_check image_check_i(clk,reset,checker_start,
        flash_data_valid && checking,checker_ready,flash_data,
        checker_done,checker_accepted,checker_error,load_addr,entry_addr,
        payload_length,payload_crc32);

    kagura_boot_window window(clk,reset,window_prepare,load_addr,entry_addr,payload_length,
        flash_data_valid && transferring,window_payload_ready,flash_data,
        req_valid,req_ready,req_write,req_addr,req_wdata,
        rsp_valid,rsp_ready,rsp_rdata,rsp_error,vector_high_read);

    always @(posedge clk) begin
        if(reset) begin
            state<=ID_CMD; id_index<=0; jedec_id<=0;
            checker_start<=0; window_prepare<=0;
            boot_ready<=0; boot_error<=0; error_code<=0; unmap_request<=0;
            check_result_valid<=0; check_result_accepted<=0; check_result_error<=0;
        end else begin
            checker_start<=0; window_prepare<=0;
            if(checker_done) begin
                check_result_valid<=1; check_result_accepted<=checker_accepted;
                check_result_error<=checker_error;
            end
            if(vector_high_read) unmap_request<=1;
            case(state)
                ID_CMD: if(flash_cmd_valid && flash_cmd_ready) begin
                    id_index<=0; jedec_id<=0; state<=ID_DATA;
                end
                ID_DATA: begin
                    if(flash_data_valid && flash_data_ready) begin
                        jedec_id<={jedec_id[15:0],flash_data}; id_index<=id_index+1'b1;
                    end
                    if(flash_done) begin
                        if(flash_error || id_index!=3 || jedec_id==24'h000000 || jedec_id==24'hffffff) begin
                            boot_error<=1; error_code<=8; state<=ERROR_STATE;
                        end else begin
                            checker_start<=1; check_result_valid<=0; state<=HEADER_CMD;
                        end
                    end
                end
                HEADER_CMD: if(flash_cmd_valid && flash_cmd_ready) state<=HEADER_DATA;
                HEADER_DATA: if(flash_done) begin
                    if(flash_error) begin boot_error<=1; error_code<=8; state<=ERROR_STATE; end
                    else state<=HEADER_RESULT;
                end
                HEADER_RESULT: begin
                    if(check_result_valid) begin
                        boot_error<=1; error_code<=check_result_error; state<=ERROR_STATE;
                    end else if(checker_ready) state<=PAYLOAD_CMD;
                end
                PAYLOAD_CMD: if(flash_cmd_valid && flash_cmd_ready) state<=PAYLOAD_DATA;
                PAYLOAD_DATA: if(flash_done) begin
                    if(flash_error) begin boot_error<=1; error_code<=8; state<=ERROR_STATE; end
                    else state<=PAYLOAD_RESULT;
                end
                PAYLOAD_RESULT: if(check_result_valid) begin
                    if(check_result_accepted) state<=TRANSFER_CMD;
                    else begin boot_error<=1; error_code<=check_result_error; state<=ERROR_STATE; end
                end
                TRANSFER_CMD: if(flash_cmd_valid && flash_cmd_ready) state<=TRANSFER_PREFETCH;
                TRANSFER_PREFETCH: if(flash_data_valid) begin
                    window_prepare<=1; boot_ready<=1; state<=BOOT;
                end
                BOOT: if(flash_error) begin
                    boot_ready<=0; boot_error<=1; error_code<=8; state<=ERROR_STATE;
                end
                default: state<=ERROR_STATE;
            endcase
        end
    end

    wire unused=&{1'b0,payload_crc32[0]};
endmodule
