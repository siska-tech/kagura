// SPDX-License-Identifier: Apache-2.0
// Hardware bring-up for kagura_hyperram_ctrl on the Tang Nano 9K in-package
// PSRAM (die 0 only). After init it writes a word pattern and reads it back,
// with lat_cycles 14, sweeping the read capture delay rd_latency 4..7 until a
// pass occurs (6 passed on hardware at 54 MHz).
//   led_n[0] init_calib
//   led_n[1] pass (all words matched at the current rd_latency; stops sweep)
//   led_n[2] every rd_latency failed
//   led_n[3] heartbeat (test finished)
//   led_n[5:4] current rd_latency - 4 (binary, lit = 1)
module kagura_hyperram_test_top #(
    parameter integer WORDS=256
) (
    input  wire clk27,
    input  wire reset_n,
    output wire [5:0] led_n,
    output wire [1:0] O_psram_ck,
    output wire [1:0] O_psram_ck_n,
    inout  wire [1:0] IO_psram_rwds,
    output wire [1:0] O_psram_reset_n,
    inout  wire [15:0] IO_psram_dq,
    output wire [1:0] O_psram_cs_n
);
    wire clk,clk_ck,lock;
    // 54 MHz; CLKOUTP is the same clock shifted by 67.5 degrees (PSDA 3 x 22.5).
    rPLL #(.FCLKIN("27"),.IDIV_SEL(0),.FBDIV_SEL(1),.ODIV_SEL(8),
        .PSDA_SEL("0011"),.DUTYDA_SEL("1000"),.DEVICE("GW1NR-9C")) pll(
        .CLKOUT(clk),.CLKOUTP(clk_ck),.LOCK(lock),.CLKIN(clk27),.CLKFB(1'b0),
        .RESET(~reset_n),.RESET_P(1'b0),.FBDSEL(6'b0),.IDSEL(6'b0),.ODSEL(6'b0),
        .PSDA(4'b0),.DUTYDA(4'b0),.FDLY(4'b0));

    reg [3:0] rst_pipe=0;
    always @(posedge clk) rst_pipe<={rst_pipe[2:0],lock&reset_n};
    wire rst_n=rst_pipe[3];

    logic cmd,cmd_en,cmd_rdy,rd_data_valid,init_calib;
    logic [19:0] addr;
    logic [31:0] wr_data,rd_data;
    logic phy_reset_n,phy_cs_n,phy_ck_en,phy_dq_oe,phy_rwds_oe,phy_rwds_o_rise,phy_rwds_o_fall;
    logic [7:0] o_rise,o_fall,i_rise,i_fall;

    logic [1:0] lat;
    kagura_hyperram_ctrl #(.ADDR_WIDTH(20)) ctrl(
        .clk,.rst_n,.lat_cycles(5'd14),.rd_latency({1'b1,lat}),.cmd,.cmd_reg(1'b0),.cmd_en,.cmd_rdy,.addr,.wr_data,.data_mask(4'b0),.rd_data,
        .rd_data_valid,.init_calib,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall));

    kagura_hyperram_phy_gowin phy(
        .clk,.clk_ck,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall),
        .O_psram_ck(O_psram_ck[0]),.O_psram_ck_n(O_psram_ck_n[0]),
        .O_psram_reset_n(O_psram_reset_n[0]),.O_psram_cs_n(O_psram_cs_n[0]),
        .IO_psram_rwds(IO_psram_rwds[0]),.IO_psram_dq(IO_psram_dq[7:0]));

    assign O_psram_ck[1]=1'b0;
    assign O_psram_ck_n[1]=1'b1;
    assign O_psram_reset_n[1]=1'b0;
    assign O_psram_cs_n[1]=1'b1;
    assign IO_psram_rwds[1]=1'bz;
    assign IO_psram_dq[15:8]=8'bz;

    typedef enum logic [2:0] {T_WAIT,T_WRITE,T_READ,T_RWAIT,T_DONE} tstate_t;
    tstate_t ts;
    logic [19:0] idx;
    logic pass,fail,exhausted,beat;
    logic [23:0] hb;

    function automatic [31:0] pattern(input [19:0] i);
        pattern={i[15:0],16'h0}^{i[7:0],i[15:8],i[7:0]^8'h5A,i[15:8]^8'hA5}^32'h9E3779B9;
    endfunction

    always_ff @(posedge clk) begin
        if(!rst_n) begin
            ts<=T_WAIT; idx<=0; cmd_en<=0; cmd<=0; addr<=0; wr_data<=0;
            pass<=0; fail<=0; exhausted<=0; beat<=0; hb<=0; lat<=0;
        end else begin
            cmd_en<=0;
            case(ts)
                T_WAIT: if(init_calib && cmd_rdy) begin idx<=0; fail<=0; ts<=T_WRITE; end
                T_WRITE: if(cmd_rdy && !cmd_en) begin
                    cmd<=1; cmd_en<=1; addr<=idx; wr_data<=pattern(idx);
                    if(idx==WORDS-1) begin idx<=0; ts<=T_READ; end else idx<=idx+1'b1;
                end
                T_READ: if(cmd_rdy && !cmd_en) begin
                    cmd<=0; cmd_en<=1; addr<=idx; ts<=T_RWAIT;
                end
                T_RWAIT: if(rd_data_valid) begin
                    if(rd_data!==pattern(idx)) fail<=1;
                    if(idx==WORDS-1) ts<=T_DONE;
                    else begin idx<=idx+1'b1; ts<=T_READ; end
                end
                T_DONE: begin
                    if(!pass && !exhausted) begin
                        if(!fail) pass<=1;
                        else if(lat==2'd3) exhausted<=1;
                        else begin lat<=lat+1'b1; ts<=T_WAIT; end
                    end
                    hb<=hb+1'b1;
                    if(hb[23]) begin beat<=~beat; hb<=0; end
                end
                default: ts<=T_WAIT;
            endcase
        end
    end

    assign led_n=~{lat[1],lat[0],beat,exhausted,pass,init_calib};
endmodule
