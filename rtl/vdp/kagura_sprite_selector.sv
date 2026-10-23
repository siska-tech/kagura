// SPDX-License-Identifier: Apache-2.0
// Active OAM line selection. Four one-edge-latency word reads, one drain
// edge, one decision per entry: 64*6=384 granted cycles without backpressure.
// Output entries retain the little-endian OAM layout. The downstream row
// renderer consumes them in ascending index order. X does not affect selection.
module kagura_sprite_selector (
    input wire clk, reset,
    input wire start,
    input wire [7:0] line,
    input wire sprite_enable,
    output reg render_hold,
    input wire render_grant,
    output wire oam_read,
    output wire [9:0] oam_index,
    input wire [15:0] oam_data,
    output reg selected_valid,
    input wire selected_ready,
    output reg [63:0] selected_entry,
    output reg [5:0] selected_index,
    output reg [3:0] selected_row, // row before V flip, 0..15
    output reg [4:0] selected_count,
    output reg overflow,
    output reg [5:0] overflow_index,
    output reg [7:0] overflow_line,
    output reg done,
    output reg [11:0] cycles
);
    reg busy, enabled;
    reg [7:0] line_q;
    reg [5:0] index;
    reg [2:0] step;
    reg [63:0] entry;
    // Active OAM occupies words 256..511, four words per sprite.
    assign oam_index={2'b01,index,step[1:0]};
    wire advance=busy && render_grant && (!selected_valid || selected_ready);
    assign oam_read=advance && step<3'd4;
    wire signed [10:0] sprite_y={entry[25],entry[25:24],entry[23:16]};
    wire signed [10:0] line_y=$signed({3'b000,line_q});
    wire signed [10:0] height=entry[49] ? 11'sd16 : 11'sd8;
    wire signed [10:0] local_y=line_y-sprite_y;
    wire hit=enabled && entry[48] && local_y>=0 && local_y<height;

    always @(posedge clk)
        if(reset) begin
            busy<=0; enabled<=0; line_q<=0; index<=0; step<=0; entry<=0;
            render_hold<=0; selected_valid<=0; selected_entry<=0;
            selected_index<=0; selected_row<=0; selected_count<=0;
            overflow<=0; overflow_index<=0; overflow_line<=0; done<=0; cycles<=0;
        end else begin
            done<=0;
            if(selected_valid && selected_ready) selected_valid<=0;
            if(start && !busy) begin
                busy<=1; render_hold<=1; enabled<=sprite_enable; line_q<=line;
                index<=0; step<=0; entry<=0; selected_valid<=0; selected_count<=0;
                overflow<=0; overflow_index<=0; overflow_line<=0; cycles<=0;
            end else if(busy) begin
                cycles<=cycles+1'b1;
                if(advance) begin
                    // The RAM updates after the request edge: collect the
                    // previous word at steps 1..4, then decide at step 5.
                    case(step)
                        3'd1: entry[15:0]<=oam_data;
                        3'd2: entry[31:16]<=oam_data;
                        3'd3: entry[47:32]<=oam_data;
                        3'd4: entry[63:48]<=oam_data;
                        default: ;
                    endcase
                    if(step==3'd5) begin
                        if(hit) begin
                            if(selected_count<5'd16) begin
                                selected_valid<=1; selected_entry<=entry;
                                selected_index<=index; selected_row<=local_y[3:0];
                                selected_count<=selected_count+1'b1;
                            end else if(!overflow) begin
                                overflow<=1; overflow_index<=index; overflow_line<=line_q;
                            end
                        end
                        if(index==6'd63) begin
                            // Keep hold until the last output is consumed.
                            step<=3'd6;
                        end else begin index<=index+1'b1; step<=0; end
                    end else if(step==3'd6) begin
                        busy<=0; render_hold<=0; done<=1;
                    end else step<=step+1'b1;
                end
            end
        end
endmodule
