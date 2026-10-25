// SPDX-License-Identifier: Apache-2.0
// Pixel-paced audio delivery: one stereo sample per 48kHz tick, every
// TICK_NUM/TICK_DEN pixel clocks (525/1 at 25.2MHz, 12375/8 at 74.25MHz).
// Starts muted and unmutes once PREFILL samples are buffered. A tick that
// cannot be served while unmuted emits silence, sets sticky underflow and
// re-enters mute until the FIFO is prefilled again. Muted ticks emit silence
// without flagging an error.
module kagura_audio_transport #(
    parameter integer TICK_NUM=525,
    parameter integer TICK_DEN=1,
    parameter integer PREFILL=4
) (
    input wire reset, clk_system, clk_pixel,
    input wire sample_valid,
    input wire [31:0] sample_data,
    output wire full, overflow,
    output reg pixel_valid,
    output reg [31:0] pixel_data,
    input wire pixel_ready,
    output wire underflow,
    output reg muted,
    output reg underflow_toggle
);
    wire empty;
    wire response_valid;
    wire [31:0] response_data;
    wire [4:0] level;
    wire fifo_underflow;
    reg pending,starved;
    // Fractional divider: tick when the accumulator passes TICK_NUM.
    reg [13:0] tick_acc;
    // Due samples not yet handed over; bounded by the packet slot latency.
    reg [2:0] credits;
    // tick_acc < TICK_NUM, so acc+DEN >= NUM is acc >= NUM-DEN: the compare
    // and the constant adds run in parallel instead of in series (74.25MHz).
    wire tick=tick_acc>=14'(TICK_NUM-TICK_DEN);
    wire [13:0] tick_step=tick_acc+14'(TICK_DEN);
    wire [13:0] tick_wrap=tick_acc+14'(TICK_DEN-TICK_NUM);
    wire issue=!pending && !pixel_valid && pixel_ready && credits!=0;
    wire pop=!reset && issue && !muted && !empty;
    wire fill=issue && (muted || empty);
    kagura_async_fifo fifo(.reset(reset),.write_clk(clk_system),
        .write_enable(sample_valid),.write_data(sample_data),.full(full),.overflow(overflow),
        .read_clk(clk_pixel),.read_enable(pop),.read_data(response_data),
        .read_valid(response_valid),.empty(empty),.underflow(fifo_underflow),
        .read_level(level));
    assign underflow=fifo_underflow || starved;
    always @(posedge clk_pixel or posedge reset)
        if(reset) begin
            pending<=0; pixel_valid<=0; pixel_data<=0; muted<=1; starved<=0;
            tick_acc<=0; credits<=0; underflow_toggle<=0;
        end else begin
            tick_acc<=tick ? tick_wrap : tick_step;
            // Each new loss toggles independently of legacy sticky flags so
            // software can clear/re-arm its system-domain AUDIO_STATUS bits.
            if((tick && !issue && credits==3'd7) || (fill && !muted)) underflow_toggle<=~underflow_toggle;
            // A saturated credit counter means a deadline was lost.
            if(tick && !issue && credits==3'd7) starved<=1;
            else credits<=credits+{2'b0,tick}-{2'b0,issue};
            if(pixel_valid && pixel_ready) pixel_valid<=0;
            if(pop) pending<=1;
            if(response_valid) begin
                pending<=0; pixel_valid<=1; pixel_data<=response_data;
            end
            if(fill) begin pixel_valid<=1; pixel_data<=0; end
            if(muted) begin
                if(level>=PREFILL) muted<=0;
            end else if(fill) begin
                muted<=1; starved<=1;
            end
        end
endmodule
