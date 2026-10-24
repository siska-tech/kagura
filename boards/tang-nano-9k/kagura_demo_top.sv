// SPDX-License-Identifier: Apache-2.0
// Hardware test top without a CPU: kagura_demo_sequencer writes VRAM through
// the register window, animates the shooter scene every frame and plays the
// demo song, shown with the Phase 1 HDMI/48kHz stream. Instance names of the
// stream and VDP match kagura_phase2_top so phase1*.sdc/phase3-vdp.sdc and
// the CST apply.
// VIDEO_ID_CODE comes from kagura_build_config (tools/build-nano9k.tcl).
// LEDs (active low): 5 pixel lock, 4 system lock, 3 map read-back mismatch or
// (scene) sprites dropped by the 16/line limit in the last frame,
// 2 pattern/palette read-back mismatch, 1 blinks with the committed frame
// count, 0 pixel reset. (Audio flags are not shown in this diagnostic top;
// the scene skips the read-back checks, so LED 2 stays off.)
// Board labels are one-based: LED1 reset released, LED2 frame blink,
// LED3 data mismatch, LED4 map mismatch / sprite overflow, LED5 system lock,
// LED6 pixel lock.
module kagura_demo_top #(
    parameter integer VIDEO_ID_CODE=kagura_build_config::VIDEO_ID_CODE,
    localparam integer XW=VIDEO_ID_CODE==4 ? 11 : 10
) (
    input wire clk27, reset_n,
    output wire tmds_clk_p,tmds_clk_n,
    output wire [2:0] tmds_d_p,tmds_d_n,
    output wire [5:0] led_n
);
    wire pixel,serial,system_clk,pixel_lock,system_lock;
    kagura_nano9k_clocks #(.VIDEO_ID_CODE(VIDEO_ID_CODE)) clocks(clk27,reset_n,pixel,serial,system_clk,pixel_lock,system_lock);
    wire release_ok=reset_n && pixel_lock && system_lock;
    (* ASYNC_REG="TRUE" *) reg [3:0] pixel_release,system_release;
    always @(posedge pixel or negedge release_ok)
        if(!release_ok) pixel_release<=0; else pixel_release<={pixel_release[2:0],1'b1};
    always @(posedge system_clk or negedge release_ok)
        if(!release_ok) system_release<=0; else system_release<={system_release[2:0],1'b1};
    wire valid,full,overflow,underflow,muted,tc,audio_uf_toggle;
    wire [2:0] tx;
    wire [15:0] left_sample,right_sample;
    wire [XW-1:0] cx;
    wire [9:0] cy;
    wire [23:0] vdp_rgb;
    kagura_hdmi_stream_eval #(.EXTERNAL_RGB(1),.VIDEO_ID_CODE(VIDEO_ID_CODE)) link(system_clk,pixel,serial,~pixel_release[3],valid,
        {right_sample,left_sample},full,overflow,underflow,tx,tc,muted,vdp_rgb,cx,cy,audio_uf_toggle);
    ELVDS_OBUF clock_buffer(.I(tc),.O(tmds_clk_p),.OB(tmds_clk_n));
    genvar i;
    generate for(i=0;i<3;i=i+1) begin: output_lane
        ELVDS_OBUF buffer_lane(.I(tx[i]),.O(tmds_d_p[i]),.OB(tmds_d_n[i]));
    end endgenerate

    wire sys_reset=~system_release[3];
    wire req_valid,req_ready,req_write,rsp_valid,rsp_error,irq,configured,map_bad,data_bad,sprite_overflow;
    wire [4:0] req_addr;
    wire [7:0] req_wdata,rsp_rdata;
    wire [15:0] frames;
    wire [11:0] render_cycles;
    kagura_demo_sequencer #(.SPRITES(1),.AUDIO(1),.SCENE(1),.RASTER(1),.LINES(VIDEO_ID_CODE==4 ? 180 : 240)) sequencer(.clk(system_clk),.reset(sys_reset),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_rdata(rsp_rdata),.rsp_error(rsp_error),
        .configured(configured),.frames(frames),.map_bad(map_bad),.data_bad(data_bad),.sprite_overflow(sprite_overflow),
        .map_readback(),.map_written());
    // CAPS: HDMI_AUDIO, WAVE, 16 sprites per line, WIDE, raster scroll for 320x180.
    kagura_vdp #(.CAPS(VIDEO_ID_CODE==4 ? 8'h73 : 8'h53),.VIDEO_ID_CODE(VIDEO_ID_CODE)) vdp(.sys_clk(system_clk),.sys_reset(sys_reset),
        .req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.render_cycles(render_cycles),
        .audio_full(full),.audio_underflow_toggle(audio_uf_toggle),.audio_muted(muted),
        .audio_sample_valid(valid),.audio_left(left_sample),.audio_right(right_sample),.audio_status(),
        .pix_clk(pixel),.pix_reset(~pixel_release[3]),.cx(cx),.cy(cy),.rgb(vdp_rgb));
    assign led_n=~{pixel_lock,system_lock,map_bad || sprite_overflow,data_bad,frames[5],pixel_release[3]};
endmodule
