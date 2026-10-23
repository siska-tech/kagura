// SPDX-License-Identifier: Apache-2.0
// Based on hdl-util/hdmi src/tmds_channel.sv by Sameer Puri
// (https://github.com/sameer), revision 83b1c9543a91b776671a44e68e130f81cae437b7.
// Modified for KAGURA-9: prefix XOR and a three-stage pipeline.
// Apache-2.0 option; see third_party/hdl-util-hdmi/LICENSE-APACHE.
// Pipelined replacement for hdl-util tmds_channel (HDMI 1.4a 5.4 encoding,
// 5.2.2.1 / 5.2.3.3 guard bands) with the same ports and output sequence,
// two pixel clocks later (3-cycle latency instead of 1). Needed at 74.25MHz:
// the upstream single-cycle 8b/10b path does not fit GW1NR-9.
//   1: transition minimisation. XNOR stage k equals the XOR prefix with odd
//      bits inverted, so q_m is a prefix XOR, not a serial chain.
//   2: ones count of q_m[7:0].
//   3: DC balance against the running disparity, mode select.
// All inputs travel through the same stages, so every lane keeps the same
// latency and the sync/guard/island timing is unchanged relative to video.
module kagura_tmds_channel #(
    parameter int CN = 0
) (
    input logic clk_pixel,
    input logic [7:0] video_data,
    input logic [3:0] data_island_data,
    input logic [1:0] control_data,
    input logic [2:0] mode,  // 0 control, 1 video, 2 video guard, 3 island, 4 island guard
    output logic [9:0] tmds = 10'b1101010100
);
    // Stage 1
    logic [3:0] n1d;
    logic [7:0] prefix;
    logic use_xnor;
    always_comb begin
        n1d = 4'(video_data[0]) + 4'(video_data[1]) + 4'(video_data[2]) + 4'(video_data[3])
            + 4'(video_data[4]) + 4'(video_data[5]) + 4'(video_data[6]) + 4'(video_data[7]);
        use_xnor = n1d > 4'd4 || (n1d == 4'd4 && video_data[0] == 1'b0);
        for (int k = 0; k < 8; k++) prefix[k] = ^(video_data & (8'hff >> (7 - k)));
    end
    logic [8:0] qm1 = 9'd0;
    logic [2:0] mode1 = 3'd0, mode2 = 3'd0;
    logic [1:0] ctrl1 = 2'd0, ctrl2 = 2'd0;
    logic [3:0] island1 = 4'd0, island2 = 4'd0;
    always_ff @(posedge clk_pixel) begin
        qm1 <= {~use_xnor, prefix ^ (use_xnor ? 8'b10101010 : 8'b00000000)};
        mode1 <= mode; ctrl1 <= control_data; island1 <= data_island_data;
    end
    // Stage 2
    logic [8:0] qm2 = 9'd0;
    logic signed [4:0] n1q2 = 5'sd0;
    always_ff @(posedge clk_pixel) begin
        qm2 <= qm1;
        n1q2 <= 5'(qm1[0]) + 5'(qm1[1]) + 5'(qm1[2]) + 5'(qm1[3]) + 5'(qm1[4]) + 5'(qm1[5]) + 5'(qm1[6]) + 5'(qm1[7]);
        mode2 <= mode1; ctrl2 <= ctrl1; island2 <= island1;
    end
    // Stage 3: Figure 5-7 with the same variable roles as upstream.
    logic signed [4:0] acc = 5'sd0;
    logic signed [4:0] n0q2, acc_add;
    logic [9:0] video_coding;
    always_comb begin
        n0q2 = 5'sd8 - n1q2;
        if (acc == 5'sd0 || n1q2 == n0q2) begin
            if (qm2[8]) begin
                acc_add = n1q2 - n0q2;
                video_coding = {~qm2[8], qm2[8], qm2[7:0]};
            end else begin
                acc_add = n0q2 - n1q2;
                video_coding = {~qm2[8], qm2[8], ~qm2[7:0]};
            end
        end else if ((acc > 5'sd0 && n1q2 > n0q2) || (acc < 5'sd0 && n1q2 < n0q2)) begin
            video_coding = {1'b1, qm2[8], ~qm2[7:0]};
            acc_add = (n0q2 - n1q2) + (qm2[8] ? 5'sd2 : 5'sd0);
        end else begin
            video_coding = {1'b0, qm2[8], qm2[7:0]};
            acc_add = (n1q2 - n0q2) - (~qm2[8] ? 5'sd2 : 5'sd0);
        end
    end
    always_ff @(posedge clk_pixel) acc <= mode2 != 3'd1 ? 5'sd0 : acc + acc_add;

    logic [9:0] control_coding, terc4_coding, video_guard_band, data_guard_band;
    always_comb begin
        case (ctrl2)
            2'b00: control_coding = 10'b1101010100;
            2'b01: control_coding = 10'b0010101011;
            2'b10: control_coding = 10'b0101010100;
            default: control_coding = 10'b1010101011;
        endcase
        case (island2)
            4'b0000: terc4_coding = 10'b1010011100;
            4'b0001: terc4_coding = 10'b1001100011;
            4'b0010: terc4_coding = 10'b1011100100;
            4'b0011: terc4_coding = 10'b1011100010;
            4'b0100: terc4_coding = 10'b0101110001;
            4'b0101: terc4_coding = 10'b0100011110;
            4'b0110: terc4_coding = 10'b0110001110;
            4'b0111: terc4_coding = 10'b0100111100;
            4'b1000: terc4_coding = 10'b1011001100;
            4'b1001: terc4_coding = 10'b0100111001;
            4'b1010: terc4_coding = 10'b0110011100;
            4'b1011: terc4_coding = 10'b1011000110;
            4'b1100: terc4_coding = 10'b1010001110;
            4'b1101: terc4_coding = 10'b1001110001;
            4'b1110: terc4_coding = 10'b0101100011;
            default: terc4_coding = 10'b1011000011;
        endcase
        video_guard_band = (CN == 0 || CN == 2) ? 10'b1011001100 : 10'b0100110011;
        if (CN == 1 || CN == 2) data_guard_band = 10'b0100110011;
        else case (ctrl2)
            2'b00: data_guard_band = 10'b1010001110;
            2'b01: data_guard_band = 10'b1001110001;
            2'b10: data_guard_band = 10'b0101100011;
            default: data_guard_band = 10'b1011000011;
        endcase
    end
    // Upstream holds the previous symbol for undefined modes 5..7.
    always_ff @(posedge clk_pixel)
        case (mode2)
            3'd0: tmds <= control_coding;
            3'd1: tmds <= video_coding;
            3'd2: tmds <= video_guard_band;
            3'd3: tmds <= terc4_coding;
            3'd4: tmds <= data_guard_band;
            default: ;
        endcase
endmodule
