// SPDX-License-Identifier: Apache-2.0
// W65C02S-facing endpoint for the temporary $FFE0-$FFFF boot mapping.
// Addresses are the existing five-bit KAGURA request offsets.
module kagura_boot_window (
    input wire clk,
    input wire reset,
    input wire prepare,
    input wire [15:0] load_addr,
    input wire [15:0] entry_addr,
    input wire [31:0] payload_length,
    input wire payload_valid,
    output wire payload_ready,
    input wire [7:0] payload_data,
    input wire req_valid,
    output wire req_ready,
    input wire req_write,
    input wire [4:0] req_addr,
    input wire [7:0] req_wdata,
    output reg rsp_valid,
    input wire rsp_ready,
    output reg [7:0] rsp_rdata,
    output reg rsp_error,
    output reg vector_high_read
);
    reg vector_armed;
    reg [1:0] port_prefix;
    reg [31:0] payload_remaining;
    wire port_read=req_valid && !req_write && req_addr==5'h1a;
    wire port_needs_payload=port_read && vector_armed && port_prefix==2 && payload_remaining!=0;
    assign req_ready=!rsp_valid && (!port_needs_payload || payload_valid);
    wire accept=req_valid && req_ready;
    assign payload_ready=accept && port_needs_payload;

    function automatic [7:0] stub_byte(input [4:0] address);
        begin
            case(address)
                5'h00: stub_byte=8'h64; 5'h01: stub_byte=8'h00;
                5'h02: stub_byte=8'had; 5'h03: stub_byte=8'hfa; 5'h04: stub_byte=8'hff;
                5'h05: stub_byte=8'h85; 5'h06: stub_byte=8'h01;
                5'h07: stub_byte=8'hae; 5'h08: stub_byte=8'hfa; 5'h09: stub_byte=8'hff;
                5'h0a: stub_byte=8'ha0; 5'h0b: stub_byte=8'h00;
                5'h0c: stub_byte=8'had; 5'h0d: stub_byte=8'hfa; 5'h0e: stub_byte=8'hff;
                5'h0f: stub_byte=8'h91; 5'h10: stub_byte=8'h00;
                5'h11: stub_byte=8'hc8;
                5'h12: stub_byte=8'hd0; 5'h13: stub_byte=8'hf8;
                5'h14: stub_byte=8'he6; 5'h15: stub_byte=8'h01;
                5'h16: stub_byte=8'hca;
                5'h17: stub_byte=8'hd0; 5'h18: stub_byte=8'hf3;
                5'h19: stub_byte=8'h00;
                default: stub_byte=8'h00;
            endcase
        end
    endfunction

    always @(posedge clk) begin
        if(reset) begin
            rsp_valid<=0; rsp_rdata<=0; rsp_error<=0; vector_high_read<=0;
            vector_armed<=0; port_prefix<=0; payload_remaining<=payload_length;
        end else begin
            vector_high_read<=0;
            if(prepare) begin
                vector_armed<=0; port_prefix<=0; payload_remaining<=payload_length;
            end
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(accept) begin
                rsp_valid<=1; rsp_error<=req_write;
                if(req_write) rsp_rdata<=0;
                else case(req_addr)
                    5'h1a: begin
                        if(!vector_armed) rsp_rdata<=0;
                        else if(port_prefix==0) begin
                            rsp_rdata<=load_addr[15:8]; port_prefix<=1;
                        end else if(port_prefix==1) begin
                            rsp_rdata<=payload_length[15:8]; port_prefix<=2;
                        end else if(payload_remaining!=0) begin
                            rsp_rdata<=payload_data;
                            payload_remaining<=payload_remaining-1'b1;
                        end else rsp_rdata<=0;
                    end
                    5'h1c: rsp_rdata<=8'he0;
                    5'h1d: begin rsp_rdata<=8'hff; vector_armed<=1; end
                    5'h1e: rsp_rdata<=entry_addr[7:0];
                    5'h1f: begin rsp_rdata<=entry_addr[15:8]; vector_high_read<=1; end
                    default: rsp_rdata<=stub_byte(req_addr);
                endcase
            end
        end
    end

    wire unused_wdata=&{1'b0,req_wdata};
endmodule
