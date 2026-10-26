// SPDX-License-Identifier: Apache-2.0
// Line bank handover and scan-out (docs/memory-access-schedule.md):
// - At physical y=SCALE*n, x=0 the pixel side requests logical line n+1 into
//   the bank it is not displaying (line 0 at y=V_TOTAL-3). The payload {line, bank} is
//   held until the next request; a toggle carries it to the system domain.
// - The renderer writes that bank and returns a done toggle with the line tag.
// - Two pixels ahead of the first pixel of logical line m, the pixel side
//   switches to the requested bank only if the done tag equals m. Otherwise
//   all SCALE copies of line m are black and LINE_UNDERRUN is raised (not before
//   the first successful handover). Stale done tags are ignored.
// Each logical pixel is shown SCALExSCALE; RGB444 is widened by nibble
// duplication. VIDEO_ID_CODE 1: 640x480 in 800x525, SCALE 2, 240 lines;
// 4: 1280x720 in 1650x750, SCALE 4, 180 lines (docs/video.md).
// The system side never writes the displayed bank and the pixel side never
// reads the requested one, so the dual-clock banks never collide.
module kagura_line_display #(
    parameter integer VIDEO_ID_CODE=1,
    localparam integer XW=VIDEO_ID_CODE==4 ? 11 : 10
) (
    // system domain
    input wire sys_clk, sys_reset,
    input wire memory_ready,
    output reg line_init_done,
    output reg frame_ready,           // first line 0 prepared, system domain
    output reg render_start,           // pulse with render_line, render bank latched inside
    output reg [7:0] render_line,
    input wire line_write,
    input wire [8:0] line_addr,
    input wire [15:0] line_data,
    input wire line_read,
    output wire [15:0] line_rdata,
    input wire render_done,
    output reg vblank_start,           // pulse at physical y=V_ACTIVE, x=0
    output wire vblank_live,
    output reg underrun_event,         // pulse
    output reg line_start,             // pulse when logical line `shown_line` starts
    output reg [7:0] shown_line,
    // pixel domain
    input wire pix_clk, pix_reset,
    input wire [XW-1:0] cx,
    input wire [9:0] cy,
    output reg [23:0] rgb
);
    // ---------------- pixel domain ----------------
    localparam integer H_TOTAL=VIDEO_ID_CODE==4 ? 1650 : 800;
    localparam integer V_TOTAL=VIDEO_ID_CODE==4 ? 750 : 525;
    localparam integer H_ACTIVE=VIDEO_ID_CODE==4 ? 1280 : 640;
    localparam integer V_ACTIVE=VIDEO_ID_CODE==4 ? 720 : 480;
    localparam integer SHIFT=VIDEO_ID_CODE==4 ? 2 : 1;
    localparam integer SCALE=1<<SHIFT;
    localparam integer LINES=V_ACTIVE>>SHIFT;
    // Line 0 is requested three physical lines before the frame starts.
    localparam integer LINE0_Y=V_TOTAL-3;
    // Scan decisions are made for the position two pixel clocks ahead
    // (scan-out latency). They are registered one clock earlier from the
    // position three ahead (cx advances by one per clock), so no adder or
    // compare on cx/cy feeds the line RAM enable at 74.25MHz.
    wire [XW-1:0] ax3=cx>=XW'(H_TOTAL-3) ? cx-XW'(H_TOTAL-3) : cx+XW'(3);
    // cy is constant over a physical line, so the vertical terms of the scan
    // decisions are registered from cy alone. nxt_* describe the next line
    // (valid from the second clock of a line); cur_* take over from them on the
    // last clock, so they are valid for the whole of the line they describe.
    wire [9:0] cy_next=cy==10'(V_TOTAL-1) ? 10'd0 : cy+10'd1;
    reg nxt_active, nxt_first, cur_active, cur_first;
    always @(posedge pix_clk) begin
        nxt_active<=cy_next<10'(V_ACTIVE);
        nxt_first<=cy_next[SHIFT-1:0]==0;
        if(cx==XW'(H_TOTAL-1)) begin cur_active<=nxt_active; cur_first<=nxt_first; end
    end
    wire at_wrap=cx>=XW'(H_TOTAL-3);
    wire ay3_active=at_wrap ? nxt_active : cur_active;
    wire ay3_first=at_wrap ? nxt_first : cur_first;
    reg line_begin, scan, tag_match;
    // The logical line a line_begin can start during this physical line:
    // line_begin falls in its last clocks and refers to the next physical
    // line. cy is constant over the line, so this is registered from cy only.
    reg [7:0] next_line;
    reg [8:0] scan_addr;
    always @(posedge pix_clk) begin
        next_line<=cy==10'(V_TOTAL-1) ? 8'd0 : 8'((cy+10'd1)>>SHIFT);
        line_begin<=cx==XW'(H_TOTAL-3) && ay3_first && ay3_active;
        scan<=(at_wrap || cx<XW'(H_ACTIVE-3)) && ay3_active;
        scan_addr<=9'(ax3>>SHIFT);
    end
    reg req_toggle, req_bank;
    reg [7:0] req_line;
    reg display, blank, started;
    reg vblank_toggle, underrun_toggle, vblank_level;
    // The last logical line starts without a request behind it; this toggle
    // reports its start (line_start) the way a request reports the others.
    reg last_toggle;
    (* ASYNC_REG="TRUE" *) reg [1:0] done_sync;
    reg done_seen;
    reg [7:0] done_tag_pix;
    reg done_valid;                    // a done for the outstanding request arrived
    reg [8:0] init_addr;
    reg memory_up;
    (* ASYNC_REG="TRUE" *) reg [1:0] memory_up_sync;
    (* ASYNC_REG="TRUE" *) reg [1:0] scan_quiet_sync;
    // Isolate the CDC source from memory_ready's large system-domain fanout
    // and from the ready AND gate.  The extra cycle only delays enable.
    always @(posedge sys_clk)
        if(sys_reset) memory_up<=0;
        else memory_up<=memory_ready && line_init_done;
    always @(posedge pix_clk)
        if(pix_reset) memory_up_sync<=0;
        else memory_up_sync<={memory_up_sync[0],memory_up};
    // A system-only reset must first stop pixel reads before either line
    // bank is cleared. Acknowledge the synchronized pixel-side read gate.
    always @(posedge sys_clk)
        if(sys_reset) scan_quiet_sync<=0;
        else scan_quiet_sync<={scan_quiet_sync[0],!memory_up_sync[1]};
    always @(posedge sys_clk)
        if(sys_reset) begin line_init_done<=0; init_addr<=0; frame_ready<=0; end
        else begin
            if(!line_init_done && scan_quiet_sync[1]) begin
                if(init_addr==9'd511) line_init_done<=1;
                else init_addr<=init_addr+1'b1;
            end
            if(render_done && render_line==0) frame_ready<=1;
        end
    wire done_edge=done_sync[1]!=done_seen;
    // The read for the first pixel of a line already uses the new decision.
    // tag_match: done_tag_pix equals the line that begins at the lookahead
    // position, registered with the other decisions. It sees a new done tag
    // one clock after done_valid, so a done must arrive at least two pixel
    // clocks before its line starts (earlier ones swap as before; a later one
    // shows the line black as an underrun).
    always @(posedge pix_clk) tag_match<=done_tag_pix==next_line;
    wire swap=line_begin && done_valid && tag_match;
    wire display_now=swap ? req_bank : display;
    wire blank_now=line_begin ? !swap : blank;
    always @(posedge pix_clk)
        if(pix_reset) begin
            req_toggle<=0; req_bank<=1; req_line<=0; display<=0; blank<=1; started<=0;
            vblank_toggle<=0; underrun_toggle<=0; vblank_level<=0; last_toggle<=0;
            done_sync<=0; done_seen<=0; done_tag_pix<=0; done_valid<=0;
        end else begin
            done_sync<={done_sync[0],done_toggle};
            if(done_edge) begin
                done_seen<=done_sync[1];
                // The bundled tag has been stable while the toggle crossed two
                // stages.  Capture it unconditionally so its data path does not
                // include the equality decode feeding this register's CE.
                done_tag_pix<=done_tag;
                done_valid<=done_tag==req_line;
            end
            if(memory_up_sync[1] && cx==0 && ((cy[SHIFT-1:0]==0 && cy<10'(V_ACTIVE-SCALE)) || cy==10'(LINE0_Y))) begin
                req_toggle<=~req_toggle; req_bank<=~display; done_valid<=0;
                req_line<=cy==10'(LINE0_Y) ? 8'd0 : 8'(cy>>SHIFT)+1'b1;
            end
            if(memory_up_sync[1] && cx==0 && cy==10'(V_ACTIVE-SCALE)) last_toggle<=~last_toggle;
            display<=display_now; blank<=blank_now;
            if(swap) started<=1;
            if(line_begin && !swap && started && memory_up_sync[1]) underrun_toggle<=~underrun_toggle;
            if(cx==0 && cy==10'(V_ACTIVE)) vblank_toggle<=~vblank_toggle;
            vblank_level<=cy>=10'(V_ACTIVE);
            if(!memory_up_sync[1]) begin done_valid<=0; blank<=1; started<=0; end
        end
    // Scan-out: read at the lookahead position, colour two edges later.
    wire [15:0] bank_rd [0:1];
    reg scan_q, blank_q, sel_q;
    wire [15:0] word=bank_rd[sel_q];
    always @(posedge pix_clk) begin
        scan_q<=scan && memory_up_sync[1]; blank_q<=blank_now; sel_q<=display_now;
        if(pix_reset) rgb<=0;
        else if(scan_q && !blank_q) rgb<={word[11:8],word[11:8],word[7:4],word[7:4],word[3:0],word[3:0]};
        else rgb<=0;
    end

    // ---------------- system domain ----------------
    (* ASYNC_REG="TRUE" *) reg [1:0] req_sync, vblank_sync, underrun_sync, live_sync, last_sync;
    reg req_seen, vblank_seen, underrun_seen, last_seen;
    reg write_bank;
    reg done_toggle;
    reg [7:0] done_tag;
    assign vblank_live=live_sync[1];
    always @(posedge sys_clk)
        if(sys_reset) begin
            req_sync<=0; vblank_sync<=0; underrun_sync<=0; live_sync<=0; last_sync<=0;
            req_seen<=0; vblank_seen<=0; underrun_seen<=0; last_seen<=0; write_bank<=1;
            render_start<=0; render_line<=0; vblank_start<=0; underrun_event<=0;
            line_start<=0; shown_line<=0; done_toggle<=0; done_tag<=0;
        end else begin
            req_sync<={req_sync[0],req_toggle};
            vblank_sync<={vblank_sync[0],vblank_toggle};
            underrun_sync<={underrun_sync[0],underrun_toggle};
            live_sync<={live_sync[0],vblank_level};
            last_sync<={last_sync[0],last_toggle};
            render_start<=0; vblank_start<=0; underrun_event<=0; line_start<=0;
            if(req_sync[1]!=req_seen) begin
                // Payload has been stable since the toggle changed.
                req_seen<=req_sync[1]; render_start<=1; render_line<=req_line; write_bank<=req_bank;
                // A request for line L>0 is made as line L-1 starts showing.
                if(req_line!=0) begin line_start<=1; shown_line<=req_line-1'b1; end
            end
            // A physical line apart from the last request, so never the same edge.
            if(last_sync[1]!=last_seen) begin last_seen<=last_sync[1]; line_start<=1; shown_line<=8'(LINES-1); end
            if(vblank_sync[1]!=vblank_seen) begin vblank_seen<=vblank_sync[1]; vblank_start<=1; end
            if(underrun_sync[1]!=underrun_seen) begin underrun_seen<=underrun_sync[1]; underrun_event<=1; end
            if(render_done) begin done_toggle<=~done_toggle; done_tag<=render_line; end
        end

    wire [15:0] system_rd [0:1];
    assign line_rdata=system_rd[write_bank];
    genvar i;
    generate for(i=0;i<2;i=i+1) begin: bank
        kagura_ram_tdp #(.DEPTH(512),.WIDTH(16)) ram(
            .clk_a(sys_clk),.enable_a(!sys_reset && ((!line_init_done && scan_quiet_sync[1]) ||
                (line_init_done && (line_write || line_read) && write_bank==i))),
            .write_a(!line_init_done || line_write),
            .addr_a(!line_init_done ? init_addr : line_addr),.wdata_a(!line_init_done ? 16'b0 : line_data),.rdata_a(system_rd[i]),
            .clk_b(pix_clk),.enable_b(scan && memory_up_sync[1] && display_now==i),.addr_b(scan_addr),.rdata_b(bank_rd[i]));
    end endgenerate
endmodule
