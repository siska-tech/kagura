// SPDX-License-Identifier: Apache-2.0
// Consume a selected OAM record, fetch its 8/16px pattern row, and composite
// into the owned line bank. Pattern/palette/line reads have one edge latency.
// Entries arrive in ascending OAM order; SPR_CLAIMED preserves that priority,
// including when the winning sprite is hidden behind opaque background.
module kagura_sprite_row (
    input wire clk, reset, render_grant,
    input wire selected_valid,
    output wire selected_ready,
    input wire [63:0] selected_entry,
    input wire [3:0] selected_row,
    output wire busy,
    output wire pattern_read,
    output wire [14:0] pattern_addr,
    input wire [7:0] pattern_data,
    output wire palette_read,
    output wire [9:0] palette_index,
    input wire [15:0] palette_data,
    output wire line_read, line_write,
    output wire [8:0] line_addr,
    output reg [15:0] line_data,
    input wire [15:0] line_rdata,
    output reg done,
    output reg [11:0] cycles
);
    localparam [2:0] IDLE=0,FETCH=1,PIX_READ=2,PIX_WAIT=3,PIX_MERGE=4,PIX_WRITE=5,PIX_NEXT=6,FIRST=7;
    reg [2:0] state;
    reg signed [10:0] x;
    reg [9:0] tile;
    reg [3:0] palette, row_y, pixel;
    reg size16,hflip,behind;
    reg [3:0] fetch_byte;
    reg [63:0] pixels;
    reg write_pixel;
    reg [3:0] colour_q;
    reg [8:0] screen_x_q;
    reg visible_q;
    assign busy=state!=IDLE;
    assign selected_ready=state==IDLE && render_grant;
    wire [3:0] byte_count=size16 ? 4'd8 : 4'd4;
    // 16px tiles are aligned to four at capture, so the row/column offset
    // replaces their low bits without a carry chain before the RAM bank CE.
    wire [9:0] fetch_tile=size16 ? {tile[9:2],row_y[3],fetch_byte[2]} : tile;
    assign pattern_read=state==FETCH && render_grant && fetch_byte<byte_count;
    assign pattern_addr={fetch_tile,row_y[2:0],fetch_byte[1:0]};
    // Prepare the next pixel before PIX_READ, keeping the barrel select and
    // signed clipping arithmetic away from the BSRAM address/enable paths.
    wire [3:0] next_pixel=pixel+1'b1;
    wire [3:0] next_source=hflip ? (size16 ? 4'd15 : 4'd7)-next_pixel : next_pixel;
    wire [3:0] next_colour=pixels[63-4*next_source -: 4];
    wire signed [10:0] next_x=x+$signed({7'b0,next_pixel});
    // The first pixel is judged from the registered row (FIRST), one cycle
    // after the last pattern byte, so the BSRAM output and bank mux only
    // feed the `pixels` capture (timing at 54MHz).
    wire [3:0] first_colour=!hflip ? pixels[63:60] : size16 ? pixels[3:0] : pixels[35:32];
    assign line_addr=screen_x_q;
    assign palette_index={2'b01,palette,colour_q};
    assign line_read=state==PIX_READ && render_grant && visible_q;
    assign palette_read=line_read;
    assign line_write=state==PIX_WRITE && render_grant && write_pixel;
    always @(posedge clk)
        if(reset) begin
            state<=IDLE; x<=0; tile<=0; palette<=0; row_y<=0; pixel<=0;
            size16<=0; hflip<=0; behind<=0; fetch_byte<=0; pixels<=0;
            line_data<=0; write_pixel<=0; done<=0; cycles<=0;
            colour_q<=0; screen_x_q<=0; visible_q<=0;
        end else begin
            done<=0;
            if(state!=IDLE) cycles<=cycles+1'b1;
            if(render_grant) case(state)
                IDLE: if(selected_valid) begin
                    x<={selected_entry[9],selected_entry[9:0]};
                    size16<=selected_entry[27]; hflip<=selected_entry[28]; behind<=selected_entry[30];
                    tile<=selected_entry[27] ? {selected_entry[41:34],2'b00} : selected_entry[41:32];
                    palette<=selected_entry[45:42];
                    row_y<=selected_entry[29] ? (selected_entry[27] ? 4'd15 : 4'd7)-selected_row : selected_row;
                    fetch_byte<=0; pixel<=0; pixels<=0; cycles<=0; state<=FETCH;
                end
                FETCH: begin
                    if(fetch_byte!=0) pixels[63-8*(fetch_byte-1) -: 8]<=pattern_data;
                    if(fetch_byte==byte_count) state<=FIRST;
                    else fetch_byte<=fetch_byte+1'b1;
                end
                FIRST: begin
                    colour_q<=first_colour; screen_x_q<=x[8:0];
                    visible_q<=x>=0 && x<11'sd320 && first_colour!=0;
                    state<=PIX_READ;
                end
                PIX_READ: begin write_pixel<=0; state<=PIX_WAIT; end
                PIX_WAIT: state<=PIX_MERGE;
                PIX_MERGE: begin
                    write_pixel<=visible_q && !line_rdata[13];
                    line_data<={line_rdata[15:14],1'b1,line_rdata[12],
                        behind && line_rdata[12] ? line_rdata[11:0] : palette_data[11:0]};
                    state<=PIX_WRITE;
                end
                PIX_WRITE: state<=PIX_NEXT;
                PIX_NEXT: if(pixel==(size16 ? 4'd15 : 4'd7)) begin state<=IDLE; done<=1; end
                    else begin
                        pixel<=next_pixel; colour_q<=next_colour; screen_x_q<=next_x[8:0];
                        visible_q<=next_x>=0 && next_x<11'sd320 && next_colour!=0;
                        state<=PIX_READ;
                    end
                default: state<=IDLE;
            endcase
        end
endmodule
