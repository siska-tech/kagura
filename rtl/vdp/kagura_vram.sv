// SPDX-License-Identifier: Apache-2.0
// VRAM (docs/memory-map.md) with a command-side port and renderer ports.
//   0000-7FFF pattern  16x SP 2048x8 (bank = addr[14:11])
//   8000-8FFF map      2x 2048x8 byte lanes (word = addr[11:1])
//   A000-A7FF OAM      SPRITES*8 x16 RMW RAM (2048 for 256), shadow words
//                      0..SPRITES*4-1, active half above
//   9400-95FF palette  1024x16 RMW RAM, shadow 0..255, active 256..511;
//                      high bytes keep bits 3:0 only
//   9800-99FF wave     SP 2048x8, shadow bytes 0..511
// Command port, one operation at a time. `ready` means the input register
// is free; an accepted operation executes from that register once no RMW is
// in flight and the renderer does not hold the RAMs. Reads return rsp_valid
// after execution plus two edges (the bank mux output is registered because
// BSRAM outputs are slow). This keeps the engine's request logic away from
// the RAM enables (timing at 54MHz).
//   word=0: byte access at a public address (the register block checks it)
//   word=1: 16-bit access, addr[15]=0 OAM / 1 palette, addr[10:0] word index
//           including the active halves (used by COMMIT)
// Renderer: raise render_hold; once render_grant is high the renderer owns
// every RAM (the command port is stalled and no RMW is in flight). Each read
// port returns data one edge after its enable.
module kagura_vram #(
    parameter integer SPRITES=256
) (
    input wire clk, reset,
    output reg init_done,
    output wire command_idle,
    input wire audio_wave_read,audio_wave_swap,
    input wire [8:0] audio_wave_addr,
    output wire signed [7:0] audio_wave_data,
    input wire valid,
    output wire ready,
    input wire write_in, word_in,
    input wire [15:0] addr_in,
    input wire [15:0] wdata_in,
    output reg rsp_valid,
    output reg [15:0] rdata,
    input wire render_hold,
    output wire render_grant,
    input wire map_read,
    input wire [10:0] map_index,
    output wire [15:0] map_data,
    input wire pattern_read,
    input wire [14:0] pattern_addr,
    output wire [7:0] pattern_data,
    input wire palette_read,
    input wire [9:0] palette_index,
    output wire [15:0] palette_data,
    input wire oam_read,
    input wire [$clog2(SPRITES)+2:0] oam_index,
    output wire [15:0] oam_data
);
    wire [3:0] word_ready, word_ready_next;
    // All 16-bit RAMs idle, registered from their next-cycle prediction so the
    // execute decision does not chain through the RMW state machines.
    reg rams_idle;
    reg pending, write, word;
    reg [15:0] addr, wdata;
    // Clear physical banks in parallel through their ordinary write ports.
    // No array/reset inference: 2048 post-reset edges clear every bank.
    reg [10:0] init_index;
    wire clearing=!init_done;
    wire clear_write=clearing && !reset;
    always @(posedge clk)
        if(reset) begin init_done<=0; init_index<=0; end
        else if(clearing) begin
            if(init_index==11'd2047) init_done<=1;
            else init_index<=init_index+1'b1;
        end
    assign ready=init_done && !pending;
    assign render_grant=init_done && render_hold && rams_idle;
    assign command_idle=init_done && !pending && rams_idle;
    wire go_graphics=init_done && pending && rams_idle && !render_hold;
    wire go_wave=init_done && pending && rams_idle && is_wave && !audio_wave_read;
    wire go=(go_graphics && !is_wave) || go_wave;
    always @(posedge clk) rams_idle<=reset ? 1'b1 : &word_ready_next;
    always @(posedge clk)
        if(reset) begin pending<=0; write<=0; word<=0; addr<=0; wdata<=0; end
        else if(valid && ready) begin pending<=1; write<=write_in; word<=word_in; addr<=addr_in; wdata<=wdata_in; end
        else if(go) pending<=0;
    wire is_pattern=!word && !addr[15];
    wire is_map=!word && addr[15:12]==4'h8;
    wire is_oam=word ? !addr[15] : addr[15:12]==4'ha;          // A000-A7FF
    wire is_palette=word ? addr[15] : addr[15:9]==7'b1001_010;  // 9400-95FF
    wire is_wave=!word && addr[15:9]==7'b1001_100;               // 9800-99FF

    // Pattern banks: renderer address when granted, else the command port.
    wire [7:0] pattern_rd [0:15];
    wire [14:0] pat_a=clearing ? {4'b0,init_index} : render_grant ? pattern_addr : addr[14:0];
    // Renderer reads already include render_grant (checked below), while
    // go_graphics requires !render_hold. OR the disjoint clients directly:
    // another grant mux here would feed the RAM-idle/renderer control chain
    // back into every pattern-bank CE.
    genvar i;
    generate for(i=0;i<16;i=i+1) begin: pattern
        kagura_ram_sp #(.DEPTH(2048),.WIDTH(8)) ram(clk,
            clear_write || (pattern_read && pattern_addr[14:11]==i) ||
                (go_graphics && is_pattern && addr[14:11]==i),
            clearing || (!render_grant && write),pat_a[10:0],clearing ? 8'b0 : wdata[7:0],pattern_rd[i]);
    end endgenerate
    reg [3:0] pat_bank_q;
    always @(posedge clk) if(render_grant && pattern_read) pat_bank_q<=pattern_addr[14:11];
    assign pattern_data=pattern_rd[pat_bank_q];
    wire [7:0] wave_rd;
    reg active_wave_bank;
    always @(posedge clk)
        if(reset) active_wave_bank<=1;
        else if(audio_wave_swap) active_wave_bank<=~active_wave_bank;
    wire [10:0] wave_address=clearing ? init_index : audio_wave_read ?
        {1'b0,active_wave_bank,audio_wave_addr} : {1'b0,!active_wave_bank,addr[8:0]};
    kagura_ram_sp #(.DEPTH(2048),.WIDTH(8)) wave(clk,clear_write || audio_wave_read || (go && is_wave),
        clearing || (!audio_wave_read && write),wave_address,clearing ? 8'b0 : wdata[7:0],wave_rd);
    assign audio_wave_data=$signed(wave_rd);

    // Map: independently writable byte lanes. Both lanes read together for
    // rendering; a CPU byte write enables only its lane, without an RMW.
    // Two 2048x8 blocks use the same capacity as two 1024x16 halves.
    wire [10:0] map_addr=clearing ? init_index : render_grant ? map_index : addr[11:1];
    wire map_cpu=go_graphics && is_map;
    wire [7:0] map_low, map_high;
    kagura_ram_sp #(.DEPTH(2048),.WIDTH(8)) map_lo(clk,
        clear_write || (render_grant ? map_read : map_cpu && (!write || !addr[0])),
        clearing || (!render_grant && write),map_addr,clearing ? 8'b0 : wdata[7:0],map_low);
    kagura_ram_sp #(.DEPTH(2048),.WIDTH(8)) map_hi(clk,
        clear_write || (render_grant ? map_read : map_cpu && (!write || addr[0])),
        clearing || (!render_grant && write),map_addr,clearing ? 8'b0 : wdata[7:0],map_high);
    assign map_data={map_high,map_low};
    assign word_ready[1:0]=2'b11;
    assign word_ready_next[1:0]=2'b11;

    // Word return slots 0,1 alias the map lanes; 2 OAM, 3 palette.
    wire [3:0] word_sel={is_palette,is_oam,2'b00};
    wire [3:0] word_rsp;
    wire [15:0] word_rd [0:3];
    assign word_rd[0]=map_data;
    assign word_rd[1]=map_data;
    // OAM: SPRITES*8 words, shadow in the lower half. Palette: 1024 words.
    localparam integer OAW=$clog2(SPRITES)+3;
    wire [OAW-1:0] oam_addr=word ? addr[OAW-1:0] : {1'b0,addr[OAW-1:1]};
    wire [9:0] palette_addr=word ? addr[9:0] : {2'b00,addr[8:1]};
    reg [7:0] byte_data;
    always @* begin
        byte_data=is_palette && addr[0] ? {4'h0,wdata[3:0]} : wdata[7:0];
        if(is_oam) case(addr[2:0])
            3'd1: byte_data={6'b0,wdata[1:0]};
            3'd3: byte_data={1'b0,wdata[6:0]};
            3'd5: byte_data={2'b0,wdata[5:0]};
            3'd6,3'd7: byte_data=0;
            default: ;
        endcase
    end
    wire [15:0] word_data=is_palette ? {4'h0,wdata[11:0]} : wdata;
    wire [15:0] ram_wdata=clearing ? 16'b0 : word ? word_data : {8'h00,byte_data};
    kagura_ram_rmw16 #(.DEPTH(SPRITES*8)) oam_ram(clk,reset,clear_write || (go_graphics && word_sel[2]),word_ready[2],
        clearing || write,!clearing && !word,addr[0],clearing ? init_index[OAW-1:0] : oam_addr,
        ram_wdata,word_rsp[2],word_rd[2],word_ready_next[2],render_grant && oam_read,oam_index);
    kagura_ram_rmw16 #(.DEPTH(1024)) palette_ram(clk,reset,clear_write || (go_graphics && word_sel[3]),word_ready[3],
        clearing || write,!clearing && !word,addr[0],clearing ? init_index[9:0] : palette_addr,
        ram_wdata,word_rsp[3],word_rd[3],word_ready_next[3],render_grant && palette_read,palette_index);
    assign oam_data=word_rd[2];
    assign palette_data=word_rd[3];

    // Command-port read return: select one edge after the read, register it.
    reg [3:0] src_bank;
    reg [2:0] src_kind; // 0 pattern, 1 wave, 2..5 word RAM 0..3
    reg src_high, src_word, read_q;
    reg [15:0] rdata_mux;
    always @(posedge clk)
        if(reset) begin rsp_valid<=0; read_q<=0; rdata<=0; src_bank<=0; src_kind<=0; src_high<=0; src_word<=0; end
        else begin
            read_q<=go && !write;
            rsp_valid<=read_q;
            if(read_q) rdata<=rdata_mux;
            if(go && !write) begin
                src_bank<=addr[14:11]; src_high<=addr[0]; src_word<=word;
                src_kind<=is_pattern ? 3'd0 : is_wave ? 3'd1 : is_palette ? 3'd5 : is_oam ? 3'd4 : addr[11] ? 3'd3 : 3'd2;
            end
        end
    wire [1:0] word_index=src_kind[1:0]-2'd2; // kinds 2..5 -> RAM 0..3
    wire [15:0] src=word_rd[word_index];
    always @*
        case(src_kind)
            3'd0: rdata_mux={8'h00,pattern_rd[src_bank]};
            3'd1: rdata_mux={8'h00,wave_rd};
            default: rdata_mux=src_word ? src : {8'h00,src_high ? src[15:8] : src[7:0]};
        endcase
// synthesis translate_off
    always @(posedge clk)
        if(!reset && (map_read || pattern_read || palette_read || oam_read) && !render_grant)
            $fatal(1,"renderer read without grant");
// synthesis translate_on
endmodule
