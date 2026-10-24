// SPDX-License-Identifier: Apache-2.0
module tb_boot_controller;
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
    integer i,failures=0;

    kagura_boot_controller #(.FLASH_CLK_DIV(2)) dut(clk,reset,
        flash_cs_n,flash_sclk,flash_mosi,flash_miso,
        boot_ready,boot_error,error_code,jedec_id,unmap_request,
        req_valid,req_ready,req_write,req_addr,req_wdata,
        rsp_valid,rsp_ready,rsp_rdata,rsp_error);
    always #5 clk=~clk;

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

    // Mode-0 SPI NOR model supporting 9f and 03 commands.
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
                    if({input_shift[6:0],flash_mosi}==8'h9f) begin
                        output_shift<=8'h85; outputting<=1;
                    end
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

    task automatic read_window(input [4:0] address,input [7:0] expected);
        begin
            @(negedge clk);
            req_addr=address; req_valid=1;
            #1; while(!req_ready) @(negedge clk);
            @(posedge clk); @(negedge clk); req_valid=0;
            while(!rsp_valid) @(posedge clk);
            if(rsp_error || rsp_rdata!==expected) begin
                $display("FAIL: window %02x got %02x expected %02x",address,rsp_rdata,expected);
                failures=failures+1;
            end
            @(posedge clk);
        end
    endtask

    initial begin
        #2000000;
        $display("timeout controller=%0d reader=%0d checker=%0d rsp=%0d req=%0d/%0d fvalid=%0d fpready=%0d remain=%0d id=%06x error=%0d/%0d",
            dut.state,dut.reader.state,dut.image_check_i.state,rsp_valid,req_valid,req_ready,
            dut.flash_data_valid,dut.window_payload_ready,dut.window.payload_remaining,
            jedec_id,boot_error,error_code);
        $fatal(1,"timeout");
    end
    initial begin
        reg [31:0] value;
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
        if(boot_error) begin $display("FAIL: controller error %0d",error_code); failures=failures+1; end
        if(jedec_id!=24'h856016) begin $display("FAIL: JEDEC %06x",jedec_id); failures=failures+1; end
        read_window(5'h1c,8'he0); read_window(5'h1d,8'hff);
        read_window(5'h1a,8'h02); read_window(5'h1a,8'h01);
        read_window(5'h1a,8'ha5); read_window(5'h1a,8'ha4); read_window(5'h1a,8'ha7);
        read_window(5'h1e,8'h10); read_window(5'h1f,8'h02); @(negedge clk);
        if(!unmap_request) begin $display("FAIL: unmap request"); failures=failures+1; end
        if(failures!=0) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: JEDEC, two-pass validation, prefetch and boot-window integration");
        $finish;
    end
endmodule
