// SPDX-License-Identifier: Apache-2.0
// Colour bars (8 columns) with a one physical pixel white border; VIC1
// 640x480 by default, VIC4 1280x720 with XW=11.
// Purely combinational so it can follow any coordinate source.
module kagura_bar_pattern #(
    parameter integer XW=10,
    parameter integer H_ACTIVE=640,
    parameter integer V_ACTIVE=480
) (
    input wire [XW-1:0] x, input wire [9:0] y,
    output reg [23:0] rgb
);
    wire de = x < H_ACTIVE && y < V_ACTIVE;
    always @* begin
        rgb = 0;
        if (de) begin
            case (x / (H_ACTIVE / 8))
                0: rgb = 24'hffffff;
                1: rgb = 24'hffff00;
                2: rgb = 24'h00ffff;
                3: rgb = 24'h00ff00;
                4: rgb = 24'hff00ff;
                5: rgb = 24'hff0000;
                6: rgb = 24'h0000ff;
                7: rgb = 24'h000000;
            endcase
            // One physical pixel border catches crop/offset errors.
            if (x == 0 || x == H_ACTIVE-1 || y == 0 || y == V_ACTIVE-1)
                rgb = 24'hffffff;
        end
    end
endmodule
