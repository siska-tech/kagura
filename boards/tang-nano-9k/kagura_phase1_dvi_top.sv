// SPDX-License-Identifier: Apache-2.0
// P1-05 DVI baseline: kagura_phase1_top with the audio path removed. Clocks,
// reset release, serializer placement and pins are identical so the resource
// and timing difference isolates HDMI packets + audio transport.
module kagura_phase1_dvi_top (
    input wire clk27, reset_n,
    output wire tmds_clk_p,tmds_clk_n,
    output wire [2:0] tmds_d_p,tmds_d_n,
    output wire [5:0] led_n
);
    wire pixel,serial,system_clk,pixel_lock,system_lock;
    kagura_nano9k_clocks clocks(clk27,reset_n,pixel,serial,system_clk,pixel_lock,system_lock,);
    wire release_ok=reset_n && pixel_lock && system_lock;
    (* ASYNC_REG="TRUE" *) reg [3:0] pixel_release;
    always @(posedge pixel or negedge release_ok)
        if(!release_ok) pixel_release<=0; else pixel_release<={pixel_release[2:0],1'b1};
    wire tc;
    wire [2:0] tx;
    kagura_dvi_stream_eval link(pixel,serial,~pixel_release[3],tx,tc);
    ELVDS_OBUF clock_buffer(.I(tc),.O(tmds_clk_p),.OB(tmds_clk_n));
    genvar i;
    generate for(i=0;i<3;i=i+1) begin: output_lane
        ELVDS_OBUF buffer_lane(.I(tx[i]),.O(tmds_d_p[i]),.OB(tmds_d_n[i]));
    end endgenerate
    assign led_n=~{pixel_lock,system_lock,3'b000,pixel_release[3]};
endmodule
