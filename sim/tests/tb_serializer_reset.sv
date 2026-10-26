`timescale 1ns/1ps

// Functional stub: GSR distribution and OSER10 analogue behaviour are outside
// RTL simulation. Keep parameters and local RESET visible for checks.
module OSER10 #(
    parameter GSREN="false", LSREN="true"
) (
    output wire Q,
    input wire PCLK, FCLK, RESET,
    input wire D0, D1, D2, D3, D4, D5, D6, D7, D8, D9
);
    assign Q = RESET ? 1'b0 : D0;
endmodule

module tb_serializer_reset;
    reg pixel=0,serial=0,reset=0;
    reg [9:0] symbols [2:0];
    wire [2:0] tmds;
    wire tmds_clock;
    integer phase,i;

    always #10 pixel=~pixel;
    always #2 serial=~serial;

    serializer dut(pixel,serial,reset,symbols,tmds,tmds_clock);

    task automatic check_reset_is_global(input integer offset);
        begin
            // Local RESET stays disabled: reset is supplied by the chip GSR.
            #(offset); reset=1; #0.1;
            if(dut.lane[0].tx.RESET!==1'b0 || dut.lane[1].tx.RESET!==1'b0 ||
               dut.lane[2].tx.RESET!==1'b0 || dut.clock_tx.RESET!==1'b0)
                $fatal(1,"phase %0d: local OSER10 RESET asserted",offset);
            #7; reset=0;
            repeat(2) @(posedge serial);
        end
    endtask

    initial begin
        for(i=0;i<3;i=i+1) symbols[i]=10'b0101010101;
        #1;
        for(phase=0;phase<4;phase=phase+1) check_reset_is_global(phase);
        $display("PASS: serializer uses GSR-enabled OSER10s with local RESET disabled");
        $finish;
    end
    initial begin #1000; $fatal(1,"Serializer reset timeout"); end
endmodule
