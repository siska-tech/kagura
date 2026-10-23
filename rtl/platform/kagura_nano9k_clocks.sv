// SPDX-License-Identifier: Apache-2.0
// GW1NR-9C, 27MHz reference. Verify frequency/routing in P&R reports.
// VIDEO_ID_CODE 1: 27*14/3 = 126MHz serial, 25.2MHz pixel.
// VIDEO_ID_CODE 4: 27*55/4 = 371.25MHz serial (VCO 742.5MHz, PFD 6.75MHz),
// 74.25MHz pixel (docs/wide-mode.md).
module kagura_nano9k_clocks #(
    parameter integer VIDEO_ID_CODE=1
) (
    input wire clk27, reset_n,
    output wire pixel, serial, system_clk,
    output wire pixel_lock, system_lock
);
    localparam integer VIDEO_IDIV=VIDEO_ID_CODE==4 ? 3 : 2;
    localparam integer VIDEO_FBDIV=VIDEO_ID_CODE==4 ? 54 : 13;
    localparam integer VIDEO_ODIV=VIDEO_ID_CODE==4 ? 2 : 4;
    rPLL #(.FCLKIN("27"),.IDIV_SEL(VIDEO_IDIV),.FBDIV_SEL(VIDEO_FBDIV),.ODIV_SEL(VIDEO_ODIV),
        .DEVICE("GW1NR-9C")) video_pll(
        .CLKOUT(serial),.LOCK(pixel_lock),.CLKIN(clk27),.CLKFB(1'b0),
        .RESET(~reset_n),.RESET_P(1'b0),.FBDSEL(6'b0),.IDSEL(6'b0),.ODSEL(6'b0),
        .PSDA(4'b0),.DUTYDA(4'b0),.FDLY(4'b0));
    CLKDIV #(.DIV_MODE("5"),.GSREN("false")) pixel_div(
        .CLKOUT(pixel),.HCLKIN(serial),.RESETN(pixel_lock),.CALIB(1'b0));
    rPLL #(.FCLKIN("27"),.IDIV_SEL(0),.FBDIV_SEL(1),.ODIV_SEL(8),
        .DEVICE("GW1NR-9C")) system_pll(
        .CLKOUT(system_clk),.LOCK(system_lock),.CLKIN(clk27),.CLKFB(1'b0),
        .RESET(~reset_n),.RESET_P(1'b0),.FBDSEL(6'b0),.IDSEL(6'b0),.ODSEL(6'b0),
        .PSDA(4'b0),.DUTYDA(4'b0),.FDLY(4'b0));
endmodule
