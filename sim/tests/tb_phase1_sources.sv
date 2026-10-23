`timescale 1ns/1ps
module tb_phase1_sources;
    reg clk=0, reset=1;
    always #5 clk=~clk;
    wire [9:0] x,y;
    wire de,hs,vs;
    wire [23:0] rgb;
    wire valid;
    wire signed [15:0] left_sample,right_sample;
    kagura_test_pattern video(clk,reset,x,y,de,hs,vs,rgb);
    kagura_test_tone audio(clk,reset,valid,left_sample,right_sample);
    integer i, ex, ey, active_count=0, hs_count=0, vs_count=0;
    integer samples=0, last_tick=0, ticks=0;
    reg [23:0] expected_rgb;
    initial begin
        repeat(3) @(negedge clk);
        reset=0;
        for(i=0;i<840000;i=i+1) begin
            // Check current pixel before the edge advances counters.
            ex=i%800; ey=(i/800)%525;
            if(x!==ex[9:0] || y!==ey[9:0]) $fatal(1,"coordinate mismatch at %0d",i);
            if(de !== (ex<640 && ey<480)) $fatal(1,"DE mismatch");
            if(hs !== !(ex>=656 && ex<752)) $fatal(1,"HS mismatch");
            if(vs !== !(ey>=490 && ey<492)) $fatal(1,"VS mismatch");
            expected_rgb=0;
            if(ex<640 && ey<480) begin
                case(ex/80)
                    0:expected_rgb=24'hffffff; 1:expected_rgb=24'hffff00;
                    2:expected_rgb=24'h00ffff; 3:expected_rgb=24'h00ff00;
                    4:expected_rgb=24'hff00ff; 5:expected_rgb=24'hff0000;
                    6:expected_rgb=24'h0000ff; 7:expected_rgb=0;
                endcase
                if(ex==0 || ex==639 || ey==0 || ey==479) expected_rgb=24'hffffff;
            end
            if(rgb!==expected_rgb) $fatal(1,"RGB mismatch");
            if(de) active_count=active_count+1;
            if(!hs) hs_count=hs_count+1;
            if(!vs) vs_count=vs_count+1;
            @(posedge clk); #1;
            ticks=ticks+1;
            if(valid) begin
                if(ticks-last_tick !=1125) $fatal(1,"sample period");
                last_tick=ticks;
                if(left_sample !== ((samples%48<24)?16'sd4096:-16'sd4096)) $fatal(1,"left tone");
                if(right_sample !== ((samples%96<48)?16'sd4096:-16'sd4096)) $fatal(1,"right tone");
                samples=samples+1;
            end
            @(negedge clk);
        end
        if(active_count!=614400 || hs_count!=100800 || vs_count!=3200)
            $fatal(1,"frame totals");
        if(samples!=746) $fatal(1,"sample total");
        reset=1;
        @(posedge clk); #1;
        if(x!==0 || y!==0 || valid!==0 || left_sample!==0 || right_sample!==0)
            $fatal(1,"restart reset");
        $display("PASS: two complete video frames, geometry/RGB, 746 stereo samples, reset");
        $finish;
    end
    initial begin #10000000; $fatal(1,"timeout"); end
endmodule
