// SPDX-License-Identifier: Apache-2.0
// Stage-2 integration model: a small W65C02S instruction model executes the
// documented 26-byte stub, while decode and SRAM models check ownership.
module tb_romless_boot_system;
    reg clk=0,reset=1,flash_miso=0;
    wire flash_cs_n,flash_sclk,flash_mosi,boot_ready,boot_error,unmap_request;
    wire [3:0] error_code;
    wire [23:0] jedec_id;
    reg req_valid=0,req_write=0,rsp_ready=1;
    reg [4:0] req_addr=0;
    reg [7:0] req_wdata=0;
    wire req_ready,rsp_valid,rsp_error;
    wire [7:0] rsp_rdata;
    reg [7:0] image [0:287];
    reg [7:0] sram [0:65535];
    integer i,failures=0,port_reads=0,payload_consumed=0;

    kagura_boot_controller #(.FLASH_CLK_DIV(2)) dut(clk,reset,
        flash_cs_n,flash_sclk,flash_mosi,flash_miso,
        boot_ready,boot_error,error_code,jedec_id,unmap_request,
        req_valid,req_ready,req_write,req_addr,req_wdata,
        rsp_valid,rsp_ready,rsp_rdata,rsp_error);
    always #5 clk=~clk;
    always @(posedge clk)
        if(dut.window.payload_ready) payload_consumed=payload_consumed+1;

    function automatic [31:0] crc32_byte(input [31:0] current,input [7:0] value);
        reg [31:0] c; integer bit_index;
        begin
            c=current;
            for(bit_index=0;bit_index<8;bit_index=bit_index+1)
                if(c[0]^value[bit_index]) c=(c>>1)^32'hedb88320; else c=c>>1;
            crc32_byte=c;
        end
    endfunction
    function automatic [31:0] image_crc(input integer first,input integer count);
        reg [31:0] c; integer index;
        begin
            c=32'hffffffff;
            for(index=0;index<count;index=index+1) c=crc32_byte(c,image[first+index]);
            image_crc=~c;
        end
    endfunction
    task automatic put32(input integer offset,input [31:0] value);
        begin
            image[offset]=value[7:0]; image[offset+1]=value[15:8];
            image[offset+2]=value[23:16]; image[offset+3]=value[31:24];
        end
    endtask
    function automatic [7:0] flash_byte(input [23:0] address);
        integer index;
        begin
            index={8'b0,address}-32'h00100000;
            if(index>=0 && index<288) flash_byte=image[index]; else flash_byte=8'hff;
        end
    endfunction

    reg previous_sclk=0,outputting=0;
    reg [7:0] input_shift=0,output_shift=0,command=0;
    reg [5:0] input_bits=0;
    reg [2:0] output_bit=0;
    reg [1:0] id_index=0;
    reg [23:0] flash_address=0;
    always @(posedge clk) begin
        previous_sclk<=flash_sclk;
        if(flash_cs_n) begin
            input_shift<=0; input_bits<=0; output_bit<=0; id_index<=0;
            command<=0; flash_address<=0; outputting<=0; flash_miso<=0;
        end else begin
            if(!previous_sclk && flash_sclk) begin
                input_shift<={input_shift[6:0],flash_mosi}; input_bits<=input_bits+1'b1;
                if(input_bits==7) begin
                    command<={input_shift[6:0],flash_mosi};
                    if({input_shift[6:0],flash_mosi}==8'h9f) begin output_shift<=8'h85; outputting<=1; end
                end else if(command==8'h03 && input_bits>=8 && input_bits<=31) begin
                    flash_address<={flash_address[22:0],flash_mosi};
                    if(input_bits==31) begin
                        output_shift<=flash_byte({flash_address[22:0],flash_mosi}); outputting<=1;
                    end
                end
            end
            if(previous_sclk && !flash_sclk && outputting) begin
                flash_miso<=output_shift[7];
                if(output_bit==7) begin
                    output_bit<=0;
                    if(command==8'h9f) begin
                        id_index<=id_index+1'b1;
                        if(id_index==0) output_shift<=8'h60; else output_shift<=8'h16;
                    end else begin
                        flash_address<=flash_address+1'b1;
                        output_shift<=flash_byte(flash_address+1'b1);
                    end
                end else begin output_shift<={output_shift[6:0],1'b0}; output_bit<=output_bit+1'b1; end
            end
        end
    end

    task automatic bus_read(input [15:0] address,output [7:0] value);
        begin
            if(address>=16'hffe0) begin
                @(negedge clk); req_addr=address[4:0]; req_write=0; req_valid=1;
                #1; while(!req_ready) @(negedge clk);
                @(posedge clk); @(negedge clk); req_valid=0;
                while(!rsp_valid) @(posedge clk);
                value=rsp_rdata;
                if(rsp_error) begin $display("FAIL: KAGURA read %04x",address); failures=failures+1; end
                if(address==16'hfffa) port_reads=port_reads+1;
                @(posedge clk);
            end else value=sram[address];
        end
    endtask
    task automatic bus_write(input [15:0] address,input [7:0] value);
        begin
            if(address>=16'hffe0) begin
                $display("FAIL: simultaneous/invalid SRAM write in boot window %04x",address);
                failures=failures+1;
            end else sram[address]=value;
        end
    endtask

    initial begin
        #3000000; $fatal(1,"timeout");
    end
    initial begin : cpu_model
        reg [31:0] value;
        reg [15:0] pc,address;
        reg [7:0] a,x,y,zp0,zp1,opcode,lo,hi,operand;
        reg z;
        integer steps;
        for(i=0;i<65536;i=i+1) sram[i]=8'hcc;
        for(i=0;i<288;i=i+1) image[i]=0;
        image[0]=8'h4b; image[1]=8'h39; image[2]=8'h42; image[3]=8'h54;
        image[4]=1; image[5]=32; image[6]=0; image[7]=1;
        image[8]=0; image[9]=8'h02; image[10]=8'h10; image[11]=8'h02;
        put32(12,256);
        for(i=0;i<256;i=i+1) image[32+i]=(i[7:0]^8'ha5);
        value=image_crc(32,256); put32(16,value);
        value=image_crc(0,28); put32(28,value);
        repeat(4) @(posedge clk); reset=0;
        while(!boot_ready && !boot_error) @(posedge clk);
        if(boot_error) $fatal(1,"controller error %0d",error_code);

        bus_read(16'hfffa,operand);
        bus_read(16'hfffc,lo); bus_read(16'hfffd,hi); pc={hi,lo};
        a=0; x=0; y=0; z=0; zp0=sram[0]; zp1=sram[1]; steps=0;
        while(pc!=16'h0210 && steps<5000) begin
            bus_read(pc,opcode); pc=pc+1'b1; steps=steps+1;
            case(opcode)
                8'h64: begin bus_read(pc,operand); pc=pc+1'b1; if(operand==0) begin zp0=0; sram[0]=0; end end
                8'had: begin
                    bus_read(pc,lo); bus_read(pc+1'b1,hi); pc=pc+2;
                    bus_read({hi,lo},a);
                end
                8'h85: begin
                    bus_read(pc,operand); pc=pc+1'b1;
                    if(operand==1) begin zp1=a; sram[1]=a; end else bus_write({8'b0,operand},a);
                end
                8'hae: begin
                    bus_read(pc,lo); bus_read(pc+1'b1,hi); pc=pc+2;
                    bus_read({hi,lo},x);
                end
                8'ha0: begin bus_read(pc,y); pc=pc+1'b1; end
                8'h91: begin
                    bus_read(pc,operand); pc=pc+1'b1; address={zp1,zp0}+{8'b0,y};
                    bus_write(address,a);
                end
                8'hc8: begin y=y+1'b1; z=(y==0); end
                8'hd0: begin
                    bus_read(pc,operand); pc=pc+1'b1;
                    if(!z) pc=pc+{{8{operand[7]}},operand};
                end
                8'he6: begin
                    bus_read(pc,operand); pc=pc+1'b1;
                    if(operand==1) begin zp1=zp1+1'b1; sram[1]=zp1; z=(zp1==0); end
                end
                8'hca: begin x=x-1'b1; z=(x==0); end
                8'h00: begin
                    bus_read(pc,operand); pc=pc+1'b1;
                    bus_read(16'hfffe,lo); bus_read(16'hffff,hi); pc={hi,lo};
                end
                default: begin $display("FAIL: opcode %02x at %04x",opcode,pc-1'b1); failures=failures+1; pc=16'h0210; end
            endcase
        end
        if(pc!=16'h0210) begin $display("FAIL: entry not reached, pc=%04x",pc); failures=failures+1; end
        for(i=0;i<256;i=i+1)
            if(sram[512+i]!==image[32+i]) begin
                $display("FAIL: SRAM[%04x]=%02x expected %02x",512+i,sram[512+i],image[32+i]);
                failures=failures+1;
            end
        if(payload_consumed!=256) begin $display("FAIL: consumed %0d",payload_consumed); failures=failures+1; end
        if(port_reads!=260) begin $display("FAIL: port reads %0d",port_reads); failures=failures+1; end
        repeat(2) @(posedge clk);
        if(!unmap_request) begin $display("FAIL: no unmap request"); failures=failures+1; end
        if(failures!=0) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: CPU stub copied 256 bytes, reached entry, and decode stayed exclusive");
        $finish;
    end
endmodule
