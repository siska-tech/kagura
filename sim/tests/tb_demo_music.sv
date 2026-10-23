// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
// kagura_demo_sequencer AUDIO=1 + kagura_vdp + audio FIFO: runs the song
// player for +frames=N committed frames (default 30) and writes every PCM
// sample the core produced after configuration to
// build/verilator/demo-music.raw (wrap with tools/render-audio-wav.py).
// Checks: no FIFO under/overflow, no ERROR_CODE, no clipped sample, the
// song really changes notes (several distinct ch0/ch4 steps committed).
module tb_demo_music;
    reg sys=0, pix=0;
    // Exactly 54:25.2 (15:7) as on the board, where both come from one PLL
    // input: system/1125 makes and pixel/525 takes the 48kHz samples, so any
    // ratio error would fill or drain the FIFO during a long run.
    always #9.261 sys=~sys;
    always #19.845 pix=~pix;
    reg sys_reset=1, pix_reset=1;
    wire req_valid, req_ready, req_write, rsp_valid, rsp_error, irq, configured, map_bad, data_bad;
    wire [4:0] req_addr; wire [7:0] req_wdata, rsp_rdata;
    wire [15:0] frames; wire [11:0] render_cycles;
    reg [9:0] cx=0, cy=0;
    wire [23:0] rgb;
    wire audio_full,audio_uf,audio_muted,audio_valid,ov,underflow,pv;
    wire signed [15:0] audio_l,audio_r;
    wire [31:0] pd;
    kagura_audio_transport transport(.reset(sys_reset || pix_reset),.clk_system(sys),.clk_pixel(pix),
        .sample_valid(audio_valid),.sample_data({audio_r,audio_l}),.full(audio_full),.overflow(ov),
        .pixel_valid(pv),.pixel_data(pd),.pixel_ready(1'b1),.underflow(underflow),.muted(audio_muted),.underflow_toggle(audio_uf));
    kagura_demo_sequencer #(.SPRITES(1),.AUDIO(1),.SCENE(1)) seq(.clk(sys),.reset(sys_reset),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),
        .rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.configured(configured),.frames(frames),
        .map_bad(map_bad),.data_bad(data_bad),.map_readback(),.map_written());
    kagura_vdp #(.CAPS(8'h13)) dut(.sys_clk(sys),.sys_reset(sys_reset),
        .audio_full(audio_full),.audio_underflow_toggle(audio_uf),.audio_muted(audio_muted),
        .audio_sample_valid(audio_valid),.audio_left(audio_l),.audio_right(audio_r),.req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.render_cycles(render_cycles),
        .pix_clk(pix),.pix_reset(pix_reset),.cx(cx),.cy(cy),.rgb(rgb));
    always @(posedge pix)
        if(pix_reset) begin cx<=0; cy<=0; end
        else if(cx==799) begin cx<=0; cy<=cy==524 ? 10'd0 : cy+1'b1; end
        else cx<=cx+1'b1;

    integer fd, samples=0, clipped=0, peak=0, nonzero=0;
    always @(posedge sys) if(!sys_reset && audio_valid) begin
        if(audio_full || ov) $fatal(1,"demo FIFO overflow");
        if(configured) begin
            $fwrite(fd,"%c%c%c%c",audio_l[7:0],audio_l[15:8],audio_r[7:0],audio_r[15:8]);
            samples=samples+1;
            if(audio_l==16'sh7fff || audio_l==-16'sh8000 || audio_r==16'sh7fff || audio_r==-16'sh8000) clipped=clipped+1;
            if(audio_l>peak) peak=audio_l; if(-audio_l>peak) peak=-audio_l;
            if(audio_r>peak) peak=audio_r; if(-audio_r>peak) peak=-audio_r;
            if(audio_l!=0 || audio_r!=0) nonzero=nonzero+1;
        end
    end
    always @(posedge pix) if(!pix_reset && underflow) $fatal(1,"demo FIFO underflow");

    // Distinct notes the player started (bass from the first row, lead
    // from row 64 of the first pass, i.e. frame 449).
    reg [127:0] bass_seen=0, lead_seen=0;
    always @(posedge sys) if(seq.music_tick) begin
        bass_seen[seq.bass_note]=1;
        if(seq.lead_gate) lead_seen[seq.lead_note]=1;
    end
    initial begin
        integer target;
        if(!$value$plusargs("frames=%d",target)) target=30;
        fd=$fopen("build/verilator/demo-music.raw","wb");
        #200; sys_reset=0; pix_reset=0;
        wait(configured);
        wait(frames>=16'(target));
        $fclose(fd);
        if(dut.core.registers.error_code!==0) $fatal(1,"ERROR_CODE %02h",dut.core.registers.error_code);
        if(dut.core.audio_status[2:1]!=0) $fatal(1,"audio FIFO sticky %0b",dut.core.audio_status[2:1]);
        if(clipped!=0) $fatal(1,"%0d clipped samples",clipped);
        if(nonzero<samples/2) $fatal(1,"song mostly silent: %0d of %0d samples",nonzero,samples);
        if($countones(bass_seen)<(target>=120 ? 4 : 2)) $fatal(1,"bass played only %0d notes",$countones(bass_seen));
        if(target>=600 && $countones(lead_seen)<8) $fatal(1,"lead played only %0d notes",$countones(lead_seen));
        $display("PASS: demo song %0d frames, %0d stereo samples, peak %0d, %0d non-silent, %0d bass / %0d lead notes",
            frames,samples,peak,nonzero,$countones(bass_seen),$countones(lead_seen));
        $finish;
    end
endmodule
