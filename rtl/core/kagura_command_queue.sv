// SPDX-License-Identifier: Apache-2.0
// 32 ordered descriptors in distributed 32x64 RAM. Keep the four-cycle
// staging window, including its contribution to FIFO_STATUS, but store/fetch
// whole descriptors. This removes the 64:16 staging mux and the four-word
// head assembly logic, reducing placement pressure in the 1200-tile build.
module kagura_command_queue (
    input wire clk, reset,
    input wire push,
    input wire [63:0] push_desc,
    output wire push_ready,
    output wire [5:0] free,
    output wire idle,
    output wire staging,
    output reg head_valid,
    output reg [63:0] head,
    input wire pop
);
    reg [5:0] wptr, rptr;
    reg stage_valid;
    reg [63:0] stage;
    reg [1:0] stage_cycle;
    wire [5:0] count=wptr-rptr;
    assign free=6'd32-count-{5'b0,stage_valid};
    assign push_ready=!stage_valid && count!=6'd32;
    assign idle=count==0 && !stage_valid;
    assign staging=stage_valid;
    wire store=stage_valid && stage_cycle==2'd3;
    wire fetch=!stage_valid && !head_valid && count!=0;
    (* syn_ramstyle = "distributed_ram" *) reg [63:0] memory [0:31];
    always @(posedge clk)
        if(!reset && store) memory[wptr[4:0]]<=stage;
    always @(posedge clk)
        if(reset) begin
            wptr<=0; rptr<=0; stage_valid<=0; stage<=0; stage_cycle<=0;
            head_valid<=0; head<=0;
        end else begin
            if(push && push_ready) begin stage_valid<=1; stage<=push_desc; stage_cycle<=0; end
            if(stage_valid) begin
                stage_cycle<=stage_cycle+1'b1;
                if(store) begin stage_valid<=0; wptr<=wptr+1'b1; end
            end
            if(fetch) begin head<=memory[rptr[4:0]]; head_valid<=1; end
            if(pop && head_valid) begin head_valid<=0; rptr<=rptr+1'b1; end
        end
// synthesis translate_off
    always @(posedge clk)
        if(!reset && push && !push_ready && count!=6'd32)
            $fatal(1,"command queue push while staging busy");
// synthesis translate_on
endmodule
