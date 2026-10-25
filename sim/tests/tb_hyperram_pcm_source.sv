`timescale 1ns/1ps
// Board evaluation engine, real controller, independently decoded CA memory.
module tb_hyperram_pcm_source;
    reg clk=0,reset=1;
    always #9.259 clk=~clk;
    wire valid;
    wire signed [15:0] left_sample,right_sample;
    wire [31:0] checked_samples,read_bytes,data_errors,mix_errors;
    wire [7:0] faults;
    wire [1:0] active;
    wire reset_n,cs_n,ck_en,dq_oe,rwds_oe,mask_r,mask_f;
    wire [7:0] dq_r,dq_f,read_r,read_f;
    kagura_hyperram_pcm_source #(.INIT_CYCLES(64)) dut(
        .clk,.reset,.sample_valid(valid),.sample_left(left_sample),.sample_right(right_sample),
        .checked_samples,.read_bytes,.data_errors,.mix_errors,.faults,.active,
        .phy_reset_n(reset_n),.phy_cs_n(cs_n),.phy_ck_en(ck_en),.phy_dq_oe(dq_oe),
        .phy_rwds_oe(rwds_oe),.phy_dq_o_rise(dq_r),.phy_dq_o_fall(dq_f),
        .phy_rwds_o_rise(mask_r),.phy_rwds_o_fall(mask_f),
        .phy_dq_i_rise(read_r),.phy_dq_i_fall(read_f));
    kagura_hyperram_pair_model #(.BYTES(4194304)) memory(
        .clk,.reset_n,.cs_n,.ck_en,.dq_oe,.rwds_oe,.dq_r,.dq_f,
        .mask_r,.mask_f,.read_r,.read_f);
    task automatic check_audio(input integer samples);
        integer l,r;
        wait(dut.check_pending);
        for(integer n=0;n<samples;n++) begin
            @(posedge valid); #1;
            l=((1+n%513)%64)*4;
            r=((3+n%511)%128)*2;
            if(l>=128) l=l-256;
            if(r>=128) r=r-256;
            if(left_sample!=l*16 || right_sample!=r*16)
                $fatal(1,"sample %0d: %0d,%0d expected %0d,%0d",n,left_sample,right_sample,l*16,r*16);
        end
        repeat(2) @(negedge clk);
        if(faults || data_errors || mix_errors || active!=3 || checked_samples!=32'(samples))
            $fatal(1,"unexpected status/count");
    endtask
    initial begin
        repeat(4) @(negedge clk); reset=0;
        check_audio(1250); // more than two loops of each channel and many refills
        if(read_bytes<2500) $fatal(1,"refill did not run");
        memory.memory[24'h000101]=memory.memory[24'h000101]^8'h01;
        wait(data_errors!=0 && mix_errors!=0);
        if(faults) $fatal(1,"corruption should be detected by comparators, not transport");
        @(negedge clk); reset=1;
        repeat(4) @(negedge clk); reset=0;
        check_audio(64);
        $display("PASS: dual PCM upload, unaligned 513/511-byte loops, refills, mixer, corruption detection and reset recovery");
        $finish;
    end
    initial begin #100000000; $fatal(1,"PCM source timeout"); end
endmodule
