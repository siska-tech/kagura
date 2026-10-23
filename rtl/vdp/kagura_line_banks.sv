// SPDX-License-Identifier: Apache-2.0
// Two 1024x16 line banks with a handover protocol (system renders, pixel
// displays). Ownership never overlaps:
// - system writes only the back bank and toggles ready after its last write;
// - pixel swaps the displayed bank at pix_swap only once that ready toggle
//   has crossed the synchronizer, otherwise repeats the line (sticky underrun);
// - system may use the new back bank only after the swapped display index has
//   crossed back, i.e. after pixel stopped reading it.
// Both resets must be asserted together; each is released in its own domain.
module kagura_line_banks (
    input wire sys_clk, sys_reset,
    output wire sys_can_write,       // back bank owned by system
    input wire sys_enable, sys_write,
    input wire [9:0] sys_addr,
    input wire [15:0] sys_wdata,
    output wire [15:0] sys_rdata,
    input wire sys_done,             // pulse after the last write of a line
    input wire pix_clk, pix_reset,
    input wire pix_swap,             // pulse at a logical line start
    input wire pix_enable,
    input wire [9:0] pix_addr,
    output wire [15:0] pix_rdata,
    output reg pix_underrun
);
    // Pixel domain: displayed bank and the ready toggle it has consumed.
    // Underrun counts only after the first handover (startup is not a miss).
    reg display, ready_seen, started;
    (* ASYNC_REG="TRUE" *) reg [1:0] ready_sync;
    // System domain: ready toggle and the synchronized display index.
    reg ready_toggle, filled, back_at_done;
    (* ASYNC_REG="TRUE" *) reg [1:0] display_sync;
    wire back=~display_sync[1];
    // After done, wait until pixel shows the filled bank before writing again.
    assign sys_can_write=!filled;
    always @(posedge sys_clk)
        if(sys_reset) begin ready_toggle<=0; filled<=0; display_sync<=0; end
        else begin
            display_sync<={display_sync[0],display};
            if(sys_done && !filled) begin ready_toggle<=~ready_toggle; filled<=1; end
            // The filled bank is now displayed; the old one is the back bank.
            else if(filled && display_sync[1]==back_at_done) filled<=0;
        end
    always @(posedge sys_clk)
        if(sys_reset) back_at_done<=1;
        else if(sys_done && !filled) back_at_done<=back;
    always @(posedge pix_clk)
        if(pix_reset) begin display<=0; ready_seen<=0; started<=0; ready_sync<=0; pix_underrun<=0; end
        else begin
            ready_sync<={ready_sync[0],ready_toggle};
            if(pix_swap) begin
                if(ready_sync[1]!=ready_seen) begin display<=~display; ready_seen<=ready_sync[1]; started<=1; end
                else if(started) pix_underrun<=1;
            end
        end
    wire [15:0] rdata_a [0:1];
    wire [15:0] rdata_b [0:1];
    genvar i;
    generate for(i=0;i<2;i=i+1) begin: bank
        kagura_ram_tdp #(.DEPTH(1024),.WIDTH(16)) ram(
            .clk_a(sys_clk),.enable_a(sys_enable && back==i),.write_a(sys_write),
            .addr_a(sys_addr),.wdata_a(sys_wdata),.rdata_a(rdata_a[i]),
            .clk_b(pix_clk),.enable_b(pix_enable && display==i),
            .addr_b(pix_addr),.rdata_b(rdata_b[i]));
    end endgenerate
    reg sys_sel,pix_sel;
    always @(posedge sys_clk) sys_sel<=back;
    always @(posedge pix_clk) pix_sel<=display;
    assign sys_rdata=rdata_a[sys_sel];
    assign pix_rdata=rdata_b[pix_sel];
`ifndef SYNTHESIS // Gowin does not define SYNTHESIS; the pragma below hides the checker.
// synthesis translate_off
    // Ownership check, independent of address: a system write must never
    // target the bank pixel is displaying, nor happen while filled.
    always @(posedge sys_clk)
        if(!sys_reset && sys_enable && sys_write && (back==display || filled))
            $fatal(1,"line bank ownership: system wrote bank %0d (display %0d, filled %0d)",back,display,filled);
// synthesis translate_on
`endif
endmodule
