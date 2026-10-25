// SPDX-License-Identifier: Apache-2.0
// Active OAM line selection. Word 1 of each entry (Y and the flags) decides a
// hit, so the scan issues one read per entry back to back. The read word is
// registered, then the hit, then a hit is acted on: the RAM enable/address
// never depend on the comparison in the same cycle. A selected hit drops the
// two reads behind it, fetches words 0 and 2, and rescans from the next entry.
// Without backpressure: SPRITES+3 cycles plus 4 per selected entry. Output
// entries retain the little-endian OAM layout with word 3 as 0. The
// downstream row renderer consumes them in ascending index order. X does not
// affect selection.
module kagura_sprite_selector #(
    parameter integer SPRITES=256       // registered sprites, power of two 64..256
) (
    input wire clk, reset,
    input wire start,
    input wire [7:0] line,
    input wire sprite_enable,
    output reg render_hold,
    input wire render_grant,
    output wire oam_read,
    output wire [$clog2(SPRITES)+2:0] oam_index,
    input wire [15:0] oam_data,
    output reg selected_valid,
    input wire selected_ready,
    output reg [63:0] selected_entry,
    output reg [$clog2(SPRITES)-1:0] selected_index,
    output reg [3:0] selected_row, // row before V flip, 0..15
    output reg [4:0] selected_count,
    output reg overflow,
    output reg [$clog2(SPRITES)-1:0] overflow_index,
    output reg [7:0] overflow_line,
    output reg done,
    output reg [11:0] cycles
);
    localparam integer IW=$clog2(SPRITES);
    localparam [1:0] SCAN=0, FETCH=1, PUBLISH=2;
    reg busy, enabled;
    reg [1:0] state;
    reg [7:0] line_q;
    reg [IW:0] next;                   // next entry to scan; bit IW: past the last
    reg v1, v2, take;                  // word on oam_data / word registered / hit to fetch
    reg [IW-1:0] i1, i2, i3;
    reg [15:0] w2, w3, x_word;
    reg [3:0] row3;
    wire go=busy && render_grant;
    wire out_free=!selected_valid || selected_ready;
    wire scan_read=!next[IW];
    // Active OAM occupies the upper half, four words per sprite.
    assign oam_index=state==SCAN && !take || state==PUBLISH ? {1'b1,next[IW-1:0],2'd1} :
        {1'b1,i3,state==FETCH,1'b0};   // word 0 at the hit, then word 2
    assign oam_read=go && (state==SCAN ? take || scan_read : state==FETCH || out_free && scan_read);
    wire signed [10:0] sprite_y={w2[9],w2[9:0]};
    wire signed [10:0] line_y=$signed({3'b000,line_q});
    wire signed [10:0] height=w2[11] ? 11'sd16 : 11'sd8;
    wire signed [10:0] local_y=line_y-sprite_y;
    wire hit=v2 && enabled && w2[10] && local_y>=0 && local_y<height;

    always @(posedge clk)
        if(reset) begin
            busy<=0; enabled<=0; state<=SCAN; line_q<=0; next<=0; v1<=0; v2<=0; take<=0;
            i1<=0; i2<=0; i3<=0; w2<=0; w3<=0; x_word<=0; row3<=0;
            render_hold<=0; selected_valid<=0; selected_entry<=0;
            selected_index<=0; selected_row<=0; selected_count<=0;
            overflow<=0; overflow_index<=0; overflow_line<=0; done<=0; cycles<=0;
        end else begin
            done<=0;
            if(selected_valid && selected_ready) selected_valid<=0;
            if(start && !busy) begin
                busy<=1; render_hold<=1; enabled<=sprite_enable; line_q<=line;
                state<=SCAN; next<=0; v1<=0; v2<=0; take<=0; selected_valid<=0; selected_count<=0;
                overflow<=0; overflow_index<=0; overflow_line<=0; cycles<=0;
            end else if(busy) begin
                cycles<=cycles+1'b1;
                if(go) case(state)
                    SCAN: if(take) begin
                        // Word 0 is read now; the two reads behind the hit are
                        // dropped and rescanned after it.
                        v1<=0; v2<=0; take<=0; next<={1'b0,i3}+1'b1; state<=FETCH;
                    end else if(!v1 && !v2 && !scan_read) begin
                        // Keep hold until the last output is consumed.
                        if(out_free) begin busy<=0; render_hold<=0; done<=1; end
                    end else begin
                        // The RAM updates after the request edge: oam_data is
                        // the word read on the previous advance.
                        take<=hit && selected_count<5'd16;
                        i3<=i2; w3<=w2; row3<=local_y[3:0];
                        if(hit && selected_count==5'd16 && !overflow) begin
                            overflow<=1; overflow_index<=i2; overflow_line<=line_q;
                        end
                        v2<=v1; i2<=i1; w2<=oam_data;
                        v1<=scan_read; i1<=next[IW-1:0];
                        if(scan_read) next<=next+1'b1;
                    end
                    FETCH: begin x_word<=oam_data; state<=PUBLISH; end
                    default: if(out_free) begin
                        selected_valid<=1; selected_entry<={16'h0000,oam_data,w3,x_word};
                        selected_index<=i3; selected_row<=row3; selected_count<=selected_count+1'b1;
                        v1<=scan_read; i1<=next[IW-1:0];
                        if(scan_read) next<=next+1'b1;
                        state<=SCAN;
                    end
                endcase
            end
        end
endmodule
