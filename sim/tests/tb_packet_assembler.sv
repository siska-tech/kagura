`timescale 1ns/1ps
// kagura_packet_assembler against the unchanged hdl-util packet_assembler:
// identical counter every cycle and identical packet_data in every data
// island pixel. Header/sub change only on the edge into a packet, as
// kagura_audio_packets does on packet_enable; runs of 1..18 packets with
// random gaps, and resets in the middle of packets.
module tb_packet_assembler;
    reg clk=0; always #6.734 clk=~clk;
    reg reset=1, island=0;
    reg [23:0] header=0;
    logic [55:0] sub [3:0];
    wire [8:0] want, got;
    wire [4:0] want_counter, got_counter;
    packet_assembler reference(.clk_pixel(clk),.reset(reset),.data_island_period(island),
        .header(header),.sub(sub),.packet_data(want),.counter(want_counter));
    kagura_packet_assembler dut(.clk_pixel(clk),.reset(reset),.data_island_period(island),
        .header(header),.sub(sub),.packet_data(got),.counter(got_counter));
    integer checked=0, packets=0, resets=0;
    always @(posedge clk) begin
        if(got_counter!==want_counter) $fatal(1,"counter %0d expected %0d",got_counter,want_counter);
        if(island && !reset) begin
            if(got!==want) $fatal(1,"packet_data %03h expected %03h at counter %0d",got,want,want_counter);
            checked=checked+1;
        end
    end
    task automatic new_packet;
        begin
            header={$urandom}; header=header&24'hffffff;
            for(int i=0;i<4;i++) sub[i]={$urandom,$urandom};
        end
    endtask
    initial begin
        for(int i=0;i<4;i++) sub[i]=0;
        repeat(3) @(negedge clk); reset=0;
        for(int run=0;run<3000;run++) begin
            repeat($urandom_range(0,40)) @(negedge clk);
            for(int p=$urandom_range(1,18);p>0;p--) begin
                new_packet(); island=1; packets=packets+1;
                for(int c=0;c<32;c++) begin
                    @(negedge clk);
                    if(run%97==5 && p==1 && c==13) begin
                        // Reset in the middle of a packet ends the run.
                        reset=1; island=0; resets=resets+1;
                        @(negedge clk); reset=0; break;
                    end
                end
            end
            island=0;
        end
        @(negedge clk);
        $display("PASS: packet assembler matches hdl-util, %0d packets, %0d island pixels, %0d resets",packets,checked,resets);
        $finish;
    end
endmodule
