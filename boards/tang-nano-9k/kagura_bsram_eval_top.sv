// SPDX-License-Identifier: Apache-2.0
// P1-06 mapping test: the 25-block VRAM/audio plan from docs/memory-map.md on
// the real system/pixel clocks. LFSRs drive every port; each RAM stores
// distinct data so synthesis cannot merge equivalent instances, and all read
// data is folded into the LEDs so nothing is swept. Not a functional design.
module kagura_bsram_eval_top (
    input wire clk27, reset_n,
    output wire [5:0] led_n
);
    wire pixel,serial,system_clk,pixel_lock,system_lock;
    kagura_nano9k_clocks clocks(clk27,reset_n,pixel,serial,system_clk,pixel_lock,system_lock);
    wire release_ok=reset_n && pixel_lock && system_lock;
    (* ASYNC_REG="TRUE" *) reg [3:0] pixel_release,system_release;
    always @(posedge pixel or negedge release_ok)
        if(!release_ok) pixel_release<=0; else pixel_release<={pixel_release[2:0],1'b1};
    always @(posedge system_clk or negedge release_ok)
        if(!release_ok) system_release<=0; else system_release<={system_release[2:0],1'b1};
    wire sys_reset=~system_release[3], pix_reset=~pixel_release[3];
    reg [31:0] sl=32'h1, pl=32'h1;
    always @(posedge system_clk) sl<=sys_reset ? 32'h1 : {sl[30:0],sl[31]^sl[21]^sl[1]^sl[0]};
    always @(posedge pixel) pl<=pix_reset ? 32'h1 : {pl[30:0],pl[31]^pl[21]^pl[1]^pl[0]};

    // 16 pattern RAMs, SP 2048x8.
    wire [7:0] pattern_rd [0:15];
    reg [7:0] pattern_fold;
    genvar i;
    generate for(i=0;i<16;i=i+1) begin: pattern
        kagura_ram_sp #(.DEPTH(2048),.WIDTH(8)) ram(system_clk,sl[31],sl[30]&&sl[i],
            sl[10:0],sl[19:12]^8'(i*37+1),pattern_rd[i]);
    end endgenerate
    integer k;
    always @* begin pattern_fold=0; for(k=0;k<16;k=k+1) pattern_fold=pattern_fold^pattern_rd[k]; end

    // Map x2, OAM, palette: 1024x16 with atomic byte RMW.
    wire [15:0] rmw_rd [0:3];
    wire [3:0] rmw_ready,rmw_valid;
    generate for(i=0;i<4;i=i+1) begin: word_ram
        kagura_ram_rmw16 #(.DEPTH(1024)) ram(system_clk,sys_reset,sl[29],rmw_ready[i],
            sl[28],sl[27],sl[26],sl[9:0]^10'(i*97),sl[31:16]^16'(i*4099+5),rmw_valid[i],rmw_rd[i],,1'b0,10'd0);
    end endgenerate

    // Wave SP 2048x8, command queue SP 1024x16.
    wire [7:0] wave_rd;
    wire [15:0] command_rd;
    kagura_ram_sp #(.DEPTH(2048),.WIDTH(8)) wave(system_clk,sl[25],sl[24],sl[20:10],sl[7:0]^8'h3c,wave_rd);
    kagura_ram_sp #(.DEPTH(1024),.WIDTH(16)) command(system_clk,sl[23],sl[22],sl[19:10],sl[15:0]^16'ha5c3,command_rd);

    // Line banks: 2x TDP 1024x16, system RW / pixel R with handover.
    wire line_can,line_underrun;
    wire [15:0] line_sys_rd,line_pix_rd;
    kagura_line_banks lines(system_clk,sys_reset,line_can,sl[21]&&line_can,sl[20],sl[9:0],sl[31:16],
        line_sys_rd,sl[5]&&sl[4]&&line_can,
        pixel,pix_reset,pl[31]&&pl[30],pl[29],pl[9:0],line_pix_rd,line_underrun);

    // Audio FIFO storage: SDP 512x32, write system / read pixel.
    wire [31:0] fifo_rd;
    kagura_ram_sdp #(.DEPTH(512),.WIDTH(32)) audio(system_clk,sl[19],sl[8:0],sl^32'h1234_5678,
        pixel,pl[28],pl[8:0],fifo_rd);

    reg [5:0] sys_fold,pix_fold;
    always @(posedge system_clk)
        sys_fold<=pattern_fold[5:0]^rmw_rd[0][5:0]^rmw_rd[1][11:6]^rmw_rd[2][15:10]^rmw_rd[3][5:0]
            ^{rmw_ready,rmw_valid[1:0]}^wave_rd[5:0]^command_rd[11:6]^line_sys_rd[5:0]^{5'b0,line_can};
    always @(posedge pixel)
        pix_fold<=line_pix_rd[5:0]^line_pix_rd[11:6]^fifo_rd[5:0]^fifo_rd[17:12]^fifo_rd[31:26]^{5'b0,line_underrun};
    assign led_n=sys_fold^pix_fold;
endmodule
