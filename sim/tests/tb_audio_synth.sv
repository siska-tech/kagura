`timescale 1ns/1ps
module tb_audio_synth;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,apply_valid=0;
    wire apply_ready,apply_done,apply_error,apply_busy,wave_read,valid;
    reg [143:0] step=0;
    reg [23:0] duty=0;
    reg [47:0] gain_l=0,gain_r=0;
    reg [5:0] enable=0,phase_reset=0;
    reg [7:0] lengths=8'h55,master=32;
    reg [15:0] period=0;
    wire [8:0] wave_addr;
    reg signed [7:0] wave_data;
    wire signed [15:0] left_sample,right_sample;
    wire [6:0] cycles;
    reg signed [7:0] wave_memory [0:511];
    kagura_audio_synth dut(clk,reset,apply_valid,apply_ready,step,duty,gain_l,gain_r,enable,phase_reset,
        lengths,master,period,apply_done,apply_error,apply_busy,wave_read,wave_addr,wave_data,
        valid,left_sample,right_sample,cycles,);

    // Independent integer model, evaluated once per sample, not per RTL FSM.
    reg [143:0] a_step=0,p_step=0;
    reg [23:0] a_duty=0,p_duty=0;
    reg [47:0] a_l=0,a_r=0,p_l=0,p_r=0;
    reg [5:0] a_enable=0,p_enable=0,p_reset=0;
    reg [7:0] a_len=8'h55,p_len=8'h55,a_master=32,p_master=32;
    reg [15:0] a_period=0,p_period=0;
    reg m_pending=0,expect_done=0,expect_error=0;
    integer phases[0:5],noise=1,noise_count=0;
    integer div_count=0,clock_count=0,due=-1,expected_l=0,expected_r=0;
    integer wave_expected[0:1]; reg [1:0] wave_needed=0;
    integer observed=0,applies=0,rejected=0,pos_clip=0,neg_clip=0,raw;
    integer n,c,d,s,v,idx,old_noise;
    longint signed sum_l,sum_r,scaled_l,scaled_r;
    reg bad;
    always @(posedge clk) begin
        expect_done=0; expect_error=0;
        if(reset) begin
            div_count=0; clock_count=0; due=-1; m_pending=0;
            a_step=0; a_duty=0; a_l=0; a_r=0; a_enable=0; a_len=8'h55; a_master=32; a_period=0;
            for(integer k=0;k<6;k=k+1) phases[k]=0;
            noise=1; noise_count=0; wave_needed=0; wave_data<=0;
        end else begin
            clock_count=clock_count+1;
            if(div_count==1124) begin
                div_count=0;
                if(m_pending) begin
                    a_step=p_step; a_duty=p_duty; a_l=p_l; a_r=p_r;
                    a_enable=p_enable; a_len=p_len; a_master=p_master; a_period=p_period;
                    for(integer k=0;k<6;k=k+1) if(p_reset[k]) phases[k]=0;
                    if(p_reset[3]) begin noise=1; noise_count=a_period; end
                    m_pending=0; expect_done=1; applies=applies+1;
                end
                sum_l=0; sum_r=0; wave_needed=0;
                for(c=0;c<6;c=c+1) begin
                    v=0; s=int'(a_step[24*c +:24]);
                    if(c>=4) begin
                        n=int'(a_len[(c-4)*4 +:4]);
                        wave_needed[c-4]=1;
                        wave_expected[c-4]=(c-4)*256+phases[c]/(2**(24-n));
                    end
                    if(a_enable[c]) begin
                        if(c<3) begin
                            d=int'(a_duty[c*8 +:8]);
                            if(s!=0 && d!=0) v=phases[c]/65536<d ? 127 : -127;
                            phases[c]=(phases[c]+s)%16777216;
                        end else if(c==3) begin
                            v=(noise/16384)!=0 ? 127 : -127;
                            if(noise_count==0) begin
                                old_noise=noise;
                                noise=((old_noise*2)%32768) | (((old_noise/16384)^(old_noise/8192))&1);
                                noise_count=a_period;
                            end else noise_count=noise_count-1;
                        end else begin
                            if(s!=0) begin
                                n=int'(a_len[(c-4)*4 +:4]);
                                idx=(c-4)*256+phases[c]/(2**(24-n));
                                v=int'($signed(wave_memory[idx]));
                                wave_needed[c-4]=1; wave_expected[c-4]=idx;
                            end
                            phases[c]=(phases[c]+s)%16777216;
                        end
                    end
                    sum_l=sum_l+v*int'(a_l[c*8 +:8]);
                    sum_r=sum_r+v*int'(a_r[c*8 +:8]);
                end
                // Full-width arithmetic multiplication, independent of the
                // RTL's shared low17 product + signed high-bit correction.
                scaled_l=(sum_l*int'(a_master))>>>8;
                scaled_r=(sum_r*int'(a_master))>>>8;
                if(scaled_l>32767 || scaled_r>32767) pos_clip=pos_clip+1;
                if(scaled_l< -32768 || scaled_r< -32768) neg_clip=neg_clip+1;
                expected_l=scaled_l>32767 ? 32767 : scaled_l< -32768 ? -32768 : int'(scaled_l);
                expected_r=scaled_r>32767 ? 32767 : scaled_r< -32768 ? -32768 : int'(scaled_r);
                due=clock_count+25;
            end else div_count=div_count+1;
            if(apply_valid && apply_ready) begin
                bad=lengths[3:0]<5 || lengths[3:0]>8 || lengths[7:4]<5 || lengths[7:4]>8;
                for(integer k=0;k<6;k=k+1) if(k!=3 && step[k*24+23]) bad=1;
                if(bad) begin expect_error=1; rejected=rejected+1; end
                else begin
                    m_pending=1; p_step=step; p_duty=duty; p_l=gain_l; p_r=gain_r;
                    p_enable=enable; p_reset=phase_reset; p_len=lengths; p_master=master; p_period=period;
                end
            end
            if(wave_read) begin
                if(!wave_needed[wave_addr[8]] || wave_addr!=wave_expected[wave_addr[8]])
                    $fatal(1,"wave address %d expected %d",wave_addr,wave_expected[wave_addr[8]]);
                wave_needed[wave_addr[8]]=0;
                wave_data<=wave_memory[wave_addr];
            end
        end
    end
    always @(negedge clk) if(!reset) begin
        if(apply_done!==expect_done || apply_error!==expect_error || apply_busy!==m_pending)
            $fatal(1,"apply handshake/snapshot mismatch");
        if(valid || clock_count==due) begin
            if(!valid || clock_count!=due || cycles!=25 || wave_needed!=0)
                $fatal(1,"sample cadence/latency %d due %d cycles %d waves %b",clock_count,due,cycles,wave_needed);
            if(left_sample!==16'(expected_l) || right_sample!==16'(expected_r))
                $fatal(1,"sample %d got %d,%d expected %d,%d",observed,left_sample,right_sample,expected_l,expected_r);
            for(integer k=0;k<6;k=k+1) if(k!=3 && dut.phase[k]!=phases[k]) $fatal(1,"phase %d",k);
            if(dut.noise_state!=noise || dut.noise_count!=noise_count) $fatal(1,"noise state/counter");
            observed=observed+1;
            $fwrite(raw,"%c%c%c%c",left_sample[7:0],left_sample[15:8],right_sample[7:0],right_sample[15:8]);
        end
    end
    task automatic apply;
        begin
            @(negedge clk); while(!apply_ready) @(negedge clk);
            apply_valid=1;
            @(negedge clk); apply_valid=0;
        end
    endtask
    task automatic apply_wait;
        begin apply(); wait(apply_done); @(negedge clk); end
    endtask
    task automatic samples(input integer amount);
        integer goal;
        begin goal=observed+amount; wait(observed>=goal); @(negedge clk); end
    endtask
    reg noise_seen[0:32767];
    integer i,k;
    initial begin
        raw=$fopen("build/verilator/audio-synth.raw","wb");
        if(!raw) $fatal(1,"cannot create RTL sample artifact");
        for(i=0;i<512;i=i+1) wave_memory[i]=8'(i*37+17);
        #100; @(negedge clk); reset=0;
        samples(4); // reset silence and first boundary/cadence
        enable=6'b000111; gain_l=48'h004050607080; gain_r=48'h008070605040;
        step[23:0]=153791; step[47:24]=230687; step[71:48]=307582;
        duty=24'h208040; phase_reset=6'h3f;
        apply();
        // Shadow values change while the request is pending; they must not
        // replace its captured snapshot. Backpressure must not create apply.
        gain_l=0; gain_r=0; master=255;
        apply_valid=1; repeat(3) @(negedge clk); apply_valid=0;
        wait(apply_done); samples(512);
        // Pulse duty boundaries, STEP0 and independent L/R gains.
        master=32; gain_l={6{8'hff}}; gain_r=0; enable=1;
        step[23:0]=24'h200000;
        for(i=0;i<6;i=i+1) begin
            case(i) 0:duty[7:0]=0; 1:duty[7:0]=1; 2:duty[7:0]=32;
                3:duty[7:0]=64; 4:duty[7:0]=128; default:duty[7:0]=255; endcase
            phase_reset=1; apply_wait(); samples(32);
        end
        step[23:0]=0; apply_wait(); samples(16);
        // All wave lengths, signed endpoints and full phase wrap.
        enable=6'b110000; gain_l=48'hff0000000000; gain_r=48'h00ff00000000;
        step[119:96]=24'h010000; step[143:120]=24'h030000; phase_reset=6'b110000;
        for(i=5;i<=8;i=i+1) begin lengths={4'(13-i),4'(i)}; apply_wait(); samples(256); end
        step[119:96]=0; step[143:120]=0; apply_wait(); samples(16);
        // Disabled phase/counter hold; reset requests still act when disabled.
        enable=0; phase_reset=0; apply_wait(); samples(12);
        phase_reset=6'h3f; apply_wait(); samples(12);
        // Invalid requests do not become pending or modify active settings.
        for(i=0;i<6;i=i+1) if(i!=3) begin
            step[i*24+23]=1; apply(); @(negedge clk); step[i*24+23]=0;
        end
        lengths=8'h54; apply(); @(negedge clk); lengths=8'h95; apply();
        @(negedge clk); lengths=8'h55;
        // Positive saturation across all periodic voices; then silence while
        // changing the test RAM so active-wave data never changes in flight.
        enable=0; apply_wait(); samples(1);
        for(i=0;i<512;i=i+1) wave_memory[i]=127;
        enable=6'b110111; gain_l={6{8'hff}}; gain_r={6{8'hff}}; master=255;
        duty=24'hffffff; step={6{24'd1}}; phase_reset=6'h3f;
        apply_wait(); samples(32);
        // Prepare pulse phases in their negative half, hold that half with
        // STEP1, and use -128 wave samples to exercise negative saturation.
        enable=7; duty=24'h808080; step[71:0]={3{24'h400000}}; phase_reset=7;
        apply_wait(); samples(2);
        for(i=0;i<512;i=i+1) wave_memory[i]=-128;
        enable=6'b110111; step={6{24'd1}}; phase_reset=6'b110000;
        apply_wait(); samples(32);
        master=0; apply_wait(); samples(8);
        // Period+1 timing, disabling and resetting noise.
        master=32; enable=8; period=2; phase_reset=8;
        step[95:72]=24'hffffff; // reserved noise step is ignored
        apply_wait(); samples(64);
        enable=0; phase_reset=0; apply_wait(); samples(8);
        enable=8; apply_wait(); samples(64);
        // Every nonzero 15bit LFSR state must occur once in 32767 updates.
        period=0; phase_reset=8; apply_wait();
        for(i=0;i<32768;i=i+1) noise_seen[i]=0;
        for(i=0;i<32767;i=i+1) begin
            @(posedge valid); #1;
            k=int'(dut.noise_state);
            if(k==0 || noise_seen[k]) $fatal(1,"LFSR repeated/zero at update %d state %d",i,k);
            noise_seen[k]=1;
        end
        if(dut.noise_state!=1) $fatal(1,"LFSR period not 32767");
        @(negedge clk);
        // Abort an in-flight sample, then confirm a fresh silent start.
        wait(dut.state==1); @(negedge clk); reset=1;
        repeat(4) @(negedge clk); reset=0; samples(4);
        if(pos_clip==0 || neg_clip==0 || rejected!=7) $fatal(1,"coverage: clips %d/%d rejected %d",pos_clip,neg_clip,rejected);
        $fclose(raw);
        $display("PASS: six-voice synth, %0d stereo samples vs integer model, %0d applies, %0d invalid; 25/64 cycles, pulse/wave/noise, full LFSR period, snapshots, reset, pan and saturation",observed,applies,rejected);
        $finish;
    end
    initial begin #1000000000; $fatal(1,"audio synth timeout"); end
endmodule
