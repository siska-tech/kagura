// SPDX-License-Identifier: Apache-2.0
module tb_boot_image_check;
    reg clk=0,reset=1,start=0,in_valid=0;
    reg [7:0] in_data=0;
    wire in_ready,done,accepted;
    wire [3:0] error_code;
    wire [15:0] load_addr,entry_addr;
    wire [31:0] payload_length,payload_crc32;
    reg [7:0] image [0:287];
    integer failures=0,i;

    kagura_boot_image_check dut(clk,reset,start,in_valid,in_ready,in_data,
        done,accepted,error_code,load_addr,entry_addr,payload_length,payload_crc32);
    always #5 clk=~clk;

    function automatic [31:0] crc32_byte(input [31:0] current,input [7:0] value);
        reg [31:0] c;
        integer bit_index;
        begin
            c=current;
            for(bit_index=0;bit_index<8;bit_index=bit_index+1)
                if(c[0]^value[bit_index]) c=(c>>1)^32'hedb88320; else c=c>>1;
            crc32_byte=c;
        end
    endfunction
    function automatic [31:0] image_crc(input integer first,input integer count);
        reg [31:0] c;
        integer index;
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
    task automatic make_image;
        reg [31:0] value;
        begin
            for(i=0;i<288;i=i+1) image[i]=0;
            image[0]=8'h4b; image[1]=8'h39; image[2]=8'h42; image[3]=8'h54;
            image[4]=1; image[5]=32; image[6]=0; image[7]=1;
            image[8]=0; image[9]=8'h02;       // load $0200
            image[10]=8'h10; image[11]=8'h02; // entry $0210
            put32(12,256);
            for(i=0;i<256;i=i+1) image[32+i]=(i[7:0]^8'ha5);
            value=image_crc(32,256); put32(16,value);
            value=image_crc(0,28); put32(28,value);
        end
    endtask
    task automatic run_image(input [3:0] expected_error,input expected_accept);
        integer index;
        begin
            start=1; @(posedge clk); start=0;
            for(index=0;index<32;index=index+1) begin
                while(!in_ready) @(posedge clk);
                in_data=image[index]; in_valid=1; @(posedge clk); in_valid=0;
            end
            if(expected_error==0 || expected_error==7) begin
                for(index=32;index<288;index=index+1) begin
                    while(!in_ready) @(posedge clk);
                    in_data=image[index]; in_valid=1; @(posedge clk); in_valid=0;
                end
            end
            while(!done) @(posedge clk);
            if(accepted!==expected_accept || error_code!==expected_error) begin
                $display("FAIL: accepted=%0d error=%0d expected %0d/%0d",
                    accepted,error_code,expected_accept,expected_error);
                failures=failures+1;
            end
            @(posedge clk);
        end
    endtask

    initial begin
        repeat(4) @(posedge clk); reset=0;
        make_image(); run_image(0,1);
        if(load_addr!=16'h0200 || entry_addr!=16'h0210 || payload_length!=256) begin
            $display("FAIL: decoded metadata"); failures=failures+1;
        end
        make_image(); image[0]=0; run_image(1,0);
        make_image(); image[6]=1; put32(28,image_crc(0,28)); run_image(2,0);
        make_image(); image[20]=1; put32(28,image_crc(0,28)); run_image(3,0);
        make_image(); image[28]=image[28]^1; run_image(4,0);
        make_image(); image[9]=8'h01; put32(28,image_crc(0,28)); run_image(5,0);
        make_image(); image[10]=8'h00; image[11]=8'h03; put32(28,image_crc(0,28)); run_image(6,0);
        make_image(); image[100]=image[100]^1; run_image(7,0);
        if(failures!=0) $fatal(1,"%0d failure(s)",failures);
        $display("PASS: boot image header, range, entry and payload CRC checks");
        $finish;
    end
endmodule
