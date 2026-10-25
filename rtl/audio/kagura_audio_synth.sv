// SPDX-License-Identifier: Apache-2.0
// CPU-independent six-voice engine with an optional two-channel PCM tail.
// Apply captures a private snapshot and
// activates it at the next 48kHz boundary, before evaluating phase zero.
// Wave port: ch4/ch5 in address bit8, one-edge synchronous read latency.
// Two shared 18x9 multipliers serve all voice gains and the master gain.
module kagura_audio_synth #(
    parameter bit EXTERNAL_SNAPSHOT=0, // caller holds cfg until apply_done
    parameter bit PCM_ENABLE=0
) (
    input wire clk, reset,
    input wire apply_valid,
    output wire apply_ready,
    input wire [143:0] cfg_step,
    input wire [23:0] cfg_duty,
    input wire [47:0] cfg_gain_l, cfg_gain_r,
    input wire [5:0] cfg_enable, cfg_phase_reset,
    input wire [7:0] cfg_wave_len, cfg_master,
    input wire [15:0] cfg_noise_period,
    output reg apply_done, apply_error,
    output wire apply_busy,
    output wire wave_read,
    output wire [8:0] wave_addr,
    input wire signed [7:0] wave_data,
    output reg sample_valid,
    output reg signed [15:0] sample_left, sample_right,
    output reg [6:0] last_cycles,
    output wire apply_boundary,
    output wire sample_boundary,
    input wire signed [7:0] pcm_sample0, pcm_sample1,
    input wire [15:0] cfg_pcm_gain_l, cfg_pcm_gain_r,
    input wire [1:0] cfg_pcm_enable
);
    localparam [3:0] IDLE=0,VOICE=1,WAVE=2,MULT=3,MASTER=4,EMIT=5,PREP=6,SAT=7,ACC=8;
    reg [3:0] state;
    reg [2:0] channel;
    reg [10:0] divider;
    reg [6:0] cycles;
    reg pending;
    reg [143:0] pending_step,active_step;
    reg [23:0] pending_duty,active_duty;
    reg [47:0] pending_l,pending_r,active_l,active_r;
    reg [15:0] pending_pcm_l,pending_pcm_r,active_pcm_l,active_pcm_r;
    reg [5:0] pending_enable,pending_reset,active_enable;
    reg [1:0] pending_pcm_enable,active_pcm_enable;
    reg [7:0] pending_len,active_len,pending_master,active_master;
    reg [15:0] pending_period,active_period;
    reg [23:0] phase [0:5];
    reg [14:0] noise_state;
    reg [15:0] noise_count;
    reg signed [7:0] voice_sample;
    reg signed [19:0] sum_l,sum_r;
    // A voice product is registered in MULT and added on the next cycle
    // (PREP, or ACC after the last voice), keeping the multiplier and the
    // accumulator adder in separate cycles (timing at 54MHz).
    reg signed [26:0] voice_product_l,voice_product_r;
    reg accumulate;
    assign apply_ready=!pending;
    assign apply_busy=pending;
    assign apply_boundary=pending && divider==1124 && !reset;
    assign sample_boundary=divider==1124 && !reset;
    reg [23:0] step_now,phase_now;
    reg [7:0] gain_l,gain_r,duty_now;
    reg voice_on;
    wire [3:0] wave_len=channel==4 ? active_len[3:0] : active_len[7:4];
    wire [23:0] wave_phase=channel==5 ? phase[5] : phase[4];
    reg [7:0] wave_index;
    always @* case(wave_len)
        5: wave_index={3'b0,wave_phase[23:19]};
        6: wave_index={2'b0,wave_phase[23:18]};
        7: wave_index={1'b0,wave_phase[23:17]};
        default: wave_index=wave_phase[23:16];
    endcase
    // Read even disabled voices; muting is applied to the returned sample.
    // Keep the wide STEP/enable mux away from the shared RAM arbitration.
    assign wave_read=state==VOICE && channel>=4;
    reg [8:0] wave_addr_q;
    assign wave_addr=wave_addr_q;

    // An eight-voice sum lies within -261120..259080. Split the master input
    // into unsigned low17 plus signed high bits (only -2,-1,0,1 possible),
    // using shifts for the high contribution. This shares the same two
    // 18x9 multipliers used for signed8 voice * unsigned8 gain.
    wire signed [17:0] operand_l=state==MASTER ? {1'b0,sum_l[16:0]} : {{10{voice_sample[7]}},voice_sample};
    wire signed [17:0] operand_r=state==MASTER ? {1'b0,sum_r[16:0]} : {{10{voice_sample[7]}},voice_sample};
    wire signed [8:0] factor_l=$signed({1'b0,state==MASTER ? active_master : gain_l});
    wire signed [8:0] factor_r=$signed({1'b0,state==MASTER ? active_master : gain_r});
    wire signed [26:0] product_l=operand_l*factor_l;
    wire signed [26:0] product_r=operand_r*factor_r;
    function automatic signed [28:0] correction(input signed [19:0] sum,input [7:0] master);
        reg signed [28:0] m;
        begin
            m=$signed({21'b0,master});
            case(sum[19:17])
                3'b110: correction=-(m<<<18);
                3'b111: correction=-(m<<<17);
                3'b001: correction=m<<<17;
                default: correction=0;
            endcase
        end
    endfunction
    reg signed [26:0] master_product_l,master_product_r;
    reg signed [28:0] master_correction_l,master_correction_r;
    wire signed [28:0] scaled_l=($signed({{2{master_product_l[26]}},master_product_l})+master_correction_l)>>>8;
    wire signed [28:0] scaled_r=($signed({{2{master_product_r[26]}},master_product_r})+master_correction_r)>>>8;
    function automatic signed [15:0] saturate(input signed [28:0] value);
        if(value>29'sd32767) saturate=16'sd32767;
        else if(value< -29'sd32768) saturate=-16'sd32768;
        else saturate=value[15:0];
    endfunction
    reg invalid;
    integer i;
    always @* begin
        invalid=cfg_wave_len[3:0]<5 || cfg_wave_len[3:0]>8 || cfg_wave_len[7:4]<5 || cfg_wave_len[7:4]>8;
        for(integer c=0;c<6;c=c+1) if(c!=3 && cfg_step[c*24+23]) invalid=1;
    end
    always @(posedge clk)
        if(reset) begin
            state<=IDLE; channel<=0; divider<=0; cycles<=0; pending<=0;
            pending_step<=0; active_step<=0; pending_duty<=0; active_duty<=0;
            pending_l<=0; pending_r<=0; active_l<=0; active_r<=0;
            pending_pcm_l<=0; pending_pcm_r<=0; active_pcm_l<=0; active_pcm_r<=0;
            pending_enable<=0; pending_reset<=0; active_enable<=0;
            pending_pcm_enable<=0; active_pcm_enable<=0;
            pending_len<=8'h55; active_len<=8'h55; pending_master<=32; active_master<=32;
            pending_period<=0; active_period<=0;
            for(i=0;i<6;i=i+1) phase[i]<=0;
            noise_state<=1; noise_count<=0; voice_sample<=0; sum_l<=0; sum_r<=0;
            voice_product_l<=0; voice_product_r<=0; accumulate<=0;
            step_now<=0; phase_now<=0; gain_l<=0; gain_r<=0; duty_now<=0; voice_on<=0;
            master_product_l<=0; master_product_r<=0; master_correction_l<=0; master_correction_r<=0;
            wave_addr_q<=0;
            apply_done<=0; apply_error<=0; sample_valid<=0; sample_left<=0; sample_right<=0; last_cycles<=0;
        end else begin
            sample_valid<=0; apply_done<=0; apply_error<=0;
            if(apply_valid && apply_ready) begin
                if(invalid) apply_error<=1;
                else begin
                    pending<=1;
                    if(!EXTERNAL_SNAPSHOT) begin
                    pending_step<=cfg_step; pending_duty<=cfg_duty;
                    pending_l<=cfg_gain_l; pending_r<=cfg_gain_r; pending_enable<=cfg_enable;
                    pending_pcm_l<=PCM_ENABLE ? cfg_pcm_gain_l : 16'b0;
                    pending_pcm_r<=PCM_ENABLE ? cfg_pcm_gain_r : 16'b0;
                    pending_pcm_enable<=PCM_ENABLE ? cfg_pcm_enable : 2'b0;
                    pending_reset<=cfg_phase_reset; pending_len<=cfg_wave_len; pending_master<=cfg_master;
                    pending_period<=cfg_noise_period;
                    end
                end
            end
            if(divider==11'd1124) begin
                divider<=0; channel<=0; sum_l<=0; sum_r<=0; cycles<=0; state<=PREP;
                if(pending) begin
                    pending<=0; apply_done<=1;
                    active_step<=EXTERNAL_SNAPSHOT ? cfg_step : pending_step;
                    active_duty<=EXTERNAL_SNAPSHOT ? cfg_duty : pending_duty;
                    active_l<=EXTERNAL_SNAPSHOT ? cfg_gain_l : pending_l; active_r<=EXTERNAL_SNAPSHOT ? cfg_gain_r : pending_r;
                    active_enable<=EXTERNAL_SNAPSHOT ? cfg_enable : pending_enable;
                    active_pcm_l<=PCM_ENABLE ? (EXTERNAL_SNAPSHOT ? cfg_pcm_gain_l : pending_pcm_l) : 16'b0;
                    active_pcm_r<=PCM_ENABLE ? (EXTERNAL_SNAPSHOT ? cfg_pcm_gain_r : pending_pcm_r) : 16'b0;
                    active_pcm_enable<=PCM_ENABLE ? (EXTERNAL_SNAPSHOT ? cfg_pcm_enable : pending_pcm_enable) : 2'b0;
                    active_len<=EXTERNAL_SNAPSHOT ? cfg_wave_len : pending_len;
                    active_master<=EXTERNAL_SNAPSHOT ? cfg_master : pending_master;
                    active_period<=EXTERNAL_SNAPSHOT ? cfg_noise_period : pending_period;
                    for(i=0;i<6;i=i+1) if(EXTERNAL_SNAPSHOT ? cfg_phase_reset[i] : pending_reset[i]) phase[i]<=0;
                    if(EXTERNAL_SNAPSHOT ? cfg_phase_reset[3] : pending_reset[3]) begin
                        noise_state<=1; noise_count<=EXTERNAL_SNAPSHOT ? cfg_noise_period : pending_period;
                    end
                end
            end else divider<=divider+1'b1;
            if(state!=IDLE) cycles<=cycles+1'b1;
            case(state)
                PREP: begin
                    if(channel<6) begin
                        wave_addr_q<={channel==5,wave_index};
                        step_now<=active_step[24*channel +:24]; phase_now<=phase[channel];
                        gain_l<=active_l[8*channel +:8]; gain_r<=active_r[8*channel +:8];
                        duty_now<=channel<3 ? active_duty[8*channel +:8] : 8'b0;
                        voice_on<=active_enable[channel];
                    end else begin
                        step_now<=0; phase_now<=0; duty_now<=0;
                        gain_l<=active_pcm_l[8*(channel-6) +:8];
                        gain_r<=active_pcm_r[8*(channel-6) +:8];
                        voice_on<=active_pcm_enable[channel-6];
                    end
                    state<=VOICE;
                end
                VOICE: begin
                    voice_sample<=0;
                    if(channel<3) begin
                        if(voice_on) begin
                            phase[channel]<=phase_now+step_now;
                            if(step_now!=0 && duty_now!=0)
                                voice_sample<=phase_now[23:16]<duty_now ? 8'sd127 : -8'sd127;
                        end
                    end else if(channel==3) begin
                        if(voice_on) begin
                            voice_sample<=noise_state[14] ? 8'sd127 : -8'sd127;
                            if(noise_count==0) begin
                                noise_state<={noise_state[13:0],noise_state[14]^noise_state[13]}; noise_count<=active_period;
                            end else noise_count<=noise_count-1'b1;
                        end
                    end else if(channel<6) begin
                        if(voice_on) phase[channel]<=phase_now+step_now;
                    end else if(voice_on) voice_sample<=channel==6 ? pcm_sample0 : pcm_sample1;
                    state<=channel==4 || channel==5 ? WAVE : MULT;
                end
                WAVE: begin voice_sample<=voice_on && step_now!=0 ? wave_data : 8'sd0; state<=MULT; end
                MULT: begin
                    voice_product_l<=product_l; voice_product_r<=product_r; accumulate<=1;
                    if(channel==(PCM_ENABLE ? 7 : 5)) state<=ACC;
                    else begin channel<=channel+1'b1; state<=PREP; end
                end
                ACC: state<=MASTER;
                MASTER: begin
                    master_product_l<=product_l; master_product_r<=product_r;
                    master_correction_l<=correction(sum_l,active_master); master_correction_r<=correction(sum_r,active_master);
                    state<=SAT;
                end
                SAT: begin sample_left<=saturate(scaled_l); sample_right<=saturate(scaled_r); state<=EMIT; end
                EMIT: begin sample_valid<=1; last_cycles<=cycles+1'b1; state<=IDLE; end
                default: ;
            endcase
            if(accumulate) begin
                sum_l<=sum_l+20'(voice_product_l); sum_r<=sum_r+20'(voice_product_r); accumulate<=0;
            end
        end
// synthesis translate_off
    always @(posedge clk)
        if(!reset && divider==1124 && state!=IDLE) $fatal(1,"audio sample deadline missed");
// synthesis translate_on
endmodule
