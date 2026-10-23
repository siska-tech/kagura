`timescale 1ns/1ps
// kagura_tmds_channel against the unchanged upstream tmds_channel: the same
// random input sequence (video runs long enough to build disparity, plus
// control, guard, island and undefined modes) must give the upstream output
// exactly two pixel clocks later on all three lanes.
module tb_tmds_pipeline;
    reg clk=0;
    always #5 clk=~clk;
    reg [7:0] video [0:2];
    reg [3:0] island [0:2];
    reg [1:0] ctrl [0:2];
    reg [2:0] mode=0;
    wire [9:0] ref_tmds [0:2], new_tmds [0:2];
    genvar c;
    generate for(c=0;c<3;c=c+1) begin: lane
        tmds_channel #(.CN(c)) upstream(.clk_pixel(clk),.video_data(video[c]),.data_island_data(island[c]),
            .control_data(ctrl[c]),.mode(mode),.tmds(ref_tmds[c]));
        kagura_tmds_channel #(.CN(c)) pipelined(.clk_pixel(clk),.video_data(video[c]),.data_island_data(island[c]),
            .control_data(ctrl[c]),.mode(mode),.tmds(new_tmds[c]));
    end endgenerate
    reg [9:0] ref_d1 [0:2], ref_d2 [0:2];
    integer cycle=0, run=0, j, checked=0, video_symbols=0;
    always @(posedge clk) begin
        for(j=0;j<3;j=j+1) begin ref_d2[j]<=ref_d1[j]; ref_d1[j]<=ref_tmds[j]; end
    end
    always @(negedge clk) begin
        // Compare once the delay line holds upstream output (from cycle 3).
        if(cycle>=3) for(j=0;j<3;j=j+1) begin
            if(new_tmds[j]!==ref_d2[j]) $fatal(1,"lane %0d cycle %0d: %010b expected %010b",j,cycle,new_tmds[j],ref_d2[j]);
            checked=checked+1;
        end
        if(run==0) begin
            // Mostly video; runs of 1..200 symbols in one mode.
            mode=$urandom_range(0,9)<6 ? 3'd1 : 3'($urandom_range(0,7));
            run=$urandom_range(1,200);
        end
        run=run-1;
        if(mode==1) video_symbols=video_symbols+1;
        for(j=0;j<3;j=j+1) begin
            // Biased data as well as uniform, so disparity runs far both ways.
            case($urandom_range(0,3))
                0: video[j]=8'($urandom);
                1: video[j]=8'($urandom) | 8'hf0;
                2: video[j]=8'($urandom) & 8'h0f;
                default: video[j]=$urandom_range(0,1) ? 8'hff : 8'h00;
            endcase
            island[j]=4'($urandom); ctrl[j]=2'($urandom);
        end
        cycle=cycle+1;
        if(cycle==200000) begin
            $display("PASS: pipelined TMDS channel equals upstream two clocks later, %0d lane symbols (%0d video cycles), all modes",checked,video_symbols);
            $finish;
        end
    end
    initial for(j=0;j<3;j=j+1) begin video[j]=0; island[j]=0; ctrl[j]=0; end
endmodule
