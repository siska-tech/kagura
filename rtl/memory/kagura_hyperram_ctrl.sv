// SPDX-License-Identifier: Apache-2.0
// Vendor-neutral HyperBus (8-bit DDR, HyperRAM-style) controller for one
// PSRAM die. It replaces the generated Gowin PSRAM_HS controller: the user
// side keeps the same cmd/cmd_en/cmd_rdy, word address, 32-bit data and
// rd_data_valid shape, so kagura_psram_byte_bridge connects unchanged.
//
// The core runs in the CK cycle domain. One user clock is one CK cycle that
// carries one DDR byte pair, so no DDR primitive appears here. A PHY (DDR I/O,
// CK phase, RWDS capture) is expected to turn each pair into pin activity:
//   * phy_ck_en: CK toggles during this cycle. For writes the PHY must place
//     the pair centred on the CK edges (CK delayed by 90 degrees).
//   * phy_dq_o_rise/fall: bytes for the CK rising/falling edge of that cycle.
//   * phy_dq_i_rise/fall: the pair the memory drove in a cycle, seen
//     rd_latency cycles later (PHY capture pipeline depth, including any
//     RWDS-to-clock transfer).
//
// Every command moves one 32-bit word (4 bytes at byte address 4*addr), the
// first byte in rd_data/wr_data[7:0]. data_mask bit i = 1 masks byte i.
// cmd_reg=1 selects register space: addr is the register word address
// (ID0=0, ID1=1, CR0=0x800, CR1=0x801). A register read returns the value in
// {rd_data[7:0],rd_data[15:8]}; a register write sends wr_data[15:0] MSB first
// with zero latency.
// Fixed (2x) initial latency is assumed and written to CR0 after reset.
// Tang Nano 9K die 0 was tested at 54MHz with lat_cycles=14, rd_latency=6
// and a 67.5-degree CK phase. Other boards/clock settings require validation.
module kagura_hyperram_ctrl #(
    parameter integer ADDR_WIDTH=20,
    parameter integer CS_HIGH_CYCLES=2,
    // Power-up wait before the first access; reset# is released at half.
    parameter integer INIT_CYCLES=4096,
    parameter         CFG_WRITE=1'b1,
    parameter [15:0]  CR0_VALUE=16'h8F1F,
    // CR0 lives at word address 0x800 in register space.
    parameter [31:0]  CFG_WORD_ADDR=32'h0000_0800
) (
    input  logic clk,
    input  logic rst_n,
    // CK cycles from the first CA cycle to the first data cycle (2 x latency
    // count) and capture delay in cycles; hold constant while a command is in flight.
    input  logic [4:0] lat_cycles,
    input  logic [2:0] rd_latency,
    input  logic cmd,            // 0 read, 1 write
    input  logic cmd_reg,
    input  logic cmd_en,
    output logic cmd_rdy,
    input  logic [ADDR_WIDTH-1:0] addr,
    input  logic [31:0] wr_data,
    input  logic [3:0]  data_mask,
    output logic [31:0] rd_data,
    output logic rd_data_valid,
    output logic init_calib,

    output logic phy_reset_n,
    output logic phy_cs_n,
    output logic phy_ck_en,
    output logic phy_dq_oe,
    output logic [7:0] phy_dq_o_rise,
    output logic [7:0] phy_dq_o_fall,
    output logic phy_rwds_oe,
    output logic phy_rwds_o_rise,
    output logic phy_rwds_o_fall,
    // Output-enable windows for the PHY tristate (TX) inputs: phy_dq_oe /
    // phy_rwds_oe widened by one cycle on each side. Gowin STA does not time
    // fabric paths into an ODDR TX pin, and a placement whose DQ7 enable was a
    // cycle late turned every write CA into a read on hardware; the margin
    // keeps a late or early enable inside the window. The extra cycles fall
    // before CA (CK stopped), after CA or before write data (memory not
    // driving during latency) and right after write data (CS high).
    output logic phy_dq_tx,
    output logic phy_rwds_tx,
    input  logic [7:0] phy_dq_i_rise,
    input  logic [7:0] phy_dq_i_fall
);
    typedef enum logic [2:0] {S_INIT,S_CFG,S_IDLE,S_XFER,S_GAP} state_t;
    state_t state;

    localparam integer CNT_W=$clog2(INIT_CYCLES+2)>6 ? $clog2(INIT_CYCLES+2) : 6;
    logic [CNT_W-1:0] t;
    logic op_write,op_cfg,calib;
    logic [15:0] cr_data;
    logic [47:0] ca;
    logic [31:0] wdata;
    logic [3:0] wmask;

    // Cycle 0 of a transfer only asserts CS; CA occupies cycles 1..3.
    wire [CNT_W-1:0] ds=op_cfg ? CNT_W'(3) : CNT_W'(lat_cycles);
    wire [CNT_W-1:0] nd=op_cfg ? CNT_W'(1) : CNT_W'(2);
    wire [CNT_W-1:0] data_t0=CNT_W'(1)+ds;
    wire [CNT_W-1:0] last_t=op_write||op_cfg ? ds+nd : ds+nd+CNT_W'(rd_latency);
    wire in_xfer=state==S_XFER;
    wire ca_phase=in_xfer && t>=1 && t<=3;
    wire data_phase=in_xfer && t>=data_t0 && t<data_t0+nd;
    wire data_j=data_phase && (t!=data_t0);
    wire [CNT_W-1:0] cap_t0=data_t0+CNT_W'(rd_latency);

    function automatic [47:0] make_ca(input rd,input as,input [31:0] word_addr);
        make_ca={rd,as,1'b1,word_addr[31:3],13'b0,word_addr[2:0]};
    endfunction

    wire [31:0] cmd_word_addr=32'(addr)<<1;

    assign cmd_rdy=state==S_IDLE;
    assign init_calib=calib;
    assign phy_reset_n=!(state==S_INIT && t<CNT_W'(INIT_CYCLES/2));
    assign phy_cs_n=!in_xfer;
    assign phy_ck_en=in_xfer && t>=1 && t<=ds+nd;
    assign phy_dq_oe=ca_phase || (data_phase && (op_write||op_cfg));
    // RWDS is a write mask only for memory writes; register writes leave it undriven.
    assign phy_rwds_oe=data_phase && op_write && !op_cfg;
    wire writes=op_write || op_cfg;
    wire after_write=state==S_GAP && t==0;   // the cycle after the last data cycle of a write
    assign phy_dq_tx=(in_xfer && t<=4) || (in_xfer && writes && t>=data_t0-1'b1) || (after_write && writes);
    assign phy_rwds_tx=(in_xfer && op_write && !op_cfg && t>=data_t0-1'b1) || (after_write && op_write && !op_cfg);

    always_comb begin
        phy_dq_o_rise=0;
        phy_dq_o_fall=0;
        phy_rwds_o_rise=0;
        phy_rwds_o_fall=0;
        if(ca_phase) begin
            case(t[1:0])
                2'd1: {phy_dq_o_rise,phy_dq_o_fall}=ca[47:32];
                2'd2: {phy_dq_o_rise,phy_dq_o_fall}=ca[31:16];
                default: {phy_dq_o_rise,phy_dq_o_fall}=ca[15:0];
            endcase
        end else if(data_phase && op_cfg) begin
            {phy_dq_o_rise,phy_dq_o_fall}=cr_data;
        end else if(data_phase && op_write) begin
            if(!data_j) begin
                phy_dq_o_rise=wdata[7:0];
                phy_dq_o_fall=wdata[15:8];
                phy_rwds_o_rise=wmask[0];
                phy_rwds_o_fall=wmask[1];
            end else begin
                phy_dq_o_rise=wdata[23:16];
                phy_dq_o_fall=wdata[31:24];
                phy_rwds_o_rise=wmask[2];
                phy_rwds_o_fall=wmask[3];
            end
        end
    end

    always_ff @(posedge clk) begin
        if(!rst_n) begin
            state<=S_INIT;
            t<=0;
            op_write<=0;
            op_cfg<=0;
            calib<=0;
            cr_data<=CR0_VALUE;
            ca<=0;
            wdata<=0;
            wmask<=0;
            rd_data<=0;
            rd_data_valid<=0;
        end else begin
            rd_data_valid<=0;
            case(state)
                S_INIT: begin
                    if(t==CNT_W'(INIT_CYCLES)) begin
                        t<=0;
                        if(CFG_WRITE) begin
                            op_write<=1;
                            op_cfg<=1;
                            ca<=make_ca(1'b0,1'b1,CFG_WORD_ADDR);
                            state<=S_CFG;
                        end else begin
                            calib<=1;
                            state<=S_IDLE;
                        end
                    end else begin
                        t<=t+1'b1;
                    end
                end
                S_CFG: begin
                    state<=S_XFER;
                end
                S_IDLE: begin
                    t<=0;
                    if(cmd_en) begin
                        op_write<=cmd;
                        op_cfg<=cmd && cmd_reg;
                        ca<=make_ca(!cmd,cmd_reg,cmd_reg ? 32'(addr) : cmd_word_addr);
                        cr_data<=wr_data[15:0];
                        wdata<=wr_data;
                        wmask<=data_mask;
                        state<=S_XFER;
                    end
                end
                S_XFER: begin
                    if(!op_write && !op_cfg) begin
                        if(t==cap_t0)
                            {rd_data[15:8],rd_data[7:0]}<={phy_dq_i_fall,phy_dq_i_rise};
                        if(t==cap_t0+1'b1) begin
                            {rd_data[31:24],rd_data[23:16]}<={phy_dq_i_fall,phy_dq_i_rise};
                            rd_data_valid<=1;
                        end
                    end
                    if(t==last_t) begin
                        t<=0;
                        state<=S_GAP;
                    end else begin
                        t<=t+1'b1;
                    end
                end
                S_GAP: begin
                    if(t>=CNT_W'(CS_HIGH_CYCLES-1)) begin
                        t<=0;
                        state<=S_IDLE;
                        op_cfg<=0;
                        calib<=1;
                    end else begin
                        t<=t+1'b1;
                    end
                end
                default: state<=S_INIT;
            endcase
        end
    end
endmodule
