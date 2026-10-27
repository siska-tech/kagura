// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps

// Board timing contract: CLK_DIV=4, with both earliest and provisional latest
// MISO responses. The flash model reacts to SCLK edges, independently of the
// reader's state/divider. Internal observation checks the actual capture enables.
module flash_reader_timing_case #(parameter integer RESPONSE_NS=0)(output reg finished=0);
    reg clk=0,reset=1,cmd_valid=0,cmd_jedec_id=0,data_ready=0;
    reg [23:0] cmd_addr=0,cmd_byte_count=0;
    wire cmd_ready,data_valid,done,error,cs_n,sclk,mosi;
    wire [7:0] data;
    reg miso=0;
    kagura_flash_reader #(.CLK_DIV(4)) dut(clk,reset,cmd_valid,cmd_ready,
        cmd_jedec_id,cmd_addr,cmd_byte_count,data_valid,data_ready,data,done,error,
        cs_n,sclk,mosi,miso);
    always #9.259 clk=~clk; // 54 MHz, matching system54 in boot*.sdc.

    reg [7:0] in_shift=0,out_shift=0,command=0;
    reg [23:0] address=0;
    integer in_bits=0,out_bit=0,id_index=0;
    reg outputting=0;
    function automatic [7:0] flash_byte(input [23:0] a);
        flash_byte=a[7:0]^8'h5a;
    endfunction
    always @(posedge sclk or negedge sclk or posedge cs_n) begin
        if(cs_n) begin
            in_shift=0; out_shift=0; command=0; address=0;
            in_bits=0; out_bit=0; id_index=0; outputting=0; miso<=0;
        end else if(sclk) begin
            in_shift={in_shift[6:0],mosi};
            if(in_bits==7) begin
                command=in_shift;
                if(in_shift==8'h9f) begin out_shift=8'h85; outputting=1; end
            end else if(command==8'h03 && in_bits>=8 && in_bits<=31) begin
                address={address[22:0],mosi};
                if(in_bits==31) begin out_shift=flash_byte(address); outputting=1; end
            end
            in_bits=in_bits+1;
        end else if(outputting) begin
            miso<=#(RESPONSE_NS) out_shift[7];
            if(out_bit==7) begin
                out_bit=0;
                if(command==8'h9f) begin
                    id_index=id_index+1;
                    out_shift=id_index==1 ? 8'h60 : 8'h16;
                end else begin address=address+1'b1; out_shift=flash_byte(address); end
            end else begin out_shift={out_shift[6:0],1'b0}; out_bit=out_bit+1; end
        end
    end

    integer cycle=0,last_fall=-100,last_sample=-100,samples=0,holds=0;
    reg prev_sclk=0,sampled=0;
    reg [7:0] expected_shift=0;
    reg last_bit=0;
    always @(posedge clk) begin
        cycle=cycle+1;
        sampled=!reset && dut.state==2 && dut.divider==3 && !sclk;
        expected_shift={dut.rx_shift[6:0],miso};
        last_bit=dut.rx_bits==7;
        if(sampled) begin
            if(cycle-last_fall<4) $fatal(1,"%0d ns: setup window below four cycles",RESPONSE_NS);
            samples=samples+1; last_sample=cycle;
        end
    end
    always @(negedge clk) begin
        if(reset) begin last_fall=-100; last_sample=-100; end
        else begin
            if(sampled && (dut.rx_shift!==expected_shift ||
               (last_bit && data!==expected_shift)))
                $fatal(1,"%0d ns: MISO capture differs from sampled value",RESPONSE_NS);
            if(prev_sclk && !sclk) begin
                if(last_sample>=0) begin
                    if(cycle-last_sample<4) $fatal(1,"%0d ns: hold window below four cycles",RESPONSE_NS);
                    holds=holds+1; last_sample=-100;
                end
                last_fall=cycle;
            end
        end
        prev_sclk=sclk;
    end

    integer received=0;
    reg [7:0] got [0:15];
    always @(posedge clk) if(!reset && data_valid && data_ready) begin
        got[received]=data; received=received+1;
    end
    task automatic start(input bit id,input [23:0] addr,input [23:0] count);
        while(!cmd_ready) @(negedge clk);
        cmd_jedec_id=id; cmd_addr=addr; cmd_byte_count=count; cmd_valid=1;
        @(negedge clk); cmd_valid=0;
    endtask
    task automatic wait_done;
        while(!done) @(negedge clk);
        @(negedge clk);
    endtask
    task automatic expect_byte(input integer index,input [7:0] expected);
        if(got[index]!==expected) $fatal(1,"%0d ns: byte %0d got %02x expected %02x",RESPONSE_NS,index,got[index],expected);
    endtask
    reg [7:0] paused_data;
    integer i,pause_cycles;
    initial begin
        repeat(4) @(negedge clk); reset=0; data_ready=1;
        start(1,0,0); wait_done();
        if(received!=3) $fatal(1,"JEDEC length");
        expect_byte(0,8'h85); expect_byte(1,8'h60); expect_byte(2,8'h16);

        // Different pauses on every byte exercise divider restart and the final
        // high half-period. Also allow the consumer to be ready immediately.
        received=0; data_ready=0; start(0,24'h100123,4);
        for(i=0;i<4;i=i+1) begin
            while(!data_valid) @(negedge clk);
            paused_data=data;
            pause_cycles=i*5;
            repeat(pause_cycles) begin
                @(negedge clk);
                if(sclk || !data_valid || data!==paused_data) $fatal(1,"unstable paused byte");
            end
            data_ready=1; @(negedge clk); data_ready=0;
        end
        wait_done();
        if(received!=4) $fatal(1,"READ length");
        expect_byte(0,8'h79); expect_byte(1,8'h7e); expect_byte(2,8'h7f); expect_byte(3,8'h7c);
        if(samples!=56 || holds!=56) $fatal(1,"timing coverage: samples=%0d holds=%0d",samples,holds);

        // Abort in each SCLK half-period and while a byte waits for its consumer.
        // Reset invalidates the in-flight sample; recovery must begin a fresh ID.
        for(i=0;i<3;i=i+1) begin
            received=0; data_ready=0; start(1,0,0);
            if(i==2) while(!data_valid) @(negedge clk);
            else begin
                while(dut.state!=2 || sclk!=(i==1)) @(negedge clk);
                @(negedge clk);
            end
            reset=1; repeat(4) @(negedge clk);
            if(!cs_n || sclk || data_valid || !cmd_ready) $fatal(1,"reset did not idle reader");
            reset=0; received=0; data_ready=1;
            start(1,0,0); wait_done();
            if(received!=3) $fatal(1,"reset recovery length");
            expect_byte(0,8'h85); expect_byte(1,8'h60); expect_byte(2,8'h16);
        end
        received=0; start(0,0,0); wait_done();
        if(!error || received!=0) $fatal(1,"invalid command was not rejected");
        $display("PASS: MISO %0d ns response, setup/hold windows, byte pauses and reset recovery",RESPONSE_NS);
        finished=1;
    end
endmodule

module tb_flash_reader_timing;
    wire earliest_done,latest_done;
    flash_reader_timing_case #(.RESPONSE_NS(0)) earliest(earliest_done);
    flash_reader_timing_case #(.RESPONSE_NS(55)) latest(latest_done);
    initial begin
        wait(earliest_done && latest_done);
        $display("PASS: boot MISO timing contract at CLK_DIV=4");
        $finish;
    end
    initial begin #200000; $fatal(1,"flash timing test timeout"); end
endmodule
