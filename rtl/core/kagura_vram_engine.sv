// SPDX-License-Identifier: Apache-2.0
// Executes queued descriptors in order (docs/register-map.md). Descriptor:
// [7:0] opcode, [31:8] address, [47:32] length, [55:48] data, [63:56] flags.
// The register block validates every descriptor before enqueueing it, so
// addresses here are always inside one public region.
//   WRITE: one byte. READ: one byte, then read_done with the value.
//   FILL: `length` consecutive bytes from `address` (not INC), 0 is a no-op.
//   FENCE: all earlier commands are complete; fence_done with the tag.
//   COMMIT: wait for the next VBlank start seen while COMMIT is the head,
//     copy OAM and palette shadow words 0..255 to active 256..511, then
//     commit_done with the snapshot taken at acceptance ([31:8],[47:32]).
// Byte operations in the PSRAM region (address 400000-7FFFFF, ABI 0.4) use
// the psram_* port instead of VRAM; an accepted PSRAM write is complete for
// ordering, because the PSRAM controller finishes it before any later access.
// Later commands wait until the current one is complete.
module kagura_vram_engine (
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
    input wire [7:0] psram_rdata
);
    localparam [7:0] OP_FILL=8'h01, OP_FENCE=8'h02, OP_COMMIT=8'h03,OP_AUDIO=8'h04, OP_WRITE=8'h10, OP_READ=8'h11;
    localparam [3:0] IDLE=0, RUN=1, WAIT_READ=2, WAIT_VBLANK=3, COPY_READ=4, COPY_WAIT=5, COPY_WRITE=6,AUDIO_SEND=7,AUDIO_WAIT=8;
    reg [3:0] state;
    reg [7:0] op, data;
    reg [23:0] addr;
    reg [15:0] remaining;
    reg [8:0] copy;                    // bit 8: 0 OAM, 1 palette; bits 7:0 word
    reg [15:0] copy_word;
    assign pop=state==IDLE && head_valid;
    assign busy=state!=IDLE;
    assign audio_apply_valid=state==AUDIO_SEND && vram_idle;
    wire byte_op=state==RUN && (op==OP_WRITE || op==OP_READ || (op==OP_FILL && remaining!=0));
    wire psram_op=addr[23:22]==2'b01;
    assign vram_valid=(byte_op && !psram_op) || state==COPY_READ || state==COPY_WRITE;
    assign psram_valid=byte_op && psram_op;
    assign psram_write=op!=OP_READ;
    assign psram_addr=addr[21:0];
    assign psram_wdata=data;
    assign vram_word=state==COPY_READ || state==COPY_WRITE;
    assign vram_write=vram_word ? state==COPY_WRITE : op!=OP_READ;
    // Word addresses: [15] 0 OAM / 1 palette, [9:0] word index.
    assign vram_addr=vram_word ? {copy[8],6'b0,state==COPY_WRITE,copy[7:0]} : addr[15:0]; // active = +256
    assign vram_wdata=vram_word ? copy_word : {8'h00,data};
    wire issued=vram_valid && vram_ready || psram_valid && psram_ready;
    always @(posedge clk)
        if(reset) begin
            state<=IDLE; op<=0; data<=0; addr<=0; remaining<=0; copy<=0; copy_word<=0;
            read_done<=0; read_data<=0; fence_done<=0; fence_tag<=0;
            commit_done<=0; commit_snapshot<=0; audio_commit_done<=0;
        end else begin
            read_done<=0; fence_done<=0; commit_done<=0; audio_commit_done<=0;
            case(state)
                IDLE: if(head_valid) begin
                    op<=head[7:0]; addr<=head[31:8]; remaining<=head[47:32]; data<=head[55:48];
                    state<=head[7:0]==OP_COMMIT ? WAIT_VBLANK : head[7:0]==OP_AUDIO ? AUDIO_SEND : RUN;
                end
                RUN: case(op)
                    OP_WRITE: if(issued) state<=IDLE;
                    OP_READ: if(issued) state<=WAIT_READ;
                    OP_FILL: if(remaining==0) state<=IDLE;
                        else if(issued) begin addr<=addr+1'b1; remaining<=remaining-1'b1; end
                    OP_FENCE: begin fence_done<=1; fence_tag<=data; state<=IDLE; end
                    default: state<=IDLE;
                endcase
                WAIT_READ: if(vram_rsp_valid || psram_rsp_valid) begin
                    read_done<=1; read_data<=psram_op ? psram_rdata : vram_rdata[7:0]; state<=IDLE;
                end
                WAIT_VBLANK: if(vblank_start) begin copy<=0; state<=COPY_READ; end
                COPY_READ: if(issued) state<=COPY_WAIT;
                COPY_WAIT: if(vram_rsp_valid) begin copy_word<=vram_rdata; state<=COPY_WRITE; end
                COPY_WRITE: if(issued) begin
                    copy<=copy+1'b1;
                    if(copy==9'h1ff) begin
                        commit_done<=1; commit_snapshot<={remaining,addr}; state<=IDLE;
                    end else state<=COPY_READ;
                end
                AUDIO_SEND: if(vram_idle && audio_apply_ready) state<=AUDIO_WAIT;
                AUDIO_WAIT: if(audio_apply_done) begin audio_commit_done<=1; state<=IDLE; end
                default: state<=IDLE;
            endcase
        end
endmodule
