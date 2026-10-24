`timescale 1ns/1ps
// kagura_demo_sequencer + kagura_vdp: the first frame after configuration
// and the following animated frames are compared pixel by pixel with an
// independent model of the documented demo content and scroll sequence.
module tb_demo_sequencer #(parameter bit SPRITES=0,parameter bit AUDIO=0,parameter bit RASTER=0);
    reg sys=0, pix=0;
    always #9.259 sys=~sys;
    always #19.8415 pix=~pix;
    reg sys_reset=1, pix_reset=1;
    wire req_valid, req_ready, req_write, rsp_valid, rsp_error, irq, configured, map_bad, data_bad;
    wire [4:0] req_addr; wire [7:0] req_wdata, rsp_rdata;
    wire [31:0] map_readback;
    wire [31:0] map_written;
    wire [15:0] frames; wire [11:0] render_cycles;
    reg [9:0] cx=0, cy=0;
    wire [23:0] rgb;
    wire audio_full,audio_uf,audio_muted,audio_valid;
    wire signed [15:0] audio_l,audio_r;
    generate if(AUDIO) begin: audio_link_test
        wire ov,underflow,pv;
        wire [31:0] pd;
        kagura_audio_transport transport(.reset(sys_reset || pix_reset),.clk_system(sys),.clk_pixel(pix),
            .sample_valid(audio_valid),.sample_data({audio_r,audio_l}),.full(audio_full),.overflow(ov),
            .pixel_valid(pv),.pixel_data(pd),.pixel_ready(1'b1),.underflow(underflow),.muted(audio_muted),.underflow_toggle(audio_uf));
        reg [31:0] produced[0:16383];
        integer written=0,consumed=0;
        reg [31:0] expected_pcm;
        always @(posedge sys) if(!sys_reset && audio_valid) begin
            produced[written]= {audio_r,audio_l}; written=written+1;
            if(audio_full || ov) $fatal(1,"demo FIFO overflow");
        end
        always @(posedge pix) if(!pix_reset) begin
            if(transport.pop) begin
                if(consumed>=written) $fatal(1,"audio read before sample generation");
                expected_pcm=produced[consumed]; consumed=consumed+1;
            end
            if(transport.response_valid) begin
                #1;
                if(!pv || pd!==expected_pcm) $fatal(1,"audio transport reordered/corrupted PCM");
            end
            if(underflow) $fatal(1,"demo FIFO underflow");
        end
        final begin
            if(consumed<100) $error("audio transport did not consume samples");
        end
    end else begin
        assign audio_full=0; assign audio_uf=0; assign audio_muted=0;
    end endgenerate
    kagura_demo_sequencer #(.SPRITES(SPRITES),.AUDIO(AUDIO),.RASTER(RASTER)) seq(.clk(sys),.reset(sys_reset),.req_valid(req_valid),.req_ready(req_ready),
        .req_write(req_write),.req_addr(req_addr),.req_wdata(req_wdata),.rsp_valid(rsp_valid),
        .rsp_rdata(rsp_rdata),.rsp_error(rsp_error),.configured(configured),.frames(frames),
        .map_bad(map_bad),.data_bad(data_bad),.map_readback(map_readback),.map_written(map_written));
    kagura_vdp #(.CAPS(RASTER ? 8'h41 : 8'h01)) dut(.sys_clk(sys),.sys_reset(sys_reset),
        .audio_full(audio_full),.audio_underflow_toggle(audio_uf),.audio_muted(audio_muted),
        .audio_sample_valid(audio_valid),.audio_left(audio_l),.audio_right(audio_r),.req_valid(req_valid),.req_ready(req_ready),.req_write(req_write),.req_addr(req_addr),
        .req_wdata(req_wdata),.rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rsp_rdata),
        .rsp_error(rsp_error),.irq(irq),.render_cycles(render_cycles),
        .pix_clk(pix),.pix_reset(pix_reset),.cx(cx),.cy(cy),.rgb(rgb));
    always @(posedge pix)
        if(pix_reset) begin cx<=0; cy<=0; end
        else if(cx==799) begin cx<=0; cy<=cy==524 ? 10'd0 : cy+1'b1; end
        else cx<=cx+1'b1;

    // Independent model of the demo content (see the sequencer header).
    function automatic [11:0] colour(input integer p,input integer i);
        colour=i==0 ? 12'h000 : {4'(i),4'(p),4'(15-i)};
    endfunction
    function automatic integer tile_pixel(input integer t,input integer x,input integer y);
        tile_pixel=(x==0 || y==0) ? 15 : ((x+y+t)%15)+1;
    endfunction
    integer sx, sy;
    function automatic [23:0] expected(input integer x,input integer y);
        integer e, a, lx, ly, px, py, row, col, tile, pal, p,n,xx,yy,t; reg hf, vf; reg [11:0] c;
        begin
            lx=x/2; ly=y/2; px=(lx+sx)%512; py=(ly+sy)%256;
            // Raster table: from line 100, entry e=min((ly-100)/10,7) adds a triangle wave of 0..21 px (phase = update count).
            if(RASTER && ly>=100) begin e=(ly-100)/10; if(e>7) e=7; a=((sx/2)%16+3*e)%16; px=(lx+sx+3*(a>=8 ? 15-a : a))%512; end
            row=py/8; col=px/8;
            tile=(col+row)%16; pal=row%16;
            hf=col%2==1 && row/8==1; vf=col%2==1 && row/8==2;
            p=tile_pixel(tile, hf ? 7-px%8 : px%8, vf ? 7-py%8 : py%8);
            c=colour(p==0 ? 0 : pal, p); // BACKDROP 0 = palette 0 colour 0 = black
            if(SPRITES) for(n=0;n<8;n=n+1) begin
                xx=lx-(32+24*n); yy=ly-(40+32*(n%4));
                if(xx>=0 && xx<16 && yy>=0 && yy<16) begin
                    if(n%2) xx=15-xx;
                    if((n/2)%2) yy=15-yy;
                    t=(n%4)*4+2*(yy/8)+xx/8;
                    if(n<4 || p==0) c=colour(15-n,tile_pixel(t,xx%8,yy%8));
                end
            end
            expected={c[11:8],c[11:8],c[7:4],c[7:4],c[3:0],c[3:0]};
        end
    endfunction
    integer x, y;
    task automatic check_frame(input integer which);
        integer bad;
        begin
            @(negedge pix); while(!(cx==799 && cy==524)) @(negedge pix);
            bad=0;
            for(y=0;y<480;y=y+1) for(x=0;x<640;x=x+1) begin
                @(negedge pix);
                if(rgb!==expected(x,y)) begin
                    if(bad<4) $display("frame %0d (scroll %0d,%0d) pixel %0d,%0d: %06h expected %06h",which,sx,sy,x,y,rgb,expected(x,y));
                    bad=bad+1;
                end
                if(x==639) repeat(160) @(negedge pix);
            end
            if(bad!=0) $fatal(1,"frame %0d: %0d pixels differ",which,bad);
        end
    endtask

    integer k, first;
    initial begin
        #200; sys_reset=0; pix_reset=0;
        wait(configured);
        // The first COMMIT applies scroll 0,0; update k (k=1,2,..) applies
        // X=k, Y=floor(k/4) one frame later each.
        sx=0; sy=0; check_frame(0);
        first=frames;
        for(k=0;k<3;k=k+1) begin
            // The frame shown now carries the scroll committed before it began.
            @(negedge pix); while(!(cx==799 && cy==523)) @(negedge pix);
            sx=frames; sy=frames/4;
            check_frame(k+1);
        end
        if(map_readback!==32'h02040580) $fatal(1,"diagnostic readback %08h",map_readback);
        if(map_written!==32'h02040580) $fatal(1,"diagnostic transmitted bytes %08h",map_written);
        if(map_bad || data_bad) $fatal(1,"read-back mismatch map=%0d data=%0d",map_bad,data_bad);
        if(dut.core.registers.error_code!==0) $fatal(1,"ERROR_CODE %02h",dut.core.registers.error_code);
        $display("PASS: demo sequencer content and scroll animation, 4 frames x 307200 pixels vs model, %0d updates",frames);
        $finish;
    end
    initial begin #200000000; $fatal(1,"demo timeout"); end
endmodule
