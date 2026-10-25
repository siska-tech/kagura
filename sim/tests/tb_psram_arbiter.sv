`timescale 1ns/1ps
// kagura_psram_arbiter against a 1-outstanding controller model with random
// command durations: response routing, data, and bounded waits on both ports.
module tb_psram_arbiter;
    localparam integer AW=8,MAX_BUSY=30;
    reg clk=0,reset=1;
    always #5 clk=~clk;

    reg p_want=0,p_wait_rsp=0;
    reg [AW-1:0] p_req_addr=0;
    wire p_cmd_rdy,p_rd_data_valid;
    wire [31:0] p_rd_data;
    wire p_cmd_en=p_want && !p_wait_rsp && p_cmd_rdy;

    reg h_cmd=0,h_cmd_en=0;
    reg [AW-1:0] h_addr=0;
    reg [31:0] h_wr_data=0;
    reg [3:0] h_data_mask=0;
    wire h_cmd_rdy,h_rd_data_valid;
    wire [31:0] h_rd_data;

    wire c_cmd,c_cmd_en;
    reg c_cmd_rdy=1;
    wire [AW-1:0] c_addr;
    wire [31:0] c_wr_data;
    wire [3:0] c_data_mask;
    reg [31:0] c_rd_data=0;
    reg c_rd_data_valid=0;

    kagura_psram_arbiter #(.ADDR_WIDTH(AW)) dut(
        .clk,.reset,.p_cmd(1'b0),.p_cmd_en,.p_cmd_rdy,.p_addr(p_req_addr),.p_rd_data,.p_rd_data_valid,
        .h_cmd,.h_cmd_en,.h_cmd_rdy,.h_addr,.h_wr_data,.h_data_mask,.h_rd_data,.h_rd_data_valid,
        .c_cmd,.c_cmd_en,.c_cmd_rdy,.c_addr,.c_wr_data,.c_data_mask,.c_rd_data,.c_rd_data_valid);

    // Controller model: memory updated on accept, read data after the command.
    reg [31:0] mem [0:(1<<AW)-1];
    integer busy=0;
    reg busy_read=0;
    reg [31:0] busy_data=0;
    integer errors=0;
    always @(posedge clk) begin
        c_rd_data_valid<=0;
        if(c_cmd_en) begin
            if(!c_cmd_rdy) begin errors++; $display("FAIL: cmd_en while busy"); end
            busy=1+$urandom_range(MAX_BUSY-1);
            busy_read=!c_cmd;
            busy_data=mem[c_addr];
            if(c_cmd) for(integer b=0;b<4;b++) if(!c_data_mask[b]) mem[c_addr][8*b +: 8]=c_wr_data[8*b +: 8];
            c_cmd_rdy<=0;
        end else if(busy>0) begin
            busy=busy-1;
            if(busy==0) begin
                if(busy_read) begin c_rd_data_valid<=1; c_rd_data<=busy_data; end
                c_cmd_rdy<=1;
            end
        end
    end

    // Shadow memory as seen by the host.
    reg [31:0] shadow [0:(1<<AW)-1];
    integer p_reads=0,h_reads=0,h_writes=0,p_wait=0,p_wait_max=0,h_wait=0,h_wait_max=0;
    reg [31:0] p_expect=0,h_expect=0;
    reg h_wait_rsp=0;

    // PCM side: byte-bridge style, wants randomly, never asserts without ready.
    always @(posedge clk) begin
        if(reset) begin p_want<=0; p_wait_rsp<=0; end
        else begin
            if(p_want && !p_wait_rsp) begin
                p_wait=p_wait+1;
                if(p_cmd_en) begin
                    if(p_wait>p_wait_max) p_wait_max=p_wait;
                    p_wait_rsp<=1; p_want<=0; p_expect=shadow[p_req_addr];
                end
            end
            if(p_rd_data_valid) begin
                if(!p_wait_rsp) begin errors++; $display("FAIL: stray PCM response"); end
                if(p_rd_data!==p_expect) begin errors++; $display("FAIL: PCM read %h expected %h",p_rd_data,p_expect); end
                p_wait_rsp<=0; p_reads++;
            end
            if(!p_want && !p_wait_rsp && !p_rd_data_valid && $urandom_range(3)==0) begin
                p_want<=1; p_wait=0; p_req_addr<=AW'($urandom);
            end
        end
    end

    // Host side: valid held until accepted, random reads/writes and masks.
    always @(posedge clk) begin
        if(reset) h_cmd_en<=0;
        else begin
            if(h_cmd_en) begin
                h_wait=h_wait+1;
                if(h_cmd_rdy) begin
                    if(h_wait>h_wait_max) h_wait_max=h_wait;
                    h_cmd_en<=0;
                    if(h_cmd) begin
                        for(integer b=0;b<4;b++) if(!h_data_mask[b]) shadow[h_addr][8*b +: 8]=h_wr_data[8*b +: 8];
                        h_writes++;
                    end else begin h_expect=shadow[h_addr]; h_wait_rsp<=1; end
                end
            end
            if(h_rd_data_valid) begin
                if(!h_wait_rsp) begin errors++; $display("FAIL: stray host response"); end
                if(h_rd_data!==h_expect) begin errors++; $display("FAIL: host read %h expected %h",h_rd_data,h_expect); end
                h_wait_rsp<=0; h_reads++;
            end
            if(!h_cmd_en && !h_wait_rsp && !h_rd_data_valid) begin
                h_cmd_en<=1; h_wait=0;
                h_cmd<=$urandom_range(1); h_addr<=AW'($urandom);
                h_wr_data<=$urandom; h_data_mask<=$urandom_range(3)==0 ? 4'($urandom) : 4'b0;
            end
        end
    end

    initial begin
        for(integer n=0;n<(1<<AW);n++) begin mem[n]=$urandom; shadow[n]=mem[n]; end
        repeat(3) @(negedge clk); reset=0;
        repeat(200000) @(negedge clk);
        // One command of the other port plus the in-flight one bounds each wait.
        if(p_wait_max>2*MAX_BUSY+2 || h_wait_max>2*MAX_BUSY+2) begin
            errors++; $display("FAIL: wait bound p=%0d h=%0d",p_wait_max,h_wait_max);
        end
        if(p_reads<1000 || h_reads<1000 || h_writes<1000) begin
            errors++; $display("FAIL: too little traffic p=%0d hr=%0d hw=%0d",p_reads,h_reads,h_writes);
        end
        if(errors==0) $display("PASS: tb_psram_arbiter p_reads=%0d h_reads=%0d h_writes=%0d max_wait p=%0d h=%0d",
            p_reads,h_reads,h_writes,p_wait_max,h_wait_max);
        else $display("FAIL: tb_psram_arbiter %0d errors",errors);
        $finish;
    end
endmodule
