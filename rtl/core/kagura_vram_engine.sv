// SPDX-License-Identifier: Apache-2.0
// Executes queued descriptors in order (docs/register-map.md). Descriptor:
// [7:0] opcode, [31:8] address, [47:32] length, [55:48] data, [63:56] flags.
// The register block validates every descriptor before enqueueing it, so
// addresses here are always inside one public region.
//   WRITE: one byte. READ: one byte, then read_done with the value.
//   FILL: `length` consecutive bytes from `address` (not INC), 0 is a no-op.
//   FENCE: all earlier commands are complete; fence_done with the tag.
//   COMMIT: wait for the next VBlank start seen while COMMIT is the head,
//     copy the OAM shadow words 0..SPRITES*4-1 to the active half above
//     them, then palette shadow words 0..255 to active 256..511, then
//     commit_done with the snapshot taken at acceptance ([31:8],[47:32]).
// Byte operations in the PSRAM region (address 400000-7FFFFF, ABI 0.4) use
// the psram_* port instead of VRAM; an accepted PSRAM write is complete for
// ordering, because the PSRAM controller finishes it before any later access.
// A FENCE also waits until the core has handed every accepted PSRAM operation to
// the controller, so accesses that start after it see earlier writes.
//   COPY (ABI 0.4, CAPS b3): `length` bytes from PSRAM `address` to VRAM at
//     {flags, data}, one PSRAM read then one VRAM write per byte.
// Later commands wait until the current one is complete.
module kagura_vram_engine #(
    parameter integer SPRITES=256
) (
    input wire clk, reset,
    input wire head_valid,
    input wire [63:0] head,
    output wire pop,
    output wire busy,
    input wire vblank_start,           // one-cycle pulse, system domain
    output wire vram_valid,
    input wire vram_ready,
    output wire vram_write, vram_word,
    output wire [15:0] vram_addr,
    output wire [15:0] vram_wdata,
    input wire vram_rsp_valid,
    input wire [15:0] vram_rdata,
    output reg read_done,
    output reg [7:0] read_data,
    output reg fence_done,
    output reg [7:0] fence_tag,
    output reg commit_done,
    output reg [39:0] commit_snapshot, // {length16, address24} of the COMMIT
    input wire vram_idle,audio_apply_ready,audio_apply_done,
    output wire audio_apply_valid,
    output reg audio_commit_done,
    output wire psram_valid,
    input wire psram_ready,
    output wire psram_write,
    output wire [21:0] psram_addr,
    output wire [7:0] psram_wdata,
    input wire psram_rsp_valid,
    input wire [7:0] psram_rdata,
    input wire psram_idle              // no accepted PSRAM operation is still waiting for the controller
);
    localparam [7:0] OP_FILL=8'h01, OP_FENCE=8'h02, OP_COMMIT=8'h03,OP_AUDIO=8'h04, OP_COPY=8'h05, OP_WRITE=8'h10, OP_READ=8'h11;
    localparam [3:0] IDLE=0, RUN=1, WAIT_READ=2, WAIT_VBLANK=3, COPY_READ=4, COPY_WAIT=5, COPY_WRITE=6,AUDIO_SEND=7,AUDIO_WAIT=8,
        X_READ=9, X_WAIT=10, X_WRITE=11;          // COPY: PSRAM read, response, VRAM write
    reg [3:0] state;
    reg [7:0] op, data;
    reg [23:0] addr;
    reg [15:0] remaining;
    reg more;                          // remaining!=0, kept with remaining (off the issue path)
    localparam integer OW=$clog2(SPRITES)+2; // OAM shadow word index bits
    reg copy_palette;                  // 0 OAM, 1 palette
    reg [OW-1:0] copy;                 // shadow word; palette uses bits 7:0
    wire copy_last=copy_palette ? &copy[7:0] : &copy;
    reg [15:0] copy_word;
    reg [15:0] dst;                    // COPY destination
    assign pop=state==IDLE && head_valid;
    assign busy=state!=IDLE;
    assign audio_apply_valid=state==AUDIO_SEND && vram_idle;
    wire byte_op=state==RUN && (op==OP_WRITE || op==OP_READ || (op==OP_FILL && more));
    wire psram_op=addr[23:22]==2'b01;
    assign vram_valid=(byte_op && !psram_op) || state==COPY_READ || state==COPY_WRITE || state==X_WRITE;
    assign psram_valid=(byte_op && psram_op) || state==X_READ;
    assign psram_write=state!=X_READ && op!=OP_READ;
    assign psram_addr=addr[21:0];
    assign psram_wdata=data;
    assign vram_word=state==COPY_READ || state==COPY_WRITE;
    assign vram_write=vram_word ? state==COPY_WRITE : op!=OP_READ;
    // Word addresses: [15] 0 OAM / 1 palette, then the word index. The active
    // half starts at word SPRITES*4 (OAM) or 256 (palette).
    assign vram_addr=!vram_word ? (state==X_WRITE ? dst : addr[15:0]) :
        copy_palette ? {1'b1,6'b0,state==COPY_WRITE,copy[7:0]} : 16'({state==COPY_WRITE,copy});
    assign vram_wdata=vram_word ? copy_word : {8'h00,data};
    wire issued=vram_valid && vram_ready || psram_valid && psram_ready;
    always @(posedge clk)
        if(reset) begin
            state<=IDLE; op<=0; data<=0; addr<=0; remaining<=0; more<=0; copy<=0; copy_palette<=0; copy_word<=0;
            read_done<=0; read_data<=0; fence_done<=0; fence_tag<=0;
            commit_done<=0; commit_snapshot<=0; audio_commit_done<=0; dst<=0;
        end else begin
            read_done<=0; fence_done<=0; commit_done<=0; audio_commit_done<=0;
            case(state)
                IDLE: if(head_valid) begin
                    op<=head[7:0]; addr<=head[31:8]; remaining<=head[47:32]; more<=head[47:32]!=0; data<=head[55:48];
                    dst<=head[63:48];
                    state<=head[7:0]==OP_COMMIT ? WAIT_VBLANK : head[7:0]==OP_AUDIO ? AUDIO_SEND :
                        head[7:0]==OP_COPY ? (head[47:32]==0 ? IDLE : X_READ) : RUN;
                end
                RUN: case(op)
                    OP_WRITE: if(issued) state<=IDLE;
                    OP_READ: if(issued) state<=WAIT_READ;
                    OP_FILL: if(!more) state<=IDLE;
                        else if(issued) begin addr<=addr+1'b1; remaining<=remaining-1'b1; more<=remaining!=1; end
                    OP_FENCE: if(psram_idle) begin fence_done<=1; fence_tag<=data; state<=IDLE; end
                    default: state<=IDLE;
                endcase
                WAIT_READ: if(vram_rsp_valid || psram_rsp_valid) begin
                    read_done<=1; read_data<=psram_op ? psram_rdata : vram_rdata[7:0]; state<=IDLE;
                end
                WAIT_VBLANK: if(vblank_start) begin copy<=0; copy_palette<=0; state<=COPY_READ; end
                COPY_READ: if(issued) state<=COPY_WAIT;
                COPY_WAIT: if(vram_rsp_valid) begin copy_word<=vram_rdata; state<=COPY_WRITE; end
                COPY_WRITE: if(issued) begin
                    copy<=copy_last ? '0 : copy+1'b1;
                    if(copy_last) copy_palette<=1;
                    if(copy_last && copy_palette) begin
                        commit_done<=1; commit_snapshot<={remaining,addr}; state<=IDLE;
                    end else state<=COPY_READ;
                end
                AUDIO_SEND: if(vram_idle && audio_apply_ready) state<=AUDIO_WAIT;
                AUDIO_WAIT: if(audio_apply_done) begin audio_commit_done<=1; state<=IDLE; end
                X_READ: if(issued) state<=X_WAIT;
                X_WAIT: if(psram_rsp_valid) begin data<=psram_rdata; state<=X_WRITE; end
                X_WRITE: if(issued) begin
                    addr<=addr+1'b1; dst<=dst+1'b1; remaining<=remaining-1'b1; more<=remaining!=1;
                    state<=remaining==1 ? IDLE : X_READ;
                end
                default: state<=IDLE;
            endcase
        end
endmodule
