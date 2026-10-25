// SPDX-License-Identifier: Apache-2.0
// Two-channel signed-8-bit PCM reader with a private prefetch buffer.
//
// The memory interface permits one outstanding read. A board-specific PSRAM
// wrapper supplies the variable-latency response. Configuration is accepted
// only while that channel is stopped and no read is outstanding; software
// waits for ready before asserting start so playback never depends on the
// first PSRAM access latency. Optional response timeout invalidates the owner
// but drains the late response before accepting a fresh configuration.
module kagura_pcm_prefetch #(
    parameter integer ADDR_WIDTH=24,
    parameter integer BUFFER_ADDR_BITS=8,
    parameter [ADDR_WIDTH:0] MEMORY_BYTES={1'b1,{ADDR_WIDTH{1'b0}}},
    parameter integer RESPONSE_TIMEOUT=0
) (
    input  wire clk,
    input  wire reset,
    input  wire sample_tick,

    input  wire [1:0] cfg_valid,
    output wire [1:0] cfg_ready,
    input  wire [2*ADDR_WIDTH-1:0] cfg_start,
    input  wire [2*ADDR_WIDTH-1:0] cfg_end,
    input  wire [2*ADDR_WIDTH-1:0] cfg_loop,
    input  wire [1:0] cfg_loop_enable,
    input  wire [1:0] start_play,
    input  wire [1:0] stop_play,

    output wire [1:0] ready,
    output reg  [1:0] active,
    output reg  [1:0] done,
    output reg  [1:0] underrun,
    output reg  [1:0] config_error,
    output reg  [1:0] memory_error,
    output reg  signed [7:0] sample0,
    output reg  signed [7:0] sample1,

    output reg  mem_req_valid,
    input  wire mem_req_ready,
    output reg  [ADDR_WIDTH-1:0] mem_req_addr,
    input  wire mem_rsp_valid,
    input  wire [7:0] mem_rsp_data,
    input  wire mem_rsp_error
);
    localparam integer BUFFER_DEPTH=1<<BUFFER_ADDR_BITS;
    localparam integer COUNT_WIDTH=BUFFER_ADDR_BITS+1;
    localparam integer TIMEOUT_WIDTH=RESPONSE_TIMEOUT>0 ? $clog2(RESPONSE_TIMEOUT+1) : 1;
    localparam [COUNT_WIDTH-1:0] BUFFER_DEPTH_COUNT=COUNT_WIDTH'(BUFFER_DEPTH);

    reg [7:0] buffer0 [0:BUFFER_DEPTH-1];
    reg [7:0] buffer1 [0:BUFFER_DEPTH-1];
    reg [BUFFER_ADDR_BITS-1:0] rd_ptr [0:1];
    reg [BUFFER_ADDR_BITS-1:0] wr_ptr [0:1];
    reg [COUNT_WIDTH-1:0] count [0:1];
    reg [ADDR_WIDTH-1:0] end_addr [0:1];   // last byte (END-1)
    reg [ADDR_WIDTH-1:0] loop_addr [0:1];
    reg [ADDR_WIDTH-1:0] fetch_addr [0:1];
    // Next fetch address and END flag, registered from fetch_addr. A channel
    // issues at most one request per response, so after each address change
    // (configure or issue) the copy is one cycle stale and next_ok blocks it.
    reg [ADDR_WIDTH-1:0] fetch_next [0:1];
    reg [1:0] fetch_last,next_ok;
    reg [1:0] loop_enable;
    reg [1:0] configured;
    reg [1:0] fetch_done;
    reg outstanding;
    reg outstanding_ch;
    reg discard_response;
    reg [TIMEOUT_WIDTH-1:0] timeout_count;
    reg rr;
    reg selected_valid;
    reg selected_ch;

    // A channel stopped on a sample tick does not consume that sample, so a
    // pause on the AUDIO_COMMIT boundary resumes without a gap.
    wire pop0=sample_tick && active[0] && !stop_play[0];
    wire pop1=sample_tick && active[1] && !stop_play[1];
    wire push0=mem_rsp_valid && outstanding && !discard_response && !mem_rsp_error && !outstanding_ch;
    wire push1=mem_rsp_valid && outstanding && !discard_response && !mem_rsp_error && outstanding_ch;
    // A request is issued only with no read outstanding, so the space a channel
    // needs is simply count < depth: the MSB of count (count <= depth).
    wire need0=configured[0] && next_ok[0] && !fetch_done[0] && !count[0][COUNT_WIDTH-1];
    wire need1=configured[1] && next_ok[1] && !fetch_done[1] && !count[1][COUNT_WIDTH-1];

    assign cfg_ready={2{!outstanding}} & ~active;
    assign ready[0]=configured[0] && (count[0]==BUFFER_DEPTH_COUNT || fetch_done[0]);
    assign ready[1]=configured[1] && (count[1]==BUFFER_DEPTH_COUNT || fetch_done[1]);

    always @* begin
        selected_valid=0;
        selected_ch=0;
        if(need0 && need1) begin selected_valid=1; selected_ch=rr; end
        else if(need0) begin selected_valid=1; selected_ch=0; end
        else if(need1) begin selected_valid=1; selected_ch=1; end
        mem_req_valid=!outstanding && selected_valid;
        mem_req_addr=selected_ch ? fetch_addr[1] : fetch_addr[0];
    end

    always @(posedge clk) begin
        for(int c=0;c<2;c=c+1) begin
            fetch_last[c]<=fetch_addr[c]==end_addr[c];
            fetch_next[c]<=fetch_addr[c]==end_addr[c] ? loop_addr[c] : fetch_addr[c]+1'b1;
        end
        next_ok[0]<=!reset && !(cfg_valid[0] && cfg_ready[0]) && !(mem_req_valid && mem_req_ready && !selected_ch);
        next_ok[1]<=!reset && !(cfg_valid[1] && cfg_ready[1]) && !(mem_req_valid && mem_req_ready && selected_ch);
    end

    integer i;
    always @(posedge clk) begin
        if(reset) begin
            active<=0; done<=0; underrun<=0; config_error<=0; memory_error<=0;
            sample0<=0; sample1<=0; loop_enable<=0; configured<=0; fetch_done<=0;
            outstanding<=0; outstanding_ch<=0; discard_response<=0; timeout_count<=0; rr<=0;
            for(i=0;i<2;i=i+1) begin
                rd_ptr[i]<=0; wr_ptr[i]<=0; count[i]<=0;
                end_addr[i]<=0; loop_addr[i]<=0; fetch_addr[i]<=0;
            end
        end else begin
            done<=0; underrun<=0; config_error<=0; memory_error<=0;

            for(i=0;i<2;i=i+1) begin
                if(cfg_valid[i] && cfg_ready[i]) begin
                    rd_ptr[i]<=0; wr_ptr[i]<=0; count[i]<=0; fetch_done[i]<=0;
                    if(cfg_start[i*ADDR_WIDTH +: ADDR_WIDTH]>=cfg_end[i*ADDR_WIDTH +: ADDR_WIDTH] ||
                       {1'b0,cfg_end[i*ADDR_WIDTH +: ADDR_WIDTH]}>MEMORY_BYTES ||
                       (cfg_loop_enable[i] &&
                        (cfg_loop[i*ADDR_WIDTH +: ADDR_WIDTH]<cfg_start[i*ADDR_WIDTH +: ADDR_WIDTH] ||
                         cfg_loop[i*ADDR_WIDTH +: ADDR_WIDTH]>=cfg_end[i*ADDR_WIDTH +: ADDR_WIDTH]))) begin
                        configured[i]<=0;
                        config_error[i]<=1;
                    end else begin
                        end_addr[i]<=cfg_end[i*ADDR_WIDTH +: ADDR_WIDTH]-1'b1;
                        loop_addr[i]<=cfg_loop[i*ADDR_WIDTH +: ADDR_WIDTH];
                        fetch_addr[i]<=cfg_start[i*ADDR_WIDTH +: ADDR_WIDTH];
                        loop_enable[i]<=cfg_loop_enable[i];
                        configured[i]<=1;
                    end
                end else if(cfg_valid[i] && !cfg_ready[i]) config_error[i]<=1;

                if(stop_play[i]) begin
                    active[i]<=0;
                    if(i==0) sample0<=0; else sample1<=0;
                end
                if(start_play[i]) begin
                    if(ready[i] && !active[i]) active[i]<=1;
                    else config_error[i]<=1;
                end
            end

            if(mem_req_valid && mem_req_ready) begin
                outstanding<=1;
                outstanding_ch<=selected_ch;
                discard_response<=0;
                timeout_count<=0;
                rr<=~selected_ch;
                if(fetch_last[selected_ch]) begin
                    if(loop_enable[selected_ch]) fetch_addr[selected_ch]<=fetch_next[selected_ch];
                    else fetch_done[selected_ch]<=1;
                end else fetch_addr[selected_ch]<=fetch_next[selected_ch];
            end

            if(mem_rsp_valid && outstanding) begin
                outstanding<=0;
                timeout_count<=0;
                if(discard_response) begin
                    discard_response<=0;
                end else if(mem_rsp_error) begin
                    memory_error[outstanding_ch]<=1;
                    fetch_done[outstanding_ch]<=1;
                    configured[outstanding_ch]<=0;
                    active[outstanding_ch]<=0;
                    if(outstanding_ch) sample1<=0; else sample0<=0;
                end else if(outstanding_ch) begin
                    buffer1[wr_ptr[1]]<=mem_rsp_data;
                    wr_ptr[1]<=wr_ptr[1]+1'b1;
                end else begin
                    buffer0[wr_ptr[0]]<=mem_rsp_data;
                    wr_ptr[0]<=wr_ptr[0]+1'b1;
                end
            end else if(outstanding && RESPONSE_TIMEOUT>0 && !discard_response) begin
                if(timeout_count==TIMEOUT_WIDTH'(RESPONSE_TIMEOUT-1)) begin
                    discard_response<=1;
                    memory_error[outstanding_ch]<=1;
                    fetch_done[outstanding_ch]<=1;
                    configured[outstanding_ch]<=0;
                    active[outstanding_ch]<=0;
                    if(outstanding_ch) sample1<=0; else sample0<=0;
                end else timeout_count<=timeout_count+1'b1;
            end

            if(pop0) begin
                if(count[0]!=0) begin sample0<=$signed(buffer0[rd_ptr[0]]); rd_ptr[0]<=rd_ptr[0]+1'b1; end
                else begin sample0<=0; active[0]<=0; underrun[0]<=1; end
            end else if(sample_tick && !active[0]) sample0<=0;
            if(pop1) begin
                if(count[1]!=0) begin sample1<=$signed(buffer1[rd_ptr[1]]); rd_ptr[1]<=rd_ptr[1]+1'b1; end
                else begin sample1<=0; active[1]<=0; underrun[1]<=1; end
            end else if(sample_tick && !active[1]) sample1<=0;

            case({push0,pop0 && count[0]!=0})
                2'b10: count[0]<=count[0]+1'b1;
                2'b01: count[0]<=count[0]-1'b1;
                default: ;
            endcase
            case({push1,pop1 && count[1]!=0})
                2'b10: count[1]<=count[1]+1'b1;
                2'b01: count[1]<=count[1]-1'b1;
                default: ;
            endcase

            if(pop0 && count[0]==1 && fetch_done[0] && !push0) begin active[0]<=0; done[0]<=1; end
            if(pop1 && count[1]==1 && fetch_done[1] && !push1) begin active[1]<=0; done[1]<=1; end
        end
    end

// synthesis translate_off
    always @(posedge clk) begin
        if(!reset && mem_rsp_valid && !outstanding) $fatal(1,"PCM memory response without request");
        if(!reset && count[0]>BUFFER_DEPTH_COUNT) $fatal(1,"PCM channel 0 buffer overflow");
        if(!reset && count[1]>BUFFER_DEPTH_COUNT) $fatal(1,"PCM channel 1 buffer overflow");
    end
// synthesis translate_on
endmodule
