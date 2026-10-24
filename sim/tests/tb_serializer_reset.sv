`timescale 1ns/1ps

// Functional stub: the Gowin primitive's analogue recovery/removal behaviour
// is deliberately outside RTL simulation.  Keep RESET visible for checks.
module OSER10 (
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
    integer phase,i,edges;

    always #10 pixel=~pixel;
    always #2 serial=~serial;

    serializer dut(pixel,serial,reset,symbols,tmds,tmds_clock);

    task automatic check_release(input integer offset);
        begin
            // Assert at a different point in the FCLK period.  Assertion must
            // be asynchronous and must reach every OSER10 reset together.
            #(offset); reset=1; #0.1;
            if(dut.serial_reset!==2'b11 || dut.serial_reset_lane!==4'hf)
                $fatal(1,"phase %0d: reset did not assert asynchronously",offset);
            #7; reset=0;

            // Release is intentionally delayed through two synchronizer FFs
            // and one lane-local FF.  No lane may leave reset early.
            edges=0;
            while(dut.serial_reset_lane===4'hf && edges<4) begin
                @(posedge serial); #0.1; edges=edges+1;
                if(dut.serial_reset_lane!==4'hf && dut.serial_reset_lane!==4'h0)
                    $fatal(1,"phase %0d: lane reset skew %h",offset,dut.serial_reset_lane);
            end
            if(edges!=3 || dut.serial_reset_lane!==4'h0)
                $fatal(1,"phase %0d: release after %0d FCLK edges",offset,edges);
            repeat(2) @(posedge serial);
        end
    endtask

    initial begin
        for(i=0;i<3;i=i+1) symbols[i]=10'b0101010101;
        #1;
        // Offsets cover assertion/deassertion on and between modelled FCLK
        // edges; physical OSER10 recovery/removal remains a hardware test.
        for(phase=0;phase<4;phase=phase+1) check_release(phase);
        $display("PASS: serializer reset phase sweep, async assert, 3-edge synchronous four-lane release");
        $finish;
    end
    initial begin #1000; $fatal(1,"Serializer reset timeout"); end
endmodule
