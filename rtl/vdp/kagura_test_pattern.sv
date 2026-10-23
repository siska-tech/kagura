// SPDX-License-Identifier: Apache-2.0
// Fixed VIC1 geometry. This is a test source, not an HDMI transmitter.
module kagura_test_pattern (
    input wire clk_pixel, input wire reset,
    output reg [9:0] x, output reg [9:0] y,
    output wire de, output wire hsync_n, output wire vsync_n,
    output wire [23:0] rgb
);
    always @(posedge clk_pixel) begin
        if (reset) begin x <= 0; y <= 0; end
        else if (x == 799) begin
            x <= 0;
            y <= y == 524 ? 10'd0 : y + 10'd1;
        end else x <= x + 10'd1;
    end
    assign de = x < 640 && y < 480;
    assign hsync_n = !(x >= 656 && x < 752);
    assign vsync_n = !(y >= 490 && y < 492);
    kagura_bar_pattern bars(x, y, rgb);
endmodule
