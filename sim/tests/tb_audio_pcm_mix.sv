`timescale 1ns/1ps
module tb_audio_pcm_mix;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,apply_valid=0;
    wire apply_ready,apply_done,apply_error,apply_busy,wave_read,sample_valid,apply_boundary,sample_boundary;
    reg [143:0] cfg_step=0;
    reg [23:0] cfg_duty=0;
    reg [47:0] cfg_gain_l=0,cfg_gain_r=0;
    reg [5:0] cfg_enable=0,cfg_phase_reset=0;
    reg [7:0] cfg_wave_len=8'h55,cfg_master=32;
    reg [15:0] cfg_noise_period=0,cfg_pcm_gain_l=0,cfg_pcm_gain_r=0;
    reg [1:0] cfg_pcm_enable=0;
    reg signed [7:0] pcm_sample0=0,pcm_sample1=0;
    wire [8:0] wave_addr;
    wire signed [15:0] sample_left,sample_right;
    wire [6:0] last_cycles;

    kagura_audio_synth #(.PCM_ENABLE(1)) dut(
        .clk(clk),.reset(reset),.apply_valid(apply_valid),.apply_ready(apply_ready),
        .cfg_step(cfg_step),.cfg_duty(cfg_duty),.cfg_gain_l(cfg_gain_l),.cfg_gain_r(cfg_gain_r),
        .cfg_enable(cfg_enable),.cfg_phase_reset(cfg_phase_reset),.cfg_wave_len(cfg_wave_len),
        .cfg_master(cfg_master),.cfg_noise_period(cfg_noise_period),.apply_done(apply_done),
        .apply_error(apply_error),.apply_busy(apply_busy),.wave_read(wave_read),.wave_addr(wave_addr),
        .wave_data(8'sd0),.sample_valid(sample_valid),.sample_left(sample_left),
        .sample_right(sample_right),.last_cycles(last_cycles),.apply_boundary(apply_boundary),.sample_boundary(sample_boundary),
        .pcm_sample0(pcm_sample0),.pcm_sample1(pcm_sample1),
        .cfg_pcm_gain_l(cfg_pcm_gain_l),.cfg_pcm_gain_r(cfg_pcm_gain_r),
        .cfg_pcm_enable(cfg_pcm_enable));

    function automatic signed [15:0] expected(input integer sum,input integer master);
        integer scaled;
        begin
            scaled=(sum*master)>>>8;
            expected=scaled>32767 ? 16'sd32767 : scaled< -32768 ? -16'sd32768 : 16'(scaled);
        end
    endfunction
    task automatic apply;
        begin
            @(negedge clk); wait(apply_ready); apply_valid=1;
            @(negedge clk); apply_valid=0; wait(apply_done);
        end
    endtask
    task automatic check(input integer left_sum,input integer right_sum);
        begin
            @(posedge sample_valid); #1;
            if(last_cycles!=30) $fatal(1,"PCM mix took %0d cycles",last_cycles);
            if(sample_left!==expected(left_sum,cfg_master) || sample_right!==expected(right_sum,cfg_master))
                $fatal(1,"PCM mix got %0d,%0d expected %0d,%0d",sample_left,sample_right,
                    expected(left_sum,cfg_master),expected(right_sum,cfg_master));
        end
    endtask

    initial begin
        #100; @(negedge clk); reset=0;
        repeat(2) @(posedge sample_valid);

        cfg_pcm_gain_l={8'd3,8'd2};
        cfg_pcm_gain_r={8'd5,8'd4};
        cfg_pcm_enable=2'b11; cfg_master=32;
        apply();
        pcm_sample0=8'sd100; pcm_sample1=-8'sd20;
        check(100*2-20*3,100*4-20*5);

        // Gain/enable are snapshots; sample values remain live per boundary.
        cfg_pcm_gain_l=0; cfg_pcm_gain_r=0; cfg_pcm_enable=0;
        pcm_sample0=-8'sd128; pcm_sample1=8'sd127;
        check(-128*2+127*3,-128*4+127*5);
        apply();
        check(0,0);

        // Both PCM channels can drive opposite saturation independently.
        cfg_pcm_gain_l=16'hffff; cfg_pcm_gain_r=16'hffff;
        cfg_pcm_enable=2'b11; cfg_master=255; apply();
        pcm_sample0=8'sd127; pcm_sample1=8'sd127;
        check(127*510,127*510);
        pcm_sample0=-8'sd128; pcm_sample1=-8'sd128;
        check(-128*510,-128*510);

        $display("PASS: optional PCM 2ch mix, snapshots, 30/64 cycles and saturation");
        $finish;
    end
    initial begin #2000000; $fatal(1,"PCM mixer timeout"); end
endmodule
