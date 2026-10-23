// SPDX-License-Identifier: Apache-2.0
// 54MHz -> 48kHz strobe, 1kHz left / 500Hz right, -18dBFS.
module kagura_test_tone (
    input wire clk_system, input wire reset,
    output reg sample_valid,
    output reg signed [15:0] sample_left, sample_right
);
    reg [10:0] divider;
    reg [6:0] phase;
    always @(posedge clk_system) begin
        if (reset) begin
            divider <= 0; phase <= 0; sample_valid <= 0;
            sample_left <= 0; sample_right <= 0;
        end else begin
            sample_valid <= 0;
            if (divider == 1124) begin
                divider <= 0;
                sample_valid <= 1;
                sample_left <= (phase % 48 < 24) ? 16'sd4096 : -16'sd4096;
                sample_right <= (phase < 48) ? 16'sd4096 : -16'sd4096;
                phase <= phase == 95 ? 7'd0 : phase + 7'd1;
            end else divider <= divider + 11'd1;
        end
    end
endmodule
