// SPDX-License-Identifier: Apache-2.0
// Based on hdl-util/hdmi src/packet_assembler.sv by Sameer Puri
// (https://github.com/sameer), revision 83b1c9543a91b776671a44e68e130f81cae437b7.
// Modified for KAGURA-9: shift registers and registered counter tests.
// Apache-2.0 option; see third_party/hdl-util-hdmi/LICENSE-APACHE.
// Drop-in for hdl-util packet_assembler (same ports and output sequence) for
// 74.25MHz. Upstream selects the header/subpacket bits for each packet pixel
// with a 32:1 mux on `counter` in front of the BCH update. Here the bits come
// from shift registers loaded at counter 0, and every counter-range test is a
// register set one cycle ahead, so the ECC update starts from registers.
// Precondition (true for kagura_audio_packets, which loads header/sub on the
// packet_enable edge): header/sub only change on the edge into counter 0, and
// stay constant while the packet is sent. tb_packet_assembler checks the
// output against the unchanged upstream module.
module kagura_packet_assembler (
    input logic clk_pixel,
    input logic reset,
    input logic data_island_period,
    input logic [23:0] header,
    input logic [55:0] sub [3:0],
    output logic [8:0] packet_data,
    output logic [4:0] counter = 5'd0
);
    wire [4:0] counter_next=reset ? 5'd0 : data_island_period ? counter+5'd1 : counter;
    always_ff @(posedge clk_pixel) counter<=counter_next;
    // counter==0, >=24 (header parity), >=28 (subpacket parity), ==31.
    logic first=1'b1, tail24=1'b0, tail28=1'b0, last=1'b0;
    always_ff @(posedge clk_pixel) begin
        first<=counter_next==5'd0; tail24<=counter_next>=5'd24;
        tail28<=counter_next>=5'd28; last<=counter_next==5'd31;
    end

    // Remaining bits of the packet in flight: bit 0 (and 1) is the next one.
    logic [53:0] rest [3:0];
    logic [22:0] header_rest;
    logic [7:0] parity [4:0] = '{8'd0, 8'd0, 8'd0, 8'd0, 8'd0};
    logic [3:0] bit_even, bit_odd;
    logic header_bit;
    always_comb begin
        for(int i=0;i<4;i++) begin
            bit_even[i]=first ? sub[i][0] : rest[i][0];
            bit_odd[i]=first ? sub[i][1] : rest[i][1];
        end
        header_bit=first ? header[0] : header_rest[0];
    end
    always_ff @(posedge clk_pixel)
        if(data_island_period) begin
            for(int i=0;i<4;i++) rest[i]<=first ? sub[i][55:2] : rest[i]>>2;
            header_rest<=first ? header[23:1] : header_rest>>1;
        end

    // Data bits, then the parity bytes (BCH blocks 0..3 two bits per pixel).
    logic [3:0] out_even, out_odd;
    always_comb
        for(int i=0;i<4;i++) begin
            out_even[i]=tail28 ? parity[i][{counter[1:0],1'b0}] : bit_even[i];
            out_odd[i]=tail28 ? parity[i][{counter[1:0],1'b1}] : bit_odd[i];
        end
    assign packet_data={out_odd,out_even,tail24 ? parity[4][counter[2:0]] : header_bit};

    // See hdl-util packet_assembler: BCH ECC as a generalized CRC.
    function automatic [7:0] next_ecc(input [7:0] ecc, input next_bch_bit);
        next_ecc=(ecc>>1)^((ecc[0]^next_bch_bit) ? 8'b10000011 : 8'd0);
    endfunction
    always_ff @(posedge clk_pixel)
        if(reset || !data_island_period || last) parity<='{8'd0, 8'd0, 8'd0, 8'd0, 8'd0};
        else begin
            if(!tail28) for(int i=0;i<4;i++) parity[i]<=next_ecc(next_ecc(parity[i],bit_even[i]),bit_odd[i]);
            if(!tail24) parity[4]<=next_ecc(parity[4],header_bit);
        end
endmodule
