// SPDX-License-Identifier: Apache-2.0
// External-clock UART memory test for Tang Nano 9K PSRAM (die 0).
// Standalone diagnostic and shared-PLL HDMI tops use the same engine.
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
module kagura_hyperram_memtest #(
    parameter integer WORDS_LOG2=20,
    parameter [4:0] LAT=5'd14,
    parameter [2:0] RL_MIN=3'd6,
    parameter [2:0] RL_MAX=3'd6,
    parameter       PHASE_SWEEP=1'b0,
    parameter [3:0] PHASE=4'd3
) (
    input  wire clk, clk_ck,
    input  wire rst_n,
    output logic [3:0] psda,
    output wire uart_tx,
    output wire [5:0] led_n,
    output wire [1:0] O_psram_ck,
    output wire [1:0] O_psram_ck_n,
    inout  wire [1:0] IO_psram_rwds,
    output wire [1:0] O_psram_reset_n,
    inout  wire [15:0] IO_psram_dq,
    output wire [1:0] O_psram_cs_n
);
    localparam integer BAUD_DIV=469;
    logic cmd,cmd_en,cmd_rdy,rd_data_valid,init_calib;
    logic [19:0] addr;
    logic [31:0] wr_data,rd_data;
    logic [2:0] rl;
    logic phy_reset_n,phy_cs_n,phy_ck_en,phy_dq_oe,phy_rwds_oe,phy_rwds_o_rise,phy_rwds_o_fall;
    logic [7:0] o_rise,o_fall,i_rise,i_fall;

    kagura_hyperram_ctrl #(.ADDR_WIDTH(20)) ctrl(
        .clk,.rst_n,.lat_cycles(LAT),.rd_latency(rl),.cmd,.cmd_reg(1'b0),.cmd_en,.cmd_rdy,
        .addr,.wr_data,.data_mask(4'b0),.rd_data,
        .rd_data_valid,.init_calib,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall));

    kagura_hyperram_phy_gowin phy(
        .clk,.clk_ck,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
        .phy_dq_o_rise(o_rise),.phy_dq_o_fall(o_fall),.phy_rwds_oe,.phy_rwds_o_rise,
        .phy_rwds_o_fall,.phy_dq_i_rise(i_rise),.phy_dq_i_fall(i_fall),
        .phy_rwds_i_rise(),.phy_rwds_i_fall(),
        .O_psram_ck(O_psram_ck[0]),.O_psram_ck_n(O_psram_ck_n[0]),
        .O_psram_reset_n(O_psram_reset_n[0]),.O_psram_cs_n(O_psram_cs_n[0]),
        .IO_psram_rwds(IO_psram_rwds[0]),.IO_psram_dq(IO_psram_dq[7:0]));

    assign O_psram_ck[1]=1'b0;
    assign O_psram_ck_n[1]=1'b1;
    assign O_psram_reset_n[1]=1'b0;
    assign O_psram_cs_n[1]=1'b1;
    assign IO_psram_rwds[1]=1'bz;
    assign IO_psram_dq[15:8]=8'bz;

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

    // xorshift32 of the address mixed with the pass seed
    function automatic [31:0] pattern(input [19:0] a,input [15:0] seed);
        logic [31:0] x;
        x={a[11:0],a}^{seed,~seed};
        x=x^(x<<13);
        x=x^(x>>17);
        x=x^(x<<5);
        pattern=x;
    endfunction

    typedef enum logic [2:0] {ST_WAIT,ST_WRITE,ST_READ,ST_RWAIT,ST_PREP,ST_SEND} st_t;
    st_t st;
    logic [19:0] idx;
    wire last=idx==20'((1<<WORDS_LOG2)-1);
    logic [15:0] pass;
    logic [31:0] errs,got,expv;
    logic [19:0] faddr;
    logic [7:0] msg [0:57];
    logic [5:0] sidx;
    integer k;

    always_ff @(posedge clk) begin
        if(!rst_n) begin
            st<=ST_WAIT; idx<=0; cmd_en<=0; cmd<=0; addr<=0; wr_data<=0; rl<=RL_MIN; psda<=PHASE;
            pass<=0; errs<=0; got<=0; expv<=0; faddr<=0; tx_start<=0; tx_data<=0; sidx<=0;
        end else begin
            cmd_en<=0;
            tx_start<=0;
            case(st)
                ST_WAIT: if(init_calib && cmd_rdy) begin idx<=0; st<=ST_WRITE; end
                ST_WRITE: if(cmd_rdy && !cmd_en) begin
                    cmd<=1; cmd_en<=1; addr<=idx; wr_data<=pattern(idx,pass);
                    if(last) begin idx<=0; errs<=0; got<=0; expv<=0; faddr<=0; st<=ST_READ; end
                    else idx<=idx+1'b1;
                end
                ST_READ: if(cmd_rdy && !cmd_en) begin
                    cmd<=0; cmd_en<=1; addr<=idx; st<=ST_RWAIT;
                end
                ST_RWAIT: if(rd_data_valid) begin
                    if(rd_data!=pattern(idx,pass)) begin
                        if(errs==0) begin faddr<=idx; got<=rd_data; expv<=pattern(idx,pass); end
                        errs<=errs+1'b1;
                    end
                    if(last) st<=ST_PREP;
                    else begin idx<=idx+1'b1; st<=ST_READ; end
                end
                ST_PREP: begin
                    msg[0]<="P"; msg[1]<=" ";
                    for(k=0;k<4;k=k+1) msg[2+k]<=hex(pass[15-4*k -: 4]);
                    msg[6]<=" "; msg[7]<="S"; msg[8]<=" ";
                    msg[9]<=8'h30+8'(psda/10); msg[10]<=8'h30+8'(psda%10);
                    msg[11]<=" "; msg[12]<="R"; msg[13]<=" "; msg[14]<=8'h30+8'(rl);
                    msg[15]<=" "; msg[16]<="E"; msg[17]<=" ";
                    for(k=0;k<8;k=k+1) msg[18+k]<=hex(errs[31-4*k -: 4]);
                    msg[26]<=" "; msg[27]<="A"; msg[28]<=" ";
                    for(k=0;k<5;k=k+1) msg[29+k]<=hex(faddr[19-4*k -: 4]);
                    msg[34]<=" "; msg[35]<="G"; msg[36]<=" ";
                    for(k=0;k<8;k=k+1) msg[37+k]<=hex(got[31-4*k -: 4]);
                    msg[45]<=" "; msg[46]<="X"; msg[47]<=" ";
                    for(k=0;k<8;k=k+1) msg[48+k]<=hex(expv[31-4*k -: 4]);
                    msg[56]<=8'h0D; msg[57]<=8'h0A;
                    // advance here so the new CK phase settles while the line is sent
                    pass<=pass+1'b1;
                    rl<=rl==RL_MAX ? RL_MIN : rl+1'b1;
                    if(PHASE_SWEEP && rl==RL_MAX) psda<=psda+1'b1;
                    sidx<=0;
                    st<=ST_SEND;
                end
                ST_SEND: if(!tx_busy && !tx_start) begin
                    tx_data<=msg[sidx]; tx_start<=1;
                    if(sidx==57) begin
                        idx<=0;
                        st<=ST_WRITE;
                    end else sidx<=sidx+1'b1;
                end
                default: st<=ST_WAIT;
            endcase
        end
    end

    // led_n[0] init_calib, [1] last pass clean, [2] any pass failed, [3] pass toggles
    logic clean,ever_fail;
    always_ff @(posedge clk) begin
        if(!rst_n) begin clean<=0; ever_fail<=0; end
        else if(st==ST_PREP) begin clean<=errs==0; if(errs!=0) ever_fail<=1; end
    end
    assign led_n=~{2'b0,pass[0],ever_fail,clean,init_calib};
endmodule
