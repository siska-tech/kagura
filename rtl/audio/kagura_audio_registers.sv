// SPDX-License-Identifier: Apache-2.0
// Indexed shadow registers and the one outstanding AUDIO_COMMIT snapshot.
// Capture is driven only by successful queue admission; completion comes
// from the ordered engine after the synthesizer has applied the snapshot.
module kagura_audio_registers (
    input wire clk,reset,index_write,data_write,
    input wire [7:0] wdata,
    output reg [7:0] index,
    output reg [7:0] rdata,
    output reg read_legal,write_legal,
    output reg settings_valid,
    input wire capture,commit_done,
    output reg apply_busy,
    input wire underflow_event,overflow_event,muted,
    output wire [7:0] status,
    output reg [143:0] snapshot_step,
    output reg [23:0] snapshot_duty,
    output reg [47:0] snapshot_l,snapshot_r,
    output reg [5:0] snapshot_enable,snapshot_reset,
    output reg [7:0] snapshot_len,snapshot_master,
    output reg [15:0] snapshot_period
);
    reg [143:0] steps;
    reg [23:0] duties;
    reg [47:0] gains_l,gains_r;
    reg [5:0] enables,resets;
    reg [15:0] lengths,noise_period;
    reg [7:0] master;
    reg underflow,overflow;
    reg capture_pending;
    reg [5:0] captured_resets;
    wire [2:0] ch=index[6:4];
    wire [3:0] offset=index[3:0];
    wire channel_index=index<8'h60;
    assign status={4'b0,muted,overflow,underflow,apply_busy};
    reg [7:0] channel_data [0:5];
    reg [7:0] global_data;
    reg valid_settings;
    always @* begin
        rdata=0; read_legal=1; write_legal=channel_index;
        if(channel_index) begin
            for(integer c=0;c<6;c=c+1) rdata=rdata | (channel_data[c] & {8{ch==c}});
        end else begin
            rdata=global_data;
            case(index)
            8'he0: write_legal=1;
            8'he1: ;
            8'he2: begin read_legal=0; write_legal=1; end
            default: ;
            endcase
        end
        valid_settings=lengths[7:0]>=5 && lengths[7:0]<=8 && lengths[15:8]>=5 && lengths[15:8]<=8;
        for(integer c=0;c<6;c=c+1) if(c!=3 && steps[24*c+23]) valid_settings=0;
    end
    // Predecode the offset for each channel in parallel, then select the
    // channel into the ordinary bus response. The two-edge request interval
    // leaves one edge after every index/shadow write for this cache.
    always @(posedge clk)
        if(reset) begin
            for(integer c=0;c<6;c=c+1) channel_data[c]<=0;
            global_data<=0; settings_valid<=1;
        end else begin
            settings_valid<=valid_settings;
            global_data<=index==8'he0 ? master : index==8'he1 ? status : 8'b0;
            for(integer c=0;c<6;c=c+1) begin
                channel_data[c]<=0;
                case(offset)
                    0: if(c!=3) channel_data[c]<=steps[24*c +:8];
                    1: if(c!=3) channel_data[c]<=steps[24*c+8 +:8];
                    2: if(c!=3) channel_data[c]<=steps[24*c+16 +:8];
                    3: if(c<3) channel_data[c]<=duties[8*c +:8];
                    4: channel_data[c]<=gains_l[8*c +:8];
                    5: channel_data[c]<=gains_r[8*c +:8];
                    6: channel_data[c]<={6'b0,resets[c],enables[c]};
                    7: if(c>=4) channel_data[c]<=lengths[8*(c-4) +:8];
                    8: if(c==3) channel_data[c]<=noise_period[7:0];
                    9: if(c==3) channel_data[c]<=noise_period[15:8];
                    default: ;
                endcase
            end
        end
    wire clear_underflow=data_write && index==8'he2 && wdata[1];
    wire clear_overflow=data_write && index==8'he2 && wdata[2];
    always @(posedge clk)
        if(reset) begin
            index<=0; steps<=0; duties<=0; gains_l<=0; gains_r<=0; enables<=0; resets<=0;
            lengths<=16'h0505; noise_period<=0; master<=32; underflow<=0; overflow<=0; apply_busy<=0;
            capture_pending<=0; captured_resets<=0;
            snapshot_step<=0; snapshot_duty<=0; snapshot_l<=0; snapshot_r<=0;
            snapshot_enable<=0; snapshot_reset<=0; snapshot_len<=8'h55; snapshot_master<=32; snapshot_period<=0;
        end else begin
            capture_pending<=capture;
            underflow<=(underflow && !clear_underflow) || underflow_event;
            overflow<=(overflow && !clear_overflow) || overflow_event;
            if(index_write) index<=wdata;
            if(data_write && write_legal) begin
                if(channel_index) begin
                    for(integer c=0;c<6;c=c+1) if(ch==c) case(offset)
                        0: if(c!=3) steps[24*c +:8]<=wdata;
                        1: if(c!=3) steps[24*c+8 +:8]<=wdata;
                        2: if(c!=3) steps[24*c+16 +:8]<=wdata;
                        3: if(c<3) duties[8*c +:8]<=wdata;
                        4: gains_l[8*c +:8]<=wdata;
                        5: gains_r[8*c +:8]<=wdata;
                        6: begin enables[c]<=wdata[0]; resets[c]<=wdata[1]; end
                        7: if(c>=4) lengths[8*(c-4) +:8]<=wdata;
                        8: if(c==3) noise_period[7:0]<=wdata;
                        9: if(c==3) noise_period[15:8]<=wdata;
                        default: ;
                    endcase
                end
                else if(index==8'he0) master<=wdata;
            end
            if(commit_done) apply_busy<=0;
            if(capture) begin
                apply_busy<=1;
                captured_resets<=resets; resets<=0;
            end
            // Shadow registers cannot be written on the following edge:
            // the bus request stage enforces a two-edge access interval.
            // Stage the high-fanout snapshot enable in that unused edge.
            if(capture_pending) begin
                snapshot_step<=steps; snapshot_duty<=duties; snapshot_l<=gains_l; snapshot_r<=gains_r;
                snapshot_enable<=enables; snapshot_reset<=captured_resets;
                snapshot_len<={lengths[11:8],lengths[3:0]}; snapshot_master<=master; snapshot_period<=noise_period;
            end
        end
// synthesis translate_off
    always @(posedge clk)
        if(!reset && capture && (apply_busy || !settings_valid)) $fatal(1,"invalid audio snapshot admission");
// synthesis translate_on
endmodule
