// SPDX-License-Identifier: Apache-2.0
// Ordered command queue: 32 descriptors x 64 bit in distributed 128x16 RAM,
// four words per entry (word0 = bits 15:0). A push lands in a staging
// register and is written over four edges; the write pointer advances only
// after the fourth word, so a half-written entry is never visible. The
// staging entry counts against `free` (FIFO_STATUS includes it).
// The writer has priority on the RAM port; the reader fetches the head entry
// word by word whenever the port is free and presents it until `pop`.
// The register block stalls new requests while `staging` is set, so a push
// never meets a busy staging register and FULL means 32 stored entries.
module kagura_command_queue (
    input wire clk, reset,
    input wire push,
    input wire [63:0] push_desc,
    output wire push_ready,
    output wire [5:0] free,
    output wire idle,             // no entry stored, staged or presented
    output wire staging,
    output reg head_valid,
    output reg [63:0] head,
    input wire pop
);
    reg [5:0] wptr, rptr;
    reg stage_valid;
    reg [63:0] stage;
    reg [1:0] stage_word;
    reg [2:0] fetch_issued;       // words of the head requested so far
    reg read_pending;
    reg [1:0] read_word;
    wire [5:0] count=wptr-rptr;
    assign free=6'd32-count-{5'b0,stage_valid};
    assign push_ready=!stage_valid && count!=6'd32;
    assign idle=count==0 && !stage_valid;
    assign staging=stage_valid;
    wire writing=stage_valid;
    wire fetch=!writing && !head_valid && count!=0 && fetch_issued!=3'd4;
    wire [6:0] ram_addr=writing ? {wptr[4:0],stage_word} : {rptr[4:0],fetch_issued[1:0]};
    // Retain the existing registered read and four-word staging protocol.
    // The explicit style is an experiment: verify SSRAM/BSRAM in synthesis.
    (* syn_ramstyle = "distributed_ram" *) reg [15:0] memory [0:127];
    reg [15:0] ram_rd;
    always @(posedge clk)
        if(writing || fetch) begin
            if(writing) memory[ram_addr]<=stage[16*stage_word +: 16];
            ram_rd<=memory[ram_addr];
        end
    always @(posedge clk)
        if(reset) begin
            wptr<=0; rptr<=0; stage_valid<=0; stage<=0; stage_word<=0;
            fetch_issued<=0; read_pending<=0; read_word<=0; head_valid<=0; head<=0;
        end else begin
            if(push && push_ready) begin stage_valid<=1; stage<=push_desc; stage_word<=0; end
            if(writing) begin
                stage_word<=stage_word+1'b1;
                if(stage_word==2'd3) begin stage_valid<=0; wptr<=wptr+1'b1; end
            end
            read_pending<=fetch;
            if(fetch) begin read_word<=fetch_issued[1:0]; fetch_issued<=fetch_issued+1'b1; end
            if(read_pending) begin
                head[16*read_word +: 16]<=ram_rd;
                if(read_word==2'd3) head_valid<=1;
            end
            if(pop && head_valid) begin head_valid<=0; rptr<=rptr+1'b1; fetch_issued<=0; end
        end
// synthesis translate_off
    always @(posedge clk)
        if(!reset && push && !push_ready && count!=6'd32)
            $fatal(1,"command queue push while staging busy");
// synthesis translate_on
endmodule
