// SPDX-License-Identifier: Apache-2.0
// Gowin GW1NR PHY for kagura_hyperram_ctrl: one 8-bit HyperRAM die.
// Only Gowin primitives (ODDR/IDDR/IOBUF/OBUF) are used, no licensed IP.
//
// clk      : controller clock (one CK cycle per clock, DDR data on both edges)
// clk_ck   : same frequency as clk, delayed 22.5..112.5 degrees (67.5 is the
//            centre measured on hardware at 54 MHz); drives CK so that
//            write data from clk is centred on the CK edges. Memory-driven
//            read data is captured on clk after the controller's RD_LATENCY.
// The RWDS read-data strobe is not used: capture timing is a fixed latency
// that must be tuned on hardware. IDDR and ODDR share a pin buffer, so Gowin
// requires them to use the same clock net; tune via the controller RD_LATENCY.
module kagura_hyperram_phy_gowin (
    input  wire clk,
    input  wire clk_ck,

    input  wire phy_reset_n,
    input  wire phy_cs_n,
    input  wire phy_ck_en,
    input  wire phy_dq_oe,
    input  wire [7:0] phy_dq_o_rise,
    input  wire [7:0] phy_dq_o_fall,
    input  wire phy_rwds_oe,
    input  wire phy_rwds_o_rise,
    input  wire phy_rwds_o_fall,
    output wire [7:0] phy_dq_i_rise,
    output wire [7:0] phy_dq_i_fall,
    // RWDS as seen on clk (diagnostics only; the controller does not use it).
    output wire phy_rwds_i_rise,
    output wire phy_rwds_i_fall,

    output wire O_psram_ck,
    output wire O_psram_ck_n,
    output wire O_psram_reset_n,
    output wire O_psram_cs_n,
    inout  wire IO_psram_rwds,
    inout  wire [7:0] IO_psram_dq
);
    // CK idles low. Enable is registered on clk so the gated edges stay glitch-free.
    // The clk ODDRs below sample their (clk-registered) inputs one clk edge
    // later, but the clk_ck ODDR samples after the clk edge and already
    // sees the new value; the second stage keeps CK in the same cycle as DQ.
    // Hardware showed a single stage puts CK one cycle early, so the memory
    // latched the idle bus as the first CA byte (every command became a read).
    // The second stage is clocked by clk_ck: the short clk->clk_ck crossing is
    // then fabric FF to FF, and the fixed-location ODDR gets a full clk_ck
    // cycle. (A clk second stage missed setup into the ODDR by 0.234 ns once
    // the evaluation logic grew.) The CK timing is unchanged.
    reg ck_en_q=0;
    always @(posedge clk) ck_en_q<=phy_ck_en;
    reg ck_en_d=0;
    always @(posedge clk_ck) ck_en_d<=ck_en_q;
    wire ck_oddr,ck_n_oddr;
    ODDR ck_ddr(.D0(ck_en_d),.D1(1'b0),.TX(1'b0),.CLK(clk_ck),.Q0(ck_oddr),.Q1());
    ODDR ck_n_ddr(.D0(~ck_en_d),.D1(1'b1),.TX(1'b0),.CLK(clk_ck),.Q0(ck_n_oddr),.Q1());
    assign O_psram_ck=ck_oddr;
    assign O_psram_ck_n=ck_n_oddr;

    assign O_psram_reset_n=phy_reset_n;

    // CS# goes through an ODDR like DQ so it brackets the delayed CK pulses.
    reg cs_n_q=1'b1;
    always @(posedge clk) cs_n_q<=phy_cs_n;
    ODDR #(.INIT(1'b1)) cs_ddr(.D0(cs_n_q),.D1(cs_n_q),.TX(1'b0),.CLK(clk),.Q0(O_psram_cs_n),.Q1());

    // Output enables must line up with the registered data; register once on clk.
    reg dq_oe_q,rwds_oe_q;
    reg [7:0] dq_r_q,dq_f_q;
    reg rwds_r_q,rwds_f_q;
    always @(posedge clk) begin
        dq_oe_q<=phy_dq_oe;
        rwds_oe_q<=phy_rwds_oe;
        dq_r_q<=phy_dq_o_rise;
        dq_f_q<=phy_dq_o_fall;
        rwds_r_q<=phy_rwds_o_rise;
        rwds_f_q<=phy_rwds_o_fall;
    end

    genvar i;
    generate
        for(i=0;i<8;i=i+1) begin : dq
            wire o,oen,in_pin;
            ODDR od(.D0(dq_r_q[i]),.D1(dq_f_q[i]),.TX(~dq_oe_q),.CLK(clk),.Q0(o),.Q1(oen));
            IOBUF io(.I(o),.OEN(oen),.IO(IO_psram_dq[i]),.O(in_pin));
            IDDR id(.D(in_pin),.CLK(clk),.Q0(phy_dq_i_rise[i]),.Q1(phy_dq_i_fall[i]));
        end
    endgenerate

    wire rwds_o,rwds_oen,rwds_in;
    ODDR rwds_ddr(.D0(rwds_r_q),.D1(rwds_f_q),.TX(~rwds_oe_q),.CLK(clk),.Q0(rwds_o),.Q1(rwds_oen));
    IOBUF rwds_io(.I(rwds_o),.OEN(rwds_oen),.IO(IO_psram_rwds),.O(rwds_in));
    IDDR rwds_id(.D(rwds_in),.CLK(clk),.Q0(phy_rwds_i_rise),.Q1(phy_rwds_i_fall));
endmodule
