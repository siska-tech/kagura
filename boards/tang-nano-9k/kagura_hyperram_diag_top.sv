// SPDX-License-Identifier: Apache-2.0
// UART memory test for kagura_hyperram_ctrl on the Tang Nano 9K PSRAM (die 0).
// Each pass writes 2^WORDS_LOG2 words with an address hash of a per-pass seed,
// reads them all back with rd_latency RL_MIN..RL_MAX (cycling per pass) and
// prints one line (115200 8N1 on the BL702 UART, FPGA TX = pin 17):
//   "P pppp S ss R r E eeeeeeee A aaaaa G gggggggg X xxxxxxxx"
// pass number, CK phase step (x22.5 deg, decimal), rd_latency, error
// count, first failing word address, data read and data expected there
// (A/G/X stay 0 on a clean pass). With PHASE_SWEEP the CK phase advances after
// every RL_MIN..RL_MAX round through the rPLL dynamic phase input; otherwise it
// stays at PHASE. A sweep with RL 5..7 at 54 MHz passed 1M words at rd_latency
// 6 for steps 1..5 (22.5..112.5 deg), had bit errors at 6 and no response from
// 7 on; the default 3 (67.5 deg) is the centre of that window.
// Settings found with kagura_hyperram_scope_top at 54 MHz: lat_cycles 14,
// rd_latency 6.
module kagura_hyperram_diag_top #(
    parameter integer WORDS_LOG2=20,
    parameter [4:0] LAT=5'd14,
    parameter [2:0] RL_MIN=3'd6,
    parameter [2:0] RL_MAX=3'd6,
    parameter       PHASE_SWEEP=1'b0,
    parameter [3:0] PHASE=4'd3
) (
    input  wire clk27,
    input  wire reset_n,
    output wire uart_tx,
    output wire [5:0] led_n,
    output wire [1:0] O_psram_ck,
    output wire [1:0] O_psram_ck_n,
    inout  wire [1:0] IO_psram_rwds,
    output wire [1:0] O_psram_reset_n,
    inout  wire [15:0] IO_psram_dq,
    output wire [1:0] O_psram_cs_n
);
    // CLKOUTP phase comes from psda. Dynamic DUTYDA places the falling edge
    // absolutely (DUTYDA 8 with psda 4 gave a 25% CK on hardware), so it
    // follows psda to keep 50% duty.
    wire clk,clk_ck,lock;
    logic [3:0] psda;
    rPLL #(.FCLKIN("27"),.IDIV_SEL(0),.FBDIV_SEL(1),.ODIV_SEL(8),
        .DYN_DA_EN("true"),.DEVICE("GW1NR-9C")) pll(
        .CLKOUT(clk),.CLKOUTP(clk_ck),.LOCK(lock),.CLKIN(clk27),.CLKFB(1'b0),
        .RESET(~reset_n),.RESET_P(1'b0),.FBDSEL(6'b0),.IDSEL(6'b0),.ODSEL(6'b0),
        .PSDA(psda),.DUTYDA(psda+4'd8),.FDLY(4'b0));

    reg [3:0] rst_pipe=0;
    always @(posedge clk) rst_pipe<={rst_pipe[2:0],lock&reset_n};
    wire rst_n=rst_pipe[3];

    kagura_hyperram_memtest #(
        .WORDS_LOG2(WORDS_LOG2),.LAT(LAT),.RL_MIN(RL_MIN),.RL_MAX(RL_MAX),
        .PHASE_SWEEP(PHASE_SWEEP),.PHASE(PHASE)
    ) test(.clk,.clk_ck,.rst_n,.psda,.uart_tx,.led_n,
        .O_psram_ck,.O_psram_ck_n,.IO_psram_rwds,.O_psram_reset_n,
        .IO_psram_dq,.O_psram_cs_n);
endmodule
