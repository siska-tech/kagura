`timescale 1ns/1ps
// Poison all physical RAM, then verify zeros through real command reads.
module tb_vram_init;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,poison=0,valid=0,write_req=0,word_req=0,hold=1;
    reg [15:0] addr=0,wd=0;
    wire init_done,ready,rsp_valid,grant;
    wire [15:0] data;
    integer reads=0;
    kagura_vram dut(.clk(clk),.reset(reset),.init_done(init_done),.valid(valid),.ready(ready),
        .command_idle(),.audio_wave_read(1'b0),.audio_wave_swap(1'b0),.audio_wave_addr(9'b0),.audio_wave_data(),
        .write_in(write_req),.word_in(word_req),.addr_in(addr),.wdata_in(wd),.rsp_valid(rsp_valid),.rdata(data),
        .render_hold(hold),.render_grant(grant),.map_read(1'b0),.map_index(11'b0),.map_data(),
        .pattern_read(1'b0),.pattern_addr(15'b0),.pattern_data(),.palette_read(1'b0),.palette_index(10'b0),.palette_data(),
        .oam_read(1'b0),.oam_index(10'b0),.oam_data());
    genvar bank;
    generate for(bank=0;bank<16;bank=bank+1) begin: poison_patterns
        always @(posedge poison)
            for(integer n=0;n<2048;n=n+1) dut.pattern[bank].ram.memory[n]=8'ha5;
    end endgenerate
    always @(posedge poison) begin
        for(integer n=0;n<2048;n=n+1) begin
            dut.map_lo.memory[n]=8'hff; dut.map_hi.memory[n]=8'hff; dut.wave.memory[n]=8'hff;
        end
        for(integer n=0;n<1024;n=n+1) begin
            dut.word_ram[2].ram.ram.memory[n]=16'hffff;
            dut.word_ram[3].ram.ram.memory[n]=16'hffff;
        end
    end
    always @(negedge clk)
        if(!reset && !init_done && (ready || grant || rsp_valid)) $fatal(1,"port enabled before initialization");
    task automatic cold_start;
        integer ticks;
        begin
            @(negedge clk); reset=1; valid=0; poison=0; hold=1;
            @(negedge clk); poison=1;
            @(negedge clk); reset=0; ticks=0;
            while(!init_done) begin @(negedge clk); ticks=ticks+1; end
            if(ticks!=2048) $fatal(1,"init length %d",ticks);
            for(integer n=0;n<2048;n=n+1)
                if(dut.wave.memory[n]!==0) $fatal(1,"wave physical byte %d not clear",n);
            hold=0;
        end
    endtask
    task automatic read_zero(input reg word_access,input reg[15:0] a);
        begin
            @(negedge clk); valid=1; write_req=0; word_req=word_access; addr=a;
            @(posedge clk); while(!ready) @(posedge clk);
            @(negedge clk); valid=0;
            wait(rsp_valid); #1;
            if(data!==0) $fatal(1,"word=%0d addr=%04h got=%04h expected zero",word_access,a,data);
            reads=reads+1;
            @(negedge clk);
        end
    endtask
    task automatic check_all;
        begin
            for(integer a=0;a<16'h9000;a=a+1) read_zero(0,16'(a));
            for(integer a=0;a<1024;a=a+1) begin read_zero(1,16'(a)); read_zero(1,16'h8000+16'(a)); end
            for(integer a=16'h9800;a<16'h9a00;a=a+1) read_zero(0,16'(a));
        end
    endtask
    initial begin
        cold_start(); check_all();
        // A reset part way through clearing must restart the complete sweep.
        @(negedge clk); reset=1; poison=0;
        @(negedge clk); poison=1; reset=0;
        repeat(1000) @(negedge clk);
        if(init_done) $fatal(1,"premature ready");
        cold_start(); check_all();
        $display("PASS: startup RAM clear, %0d zero reads, all pattern/map/OAM/palette/wave banks, active/unused words, 2048-cycle sweep, reset restart and port exclusion",reads);
        $finish;
    end
    initial begin #50000000; $fatal(1,"startup timeout"); end
endmodule
