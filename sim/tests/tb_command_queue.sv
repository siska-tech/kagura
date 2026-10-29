`timescale 1ns/1ps
// Full 64-bit descriptor order, staging, full capacity, held head, wrap/reset.
module tb_command_queue;
    reg clk=0; always #5 clk=~clk;
    reg reset=1,push=0,pop=0;
    reg [63:0] desc=0;
    wire ready,idle,staging,head_valid;
    wire [5:0] free_slots;
    wire [63:0] head;
    kagura_command_queue dut(clk,reset,push,desc,ready,free_slots,idle,staging,head_valid,head,pop);
    reg [63:0] expected [0:1023];
    integer written=0,read_count=0;
    task automatic enqueue(input [63:0] value);
        @(negedge clk);
        while(!ready) @(negedge clk);
        push=1; desc=value;
        @(negedge clk); push=0;
        expected[written]=value; written++;
    endtask
    task automatic dequeue;
        reg [63:0] held;
        @(negedge clk);
        while(!head_valid) @(negedge clk);
        held=head;
        if(head!==expected[read_count]) $fatal(1,"descriptor %0d mismatch",read_count);
        repeat(3) begin
            @(negedge clk);
            if(!head_valid || head!==held) $fatal(1,"head changed without pop");
        end
        pop=1; @(negedge clk); pop=0; read_count++;
    endtask
    initial begin
        repeat(3) @(negedge clk); reset=0;
        if(!idle || free_slots!==32 || head_valid) $fatal(1,"queue reset");
        // Multiple complete wraps, all bits random (not just data/opcode).
        for(integer lap=0;lap<8;lap++) begin
            for(integer n=0;n<32;n++) enqueue({$urandom,$urandom});
            while(staging) @(negedge clk);
            if(free_slots!==0 || ready || idle) $fatal(1,"queue full accounting");
            for(integer n=0;n<32;n++) dequeue();
            @(negedge clk);
            if(!idle || free_slots!==32 || head_valid) $fatal(1,"queue drain");
        end
        // Reset interrupts an unpublished staged descriptor and a queued head.
        enqueue(64'hffffffffffffffff);
        @(negedge clk); reset=1;
        repeat(2) @(negedge clk); reset=0;
        written=0; read_count=0;
        enqueue(64'h0123456789abcdef); dequeue();
        @(negedge clk);
        if(!idle || free_slots!==32) $fatal(1,"queue reset recovery");
        $display("PASS: 32x64 queue, 256 random descriptors, full/held head, eight wraps, staged reset recovery");
        $finish;
    end
    initial begin #1000000; $fatal(1,"queue timeout"); end
endmodule
