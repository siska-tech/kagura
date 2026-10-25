// SPDX-License-Identifier: Apache-2.0
// Atomic once-per-second snapshot; 115200 8N1 at system54.
// PCM N <samples> R <bytes> D <data errors> M <mix errors> F <faults> A <active> H <HDMI>
//     W <host words> E <host errors> L <max PCM byte wait, cycles>
module kagura_pcm_uart_status #(
    parameter integer REPORT_CYCLES=54000000
) (
    input wire clk,reset,
    input wire [31:0] checked_samples,read_bytes,data_errors,mix_errors,host_words,host_errors,
    input wire [15:0] pcm_wait_max,
    input wire [7:0] faults,
    input wire [1:0] active,hdmi_errors,
    output wire uart_tx
);
    reg [25:0] timer;
    reg sending,tx_start;
    reg [7:0] tx_data;
    reg [9:0] tx_shift;
    reg [8:0] tx_div;
    reg [3:0] tx_bits;
    wire tx_busy=tx_bits!=0;
    assign uart_tx=tx_shift[0];
    always @(posedge clk) begin
        if(reset) begin tx_shift<=10'h3FF; tx_bits<=0; tx_div<=0; end
        else if(!tx_busy) begin
            if(tx_start) begin tx_shift<={1'b1,tx_data,1'b0}; tx_bits<=10; tx_div<=468; end
        end else if(tx_div==0) begin
            tx_shift<={1'b1,tx_shift[9:1]}; tx_bits<=tx_bits-1'b1; tx_div<=468;
        end else tx_div<=tx_div-1'b1;
    end
    function automatic [7:0] hex(input [3:0] n);
        hex=n<10 ? 8'h30+8'(n) : 8'h41+8'(n)-8'd10;
    endfunction
    reg [7:0] msg [0:90];
    reg [6:0] index;
    integer k;
    always @(posedge clk) begin
        if(reset) begin timer<=0; sending<=0; index<=0; tx_start<=0; tx_data<=0; end
        else begin
            tx_start<=0;
            if(timer==26'(REPORT_CYCLES-1)) begin
                timer<=0;
                if(!sending && !tx_busy && !tx_start) begin
                    msg[0]<="P"; msg[1]<="C"; msg[2]<="M"; msg[3]<=" "; msg[4]<="N"; msg[5]<=" ";
                    msg[14]<=" "; msg[15]<="R"; msg[16]<=" ";
                    msg[25]<=" "; msg[26]<="D"; msg[27]<=" ";
                    msg[36]<=" "; msg[37]<="M"; msg[38]<=" ";
                    for(k=0;k<8;k=k+1) begin
                        msg[6+k]<=hex(checked_samples[31-4*k -: 4]);
                        msg[17+k]<=hex(read_bytes[31-4*k -: 4]);
                        msg[28+k]<=hex(data_errors[31-4*k -: 4]);
                        msg[39+k]<=hex(mix_errors[31-4*k -: 4]);
                    end
                    msg[47]<=" "; msg[48]<="F"; msg[49]<=" ";
                    msg[50]<=hex(faults[7:4]); msg[51]<=hex(faults[3:0]);
                    msg[52]<=" "; msg[53]<="A"; msg[54]<=" "; msg[55]<=hex({2'b0,active});
                    msg[56]<=" "; msg[57]<="H"; msg[58]<=" "; msg[59]<=hex({2'b0,hdmi_errors});
                    msg[60]<=" "; msg[61]<="W"; msg[62]<=" ";
                    msg[71]<=" "; msg[72]<="E"; msg[73]<=" ";
                    msg[82]<=" "; msg[83]<="L"; msg[84]<=" ";
                    for(k=0;k<8;k=k+1) begin
                        msg[63+k]<=hex(host_words[31-4*k -: 4]);
                        msg[74+k]<=hex(host_errors[31-4*k -: 4]);
                    end
                    for(k=0;k<4;k=k+1) msg[85+k]<=hex(pcm_wait_max[15-4*k -: 4]);
                    msg[89]<=8'h0D; msg[90]<=8'h0A;
                    sending<=1; index<=0;
                end
            end else timer<=timer+1'b1;
            if(sending && !tx_busy && !tx_start) begin
                tx_data<=msg[index]; tx_start<=1;
                if(index==90) sending<=0;
                else index<=index+1'b1;
            end
        end
    end
endmodule
