`timescale 1ns/1ps
module tb_audio_packets;
    // Scaled common-reference rates: 14ns system / 30ns pixel = 54/25.2.
    reg sys=0,pix=0,reset=1,send=0;
    always #7 sys=~sys;
    always #15 pix=~pix;
    reg [31:0] source_data=0;
    wire full,ov,pv,pr,uf,muted;
    wire [31:0] pd;
    reg enable=0,field_end=0,island=0;
    wire [23:0] header;
    wire [55:0] sub[3:0];
    wire [8:0] serial;
    wire [4:0] counter;
    kagura_audio_transport transport(reset,sys,pix,send,source_data,full,ov,pv,pd,pr,uf,muted,);
    kagura_audio_packets packets(pix,reset,field_end,enable,pv,pd,pr,header,sub);
    packet_assembler assembler(pix,reset,island,header,sub,serial,counter);
    // 2048 samples, a 40-period source stall, then 1024 more samples.
    localparam integer TOTAL=3072, STALL_AT=2048, STALL_CYCLES=40*1125;
    integer produced=0,received=0,divider=0,ticks=0,slots=0,acrs=0,infos=0;
    integer emitted=0,silences=0,gap_runs=0,stalled=0;
    reg started=0,in_gap=0;
    reg [31:0] captured_header;
    reg [63:0] captured_sub[0:3];
    integer i,j,b,sum,idx;
    reg [15:0] expected_l,expected_r;
    reg [7:0] status_l,status_r;
    // Polynomial long division, independent of the assembler's shift recurrence.
    function automatic [7:0] syndrome(input reg [63:0] block_bits,input integer n);
        reg [71:0] poly;
        integer k;
        begin
            poly=0;
            for(k=0;k<n;k=k+1) poly[n-1-k]=block_bits[k];
            for(k=n-1;k>=8;k=k-1)
                if(poly[k]) poly=poly ^ (72'h1c1 << (k-8));
            syndrome=poly[7:0];
        end
    endfunction
    always @(negedge sys) begin
        send=0;
        if(!reset && produced==STALL_AT && stalled<STALL_CYCLES) stalled=stalled+1;
        else if(!reset && produced<TOTAL) begin
            if(divider==1124) begin
                divider=0;send=1;
                source_data={16'(produced ^ 16'ha55a),16'(produced)};
                produced=produced+1;
            end else divider=divider+1;
        end
    end
    task automatic check_packet;
        begin
            if(syndrome({32'b0,captured_header},32)!=0) $fatal(1,"header BCH");
            for(j=0;j<4;j=j+1)
                if(syndrome(captured_sub[j],64)!=0) $fatal(1,"subpacket BCH");
            case(captured_header[7:0])
                2: begin
                    if(captured_header[11:8]!=15) $fatal(1,"sample presence");
                    for(j=0;j<4;j=j+1) begin
                        // Silence is both channels zero; no source sample is.
                        if(captured_sub[j][47:0]==0) begin
                            silences=silences+1;
                            if(started && !in_gap) gap_runs=gap_runs+1;
                            in_gap=1;
                        end else begin
                            expected_l=16'(received);expected_r=16'(received ^ 16'ha55a);
                            if(captured_sub[j][23:0]!=={expected_l,8'b0} ||
                               captured_sub[j][47:24]!=={expected_r,8'b0}) $fatal(1,"PCM loss/order/LR %0d",received);
                            received=received+1; started=1; in_gap=0;
                        end
                        // IEC frame numbering counts every emitted sample.
                        idx=emitted%192;
                        if(captured_header[20+j] !== (idx==0)) $fatal(1,"block start");
                        // Channel status bit layout checked independently.
                        status_l=0;status_r=0;
                        if(idx==2 || idx==20 || idx==25 || idx==33) status_l=1;
                        if(idx==2 || idx==21 || idx==25 || idx==33) status_r=1;
                        if(captured_sub[j][49:48]!=0 || captured_sub[j][53:52]!=0) $fatal(1,"valid/user");
                        if(captured_sub[j][50]!==status_l[0] || captured_sub[j][54]!==status_r[0]) $fatal(1,"channel status %0d",idx);
                        if((^captured_sub[j][51:48]) !== (^captured_sub[j][23:0]) ||
                           (^captured_sub[j][55:52]) !== (^captured_sub[j][47:24])) $fatal(1,"sample parity");
                        emitted=emitted+1;
                    end
                end
                1: begin
                    // Bits 7:0 are PB0=0; PB1..3 CTS 0x06270 (25200), PB4..6 N 0x01800 (6144).
                    if(captured_sub[0][55:0]!=56'h00180070620000) $fatal(1,"ACR N/CTS");
                    acrs=acrs+1;
                end
                8'h82,8'h83,8'h84: begin
                    sum=int'(captured_header[7:0])+int'(captured_header[15:8])+int'(captured_header[23:16]);
                    for(j=0;j<4;j=j+1) for(b=0;b<7;b=b+1)
                        sum=sum+int'(captured_sub[j][b*8+:8]);
                    if(sum%256!=0) $fatal(1,"InfoFrame checksum");
                    infos=infos+1;
                end
                0: begin end
                default: $fatal(1,"unknown packet");
            endcase
        end
    endtask
    initial begin
        #200; @(negedge pix); reset=0;
        while(received<TOTAL) begin
            // One packet window per 800 pixels; leave a 768-pixel idle gap.
            @(negedge pix); enable=1;
            @(negedge pix); enable=0;island=1;
            captured_header=0;
            for(j=0;j<4;j=j+1) captured_sub[j]=0;
            for(i=0;i<32;i=i+1) begin
                if(counter!=i[4:0]) $fatal(1,"assembler alignment");
                captured_header[i]=serial[0];
                for(j=0;j<4;j=j+1) begin
                    captured_sub[j][2*i]=serial[1+j];
                    captured_sub[j][2*i+1]=serial[5+j];
                end
                @(negedge pix);
            end
            island=0;check_packet();slots=slots+1;
            repeat(767) @(negedge pix);
            // Includes a frame-end while audio groups are waiting.
            field_end=slots%525==0;
        end
        // The stall must produce exactly one silence run and flag underflow,
        // without losing or repeating source samples. The source ends here,
        // so the transport may already be muted again.
        if(ov || !uf || produced!=TOTAL || gap_runs!=1 || acrs<10 || infos<3 || max_credits>3)
            $fatal(1,"transport flags/counts ov=%0d uf=%0d gaps=%0d",ov,uf,gap_runs);
        // Verify checker detects corrupted payload, independently of PCM check.
        captured_sub[0][7]=~captured_sub[0][7];
        if(syndrome(captured_sub[0],64)==0) $fatal(1,"BCH failed to detect corruption");
        $display("PASS: tick-paced FIFO to packets, %0d stereo pairs + %0d silence (startup mute, one stall), max pending ticks %0d, BCH, parity/status, InfoFrame checksum and ACR",received,silences,max_credits);
        $finish;
    end
    // Pending 48kHz deadlines stay well below the 3-bit saturation point
    // even with one packet window per 800 pixels.
    integer max_credits=0;
    always @(posedge pix) if(!reset && transport.credits>max_credits) max_credits=transport.credits;
    // Continuous delivery must not underflow before the deliberate stall.
    initial begin
        wait(produced==STALL_AT); #1;
        if(uf || muted || ov) $fatal(1,"underflow/mute before stall");
        // Mute must be entered during the stall and released after refill.
        wait(muted);
        wait(produced==STALL_AT+512); #1;
        if(muted) $fatal(1,"mute not released after refill");
    end
    initial begin #70000000; $fatal(1,"audio packet timeout"); end
endmodule
