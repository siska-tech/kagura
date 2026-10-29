// SPDX-License-Identifier: Apache-2.0
// Whole-line sprite pass. Hold RAM ownership until both scanning and the last
// row composite finish; selector completion alone can precede the last row.
module kagura_sprite_renderer #(
    parameter integer SPRITES=256
) (
    input wire clk, reset, start,
    input wire [7:0] line,
    output reg render_hold,
    input wire render_grant,
    output wire oam_read,
    output wire [$clog2(SPRITES)+2:0] oam_index,
    input wire [15:0] oam_data,
    output wire pattern_read,
    output wire [15:0] pattern_addr,
    input wire [7:0] pattern_data,
    output wire palette_read,
    output wire [9:0] palette_index,
    input wire [15:0] palette_data,
    output wire line_read,line_write,
    output wire [8:0] line_addr,
    output wire [15:0] line_data,
    input wire [15:0] line_rdata,
    output reg done,
    output wire overflow,
    output wire [$clog2(SPRITES)-1:0] overflow_index,
    output wire [7:0] overflow_line
);
    wire valid,ready,scan_done,row_busy;
    wire [63:0] entry;
    wire [3:0] row;
    reg scan_finished;
    kagura_sprite_selector #(.SPRITES(SPRITES)) select_line(.clk(clk),.reset(reset),.start(start),.line(line),.sprite_enable(1'b1),
        .render_hold(),.render_grant(render_grant),.oam_read(oam_read),.oam_index(oam_index),.oam_data(oam_data),
        .selected_valid(valid),.selected_ready(ready),.selected_entry(entry),.selected_index(),.selected_row(row),
        .selected_count(),.overflow(overflow),.overflow_index(overflow_index),.overflow_line(overflow_line),.done(scan_done),.cycles());
    kagura_sprite_row composite(.clk(clk),.reset(reset),.render_grant(render_grant),
        .selected_valid(valid),.selected_ready(ready),.selected_entry(entry),.selected_row(row),.busy(row_busy),
        .pattern_read(pattern_read),.pattern_addr(pattern_addr),.pattern_data(pattern_data),
        .palette_read(palette_read),.palette_index(palette_index),.palette_data(palette_data),
        .line_read(line_read),.line_write(line_write),.line_addr(line_addr),.line_data(line_data),.line_rdata(line_rdata),.done(),.cycles());
    always @(posedge clk)
        if(reset) begin render_hold<=0; scan_finished<=0; done<=0; end
        else begin
            done<=0;
            if(start) begin render_hold<=1; scan_finished<=0; end
            else if(render_hold) begin
                if(scan_done) scan_finished<=1;
                if(scan_finished && !row_busy && !valid) begin render_hold<=0; done<=1; end
            end
        end
endmodule
