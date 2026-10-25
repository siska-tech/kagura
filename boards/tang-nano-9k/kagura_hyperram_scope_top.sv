// SPDX-License-Identifier: Apache-2.0
// Raw-capture diagnostic for kagura_hyperram_ctrl on the Tang Nano 9K PSRAM
// (die 0). Every transaction records the IDDR outputs of DQ and RWDS for
// CAP cycles from CS# assertion and prints them on the BL702 UART (115200 8N1,
// FPGA TX = pin 17), one line per transaction:
//   "Wk LL: RRFFx RRFFx ..."  or  "Rk LL: ..."  or  "Gk LL: ..."
// RR/FF = DQ captured on the clk rising/falling edge, x = hex of
// {dq_oe, ck_en, rwds_rise, rwds_fall} (dq_oe/ck_en are controller-time).
// Sequence: register reads G0..G3 = ID0, ID1, CR0, CR1; a CR0 write of
// CR0_TEST (C0) and its read-back (G4); for k=0..15 write A1B2C3D4 to word
// 64k with lat_cycles 4+k (Wk, k in hex); read word 64k for k=0..15 (Rk) and
// word 0x8000 (never written, RX), all reads with lat_cycles 24 so CK runs
// well past the data start.
module kagura_hyperram_scope_top #(
    parameter CK_PSDA="0011",
    // Differs from the default 8F1F only in the wrapped-burst length.
    parameter [15:0] CR0_TEST=16'h8F1C
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
    localparam [31:0] W0=32'hA1B2C3D4,W1=32'h01234567;
    localparam integer BAUD_DIV=469;
    localparam integer CAP=48;
    localparam integer OPS=39;

    wire clk,clk_ck,lock;
    rPLL #(.FCLKIN("27"),.IDIV_SEL(0),.FBDIV_SEL(1),.ODIV_SEL(8),
        .PSDA_SEL(CK_PSDA),.DUTYDA_SEL("1000"),.DEVICE("GW1NR-9C")) pll(
        .CLKOUT(clk),.CLKOUTP(clk_ck),.LOCK(lock),.CLKIN(clk27),.CLKFB(1'b0),
        .RESET(~reset_n),.RESET_P(1'b0),.FBDSEL(6'b0),.IDSEL(6'b0),.ODSEL(6'b0),
        .PSDA(4'b0),.DUTYDA(4'b0),.FDLY(4'b0));

    reg [3:0] rst_pipe=0;
    always @(posedge clk) rst_pipe<={rst_pipe[2:0],lock&reset_n};
    wire rst_n=rst_pipe[3];

    logic cmd,cmd_reg,cmd_en,cmd_rdy,rd_data_valid,init_calib;
    logic [19:0] addr;
    logic [31:0] wr_data,rd_data;
    logic [4:0] lat_c;
    logic phy_reset_n,phy_cs_n,phy_ck_en,phy_dq_oe,phy_rwds_oe,phy_rwds_o_rise,phy_rwds_o_fall;
    logic rwds_i_rise,rwds_i_fall;
    logic [7:0] o_rise,o_fall,i_rise,i_fall;

    kagura_hyperram_ctrl #(.ADDR_WIDTH(20)) ctrl(
        .clk,.rst_n,.lat_cycles(lat_c),.rd_latency(3'd7),.cmd,.cmd_reg,.cmd_en,.cmd_rdy,
        .addr,.wr_data,.data_mask(4'b0),.rd_data,
        .rd_data_valid,.init_calib,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall));

    kagura_hyperram_phy_gowin phy(
        .clk,.clk_ck,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall),
        .phy_rwds_i_rise(rwds_i_rise),.phy_rwds_i_fall(rwds_i_fall),
        .O_psram_ck(O_psram_ck[0]),.O_psram_ck_n(O_psram_ck_n[0]),
        .O_psram_reset_n(O_psram_reset_n[0]),.O_psram_cs_n(O_psram_cs_n[0]),
        .IO_psram_rwds(IO_psram_rwds[0]),.IO_psram_dq(IO_psram_dq[7:0]));

    assign O_psram_ck[1]=1'b0;
    assign O_psram_ck_n[1]=1'b1;
    assign O_psram_reset_n[1]=1'b0;
    assign O_psram_cs_n[1]=1'b1;
    assign IO_psram_rwds[1]=1'bz;
    assign IO_psram_dq[15:8]=8'bz;

    // Capture: starts on the cycle the controller asserts CS#.
    logic [19:0] cap [0:CAP-1];
    logic [5:0] cap_n;
    logic cs_q;
    wire cap_done=cap_n==CAP;
    always_ff @(posedge clk) begin
        if(!rst_n) begin
            cap_n<=CAP; cs_q<=0;
        end else begin
            cs_q<=!phy_cs_n;
            if(!phy_cs_n && !cs_q) cap_n<=1;
            else if(!cap_done) cap_n<=cap_n+1'b1;
        end
    end
    wire [5:0] cap_w=(!phy_cs_n && !cs_q) ? 6'd0 : cap_n;
    always_ff @(posedge clk)
        if((!phy_cs_n && !cs_q) || !cap_done)
            cap[cap_w]<={i_rise,i_fall,phy_dq_oe,phy_ck_en,rwds_i_rise,rwds_i_fall};

    // UART transmitter
    logic tx_start,tx_busy;
    logic [7:0] tx_data;
    logic [9:0] tx_shift=10'h3FF;
    logic [8:0] tx_div;
    logic [3:0] tx_bits;
    assign uart_tx=tx_shift[0];
    assign tx_busy=tx_bits!=0;
    always_ff @(posedge clk) begin
        if(!rst_n) begin
            tx_shift<=10'h3FF; tx_bits<=0; tx_div<=0;
        end else if(!tx_busy) begin
            if(tx_start) begin tx_shift<={1'b1,tx_data,1'b0}; tx_bits<=10; tx_div<=BAUD_DIV-1; end
        end else if(tx_div==0) begin
            tx_shift<={1'b1,tx_shift[9:1]}; tx_bits<=tx_bits-1'b1; tx_div<=BAUD_DIV-1;
        end else tx_div<=tx_div-1'b1;
    end

    function automatic [7:0] hex(input [3:0] n);
        hex=n<10 ? 8'h30+8'(n) : 8'h41+8'(n)-8'd10;
    endfunction

    typedef enum logic [2:0] {ST_WAIT,ST_ISSUE,ST_BUSY,ST_HDR,ST_BODY,ST_EOL,ST_PAUSE} st_t;
    st_t st;
    logic [5:0] op;
    logic [2:0] hidx,j;
    logic [5:0] c;
    logic [24:0] pause;
    // 0..3 register reads, 4 CR0 write, 5 CR0 read, 6..21 writes, 22..37 reads, 38 RX
    wire op_rg=op<6;
    wire op_cw=op==4;
    wire op_wr=op>=6 && op<22;
    wire [3:0] op_k=op_rg ? (op==5 ? 4'd4 : 4'(op)) : op_wr ? 4'(op-6'd6) : 4'(op-6'd22);
    logic [19:0] ent;
    always_comb ent=cap[c];

    logic [7:0] hdr_ch,body_ch;
    always_comb begin
        case(hidx)
            3'd0: hdr_ch=op_cw ? "C" : op_rg ? "G" : op_wr ? "W" : "R";
            3'd1: hdr_ch=op_cw ? "0" : op==OPS-1 ? "X" : hex(op_k);
            3'd2: hdr_ch=" ";
            3'd3: hdr_ch=8'h30+8'(lat_c/10);
            3'd4: hdr_ch=8'h30+8'(lat_c%10);
            default: hdr_ch=":";
        endcase
        case(j)
            3'd0: body_ch=" ";
            3'd1: body_ch=hex(ent[19:16]);
            3'd2: body_ch=hex(ent[15:12]);
            3'd3: body_ch=hex(ent[11:8]);
            3'd4: body_ch=hex(ent[7:4]);
            default: body_ch=hex(ent[3:0]);
        endcase
    end

    always_ff @(posedge clk) begin
        if(!rst_n) begin
            st<=ST_WAIT; op<=0; cmd_en<=0; cmd<=0; cmd_reg<=0; addr<=0; wr_data<=0; lat_c<=24;
            tx_start<=0; tx_data<=0; hidx<=0; j<=0; c<=0; pause<=0;
        end else begin
            cmd_en<=0;
            tx_start<=0;
            case(st)
                ST_WAIT: if(init_calib && cmd_rdy) begin op<=0; st<=ST_ISSUE; end
                ST_ISSUE: if(cmd_rdy) begin
                    cmd_en<=1;
                    cmd_reg<=op_rg;
                    if(op_cw) begin
                        cmd<=1; lat_c<=24;
                        addr<=20'h00800; wr_data<={16'h0,CR0_TEST};
                    end else if(op_rg) begin
                        cmd<=0; lat_c<=24;
                        addr<=op==5 ? 20'h00800 : {8'h0,op[1],10'h0,op[0]};
                    end else if(op_wr) begin
                        cmd<=1; lat_c<=5'd4+5'(op_k);
                        addr<={10'(op_k),6'd0}; wr_data<=W0;
                    end else begin
                        cmd<=0; lat_c<=24;
                        addr<=op==OPS-1 ? 20'h08000 : {10'(op_k),6'd0};
                    end
                    st<=ST_BUSY;
                end
                ST_BUSY: if(!cmd_en && cmd_rdy && cap_done) begin hidx<=0; st<=ST_HDR; end
                ST_HDR: if(!tx_busy && !tx_start) begin
                    tx_data<=hdr_ch; tx_start<=1;
                    if(hidx==3'd5) begin c<=0; j<=0; st<=ST_BODY; end
                    else hidx<=hidx+1'b1;
                end
                ST_BODY: if(!tx_busy && !tx_start) begin
                    tx_data<=body_ch; tx_start<=1;
                    if(j==3'd5) begin
                        j<=0;
                        if(c==CAP-1) begin hidx<=0; st<=ST_EOL; end
                        else c<=c+1'b1;
                    end else j<=j+1'b1;
                end
                ST_EOL: if(!tx_busy && !tx_start) begin
                    tx_data<=hidx==0 ? 8'h0D : 8'h0A; tx_start<=1;
                    if(hidx==0) hidx<=1;
                    else if(op==OPS-1) begin pause<=0; st<=ST_PAUSE; end
                    else begin op<=op+1'b1; st<=ST_ISSUE; end
                end
                ST_PAUSE: begin
                    pause<=pause+1'b1;
                    if(&pause) begin op<=0; st<=ST_ISSUE; end
                end
                default: st<=ST_WAIT;
            endcase
        end
    end

    assign led_n=~{3'b0,lock,1'b0,init_calib};
endmodule
