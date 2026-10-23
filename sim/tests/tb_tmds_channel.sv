`timescale 1ns/1ps
// Decode transmitted symbols rather than duplicating the encoder algorithm.
module tb_tmds_channel;
    reg clk=0;
    always #5 clk=~clk;
    reg [7:0] data=255;
    reg [3:0] island=0;
    reg [1:0] control=3;
    reg [2:0] mode=0;
    wire [9:0] symbol;
    tmds_channel #(.CN(0)) dut(clk,data,island,control,mode,symbol);
    reg [7:0] qm,decoded;
    integer i,j,k,ones,stimulus,disparity=0;
    reg [9:0] expected_control;
    initial begin
        for(i=0;i<4;i=i+1) begin
            @(negedge clk); control=i[1:0]; mode=0;
            @(posedge clk); #1;
            case(i)
                0:expected_control=10'b1101010100;
                1:expected_control=10'b0010101011;
                2:expected_control=10'b0101010100;
                3:expected_control=10'b1010101011;
            endcase
            if(symbol!==expected_control) $fatal(1,"control coding");
        end
        // Sweep all bytes in many consecutive permutations; disparity persists.
        for(k=0;k<32;k=k+1) begin
            for(i=0;i<256;i=i+1) begin
                @(negedge clk); stimulus=(i*73+k*19)%256; data=stimulus[7:0]; mode=1;
                @(posedge clk); #1;
                qm=symbol[9] ? ~symbol[7:0] : symbol[7:0];
                decoded[0]=qm[0];
                for(j=1;j<8;j=j+1)
                    decoded[j]=symbol[8] ? (qm[j]^qm[j-1]) : ~(qm[j]^qm[j-1]);
                if(decoded!==data) $fatal(1,"video roundtrip byte %0d",data);
                ones=0;
                for(j=0;j<10;j=j+1) ones=ones+(symbol[j] ? 1 : 0);
                disparity=disparity+2*ones-10;
                if(disparity>8 || disparity< -8) $fatal(1,"unbounded running disparity");
            end
        end
        $display("PASS: upstream TMDS control codes and 8192 video symbols decoded, disparity bounded");
        $finish;
    end
    initial begin #1000000; $fatal(1,"timeout"); end
endmodule
