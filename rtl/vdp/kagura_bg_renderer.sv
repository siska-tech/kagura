// SPDX-License-Identifier: Apache-2.0
// Background renderer: one logical line (320 pixels) per `start`, written to
// a line bank as {2'b00, SPR_CLAIMED=0, BG_SOLID, RGB444}
// (docs/architecture.md, docs/memory-access-schedule.md).
// Map 64x32 words: bits 9:0 tile, 13:10 palette, 14 H flip, 15 V flip.
// Pattern: 32 bytes per tile, 4 bytes per row, left pixel in bits 7:4.
// Scroll: X modulo 512, Y modulo 256. Pixel 0 shows BACKDROP and is not solid.
// Active palette words are 256..511 of the palette RAM.
// Two overlapped stages over independent RAMs: fetch (map word + 4 pattern
// bytes, 7 cycles per tile) and emit (8 palette reads/line writes per tile),
// 41 tiles so fine X scroll can drop up to 7 leading pixels.
module kagura_bg_renderer (
    input wire clk, reset,
    input wire start,
    input wire [7:0] line,
    input wire display_enable, bg_enable,
    input wire [8:0] scroll_x,
    input wire [7:0] scroll_y, backdrop,
    output reg render_hold,
    input wire render_grant,
    output wire map_read,
    output wire [10:0] map_index,
    input wire [15:0] map_data,
    output wire pattern_read,
    output wire [14:0] pattern_addr,
    input wire [7:0] pattern_data,
    output wire palette_read,
    output wire [9:0] palette_index,
    input wire [15:0] palette_data,
    output reg line_write,
    output reg [8:0] line_addr,
    output reg [15:0] line_data,
    output reg done,
    output reg [11:0] cycles          // cycles of the last line, start to done
);
    // Line setup latched at start.
    reg [7:0] y;
    reg [5:0] col0;
    reg [2:0] fine;
    reg disp, bg;
    reg [7:0] back;
    reg busy;
    // Fetch stage.
    reg [5:0] fetch_tile;              // 0..41
    reg [2:0] fetch_step;              // 0 map, 1 latch, 2..5 pat0..3, 6 collect
    reg [9:0] tile;
    reg [3:0] pal;
    reg hflip;
    reg [31:0] row;
    wire fetch_active=busy && render_grant && fetch_tile!=6'd41;
    // Emit buffer: one tile, one pixel per granted cycle.
    reg buf_valid;
    reg [31:0] buf_row;
    reg [3:0] buf_pal;
    reg buf_hflip;
    reg [5:0] buf_tile;
    reg [2:0] emit_pixel;
    wire emit=busy && render_grant && buf_valid;
    wire buf_frees=!buf_valid || (emit && emit_pixel==3'd7);
    // The fetch stage hands over a tile on its collect step (6) only when
    // the buffer is free or frees in this very cycle; otherwise it waits.
    wire collect=fetch_active && fetch_step==3'd6;
    wire handover=collect && buf_frees;
    wire fetch_advance=fetch_active && (fetch_step!=3'd6 || buf_frees);

    // Fetch addresses.
    wire [5:0] col=col0+fetch_tile;
    assign map_read=fetch_active && fetch_step==3'd0;
    assign map_index={y[7:3],col};
    wire [2:0] tile_row=y[2:0];
    wire [2:0] row_sel=map_data[15] ? ~tile_row : tile_row;
    reg [2:0] row_q;
    assign pattern_read=fetch_active && fetch_step>=3'd2 && fetch_step<=3'd5;
    assign pattern_addr={tile,row_q,2'(fetch_step-3'd2)};

    // Emit: palette read for the current pixel, line write one edge later.
    wire [2:0] px_index=buf_hflip ? ~emit_pixel : emit_pixel;
    wire [3:0] px=buf_row[31-4*px_index -: 4];
    wire solid=bg && px!=0;
    assign palette_read=emit && disp;
    assign palette_index={2'b01, solid ? {buf_pal,px} : back}; // active half
    // Position in the 328-pixel strip plus 8 minus fine: keeps it unsigned.
    wire [9:0] pos_plus8={1'b0,buf_tile,emit_pixel}+10'd8-{7'b0,fine};
    reg pend_valid, pend_solid;
    reg [9:0] pend_pos;

    always @(posedge clk)
        if(reset) begin
            busy<=0; render_hold<=0; done<=0; cycles<=0; line_write<=0;
            fetch_tile<=0; fetch_step<=0; buf_valid<=0; emit_pixel<=0; pend_valid<=0;
        end else begin
            done<=0; line_write<=0;
            if(start) begin
                busy<=1; render_hold<=1; cycles<=0;
                y<=line+scroll_y; col0<=scroll_x[8:3]; fine<=scroll_x[2:0];
                disp<=display_enable; bg<=bg_enable; back<=backdrop;
                fetch_tile<=0; fetch_step<=0; buf_valid<=0; emit_pixel<=0; pend_valid<=0;
            end else if(busy) begin
                cycles<=cycles+1'b1;
                if(fetch_advance) begin
                    case(fetch_step)
                        3'd1: begin tile<=map_data[9:0]; pal<=map_data[13:10]; hflip<=map_data[14]; row_q<=row_sel; end
                        3'd3: row[31:24]<=pattern_data;
                        3'd4: row[23:16]<=pattern_data;
                        3'd5: row[15:8]<=pattern_data;
                        default: ;
                    endcase
                    if(fetch_step==3'd6) begin fetch_step<=0; fetch_tile<=fetch_tile+1'b1; end
                    else fetch_step<=fetch_step+1'b1;
                end
                if(emit) begin
                    emit_pixel<=emit_pixel+1'b1;
                    if(emit_pixel==3'd7) buf_valid<=0;
                end
                if(handover) begin
                    buf_valid<=1; buf_row<={row[31:8],pattern_data}; buf_pal<=pal; buf_hflip<=hflip;
                    buf_tile<=fetch_tile; emit_pixel<=0;
                end
                pend_valid<=emit; pend_pos<=pos_plus8; pend_solid<=solid;
                if(pend_valid && pend_pos>=10'd8 && pend_pos<10'd328) begin
                    line_write<=1; line_addr<=9'(pend_pos-10'd8);
                    line_data<={3'b000,pend_solid,disp ? palette_data[11:0] : 12'h000};
                end
                if(fetch_tile==6'd41 && !buf_valid && !pend_valid) begin
                    busy<=0; render_hold<=0; done<=1;
                end
            end
        end
endmodule
