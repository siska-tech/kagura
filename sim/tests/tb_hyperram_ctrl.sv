// SPDX-License-Identifier: Apache-2.0
// Cycle-level HyperRAM protocol checker for kagura_hyperram_ctrl. It decodes
// the CA words independently of the controller and fails on protocol errors.
module tb_hyperram_ctrl;
    localparam integer LAT=12,RDL=2,ADDR_W=12,CSHI=2,INIT=64;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;

    reg cmd=0,cmd_en=0,cmd_reg=0;
    reg [ADDR_W-1:0] addr=0;
    reg [31:0] wr_data=0;
    reg [3:0] data_mask=0;
    wire cmd_rdy,rd_data_valid,init_calib;
    wire [31:0] rd_data;
    wire phy_reset_n,phy_cs_n,phy_ck_en,phy_dq_oe,phy_rwds_oe,phy_rwds_o_rise,phy_rwds_o_fall;
    wire [7:0] phy_dq_o_rise,phy_dq_o_fall;
    wire [7:0] phy_dq_i_rise,phy_dq_i_fall;

    kagura_hyperram_ctrl #(
        .ADDR_WIDTH(ADDR_W),                        .CS_HIGH_CYCLES(CSHI),.INIT_CYCLES(INIT)
            ) dut(.clk,.rst_n,.lat_cycles(5'(LAT)),.rd_latency(3'(RDL)),.cmd,.cmd_reg,.cmd_en,.cmd_rdy,.addr,.wr_data,.data_mask,.rd_data,
          .rd_data_valid,.init_calib,.phy_reset_n,.phy_cs_n,.phy_ck_en,.phy_dq_oe,
          .phy_dq_o_rise,.phy_dq_o_fall,.phy_rwds_oe,.phy_rwds_o_rise,.phy_rwds_o_fall,
          .phy_dq_i_rise,.phy_dq_i_fall);

    reg [7:0] mem [0:4095];
    reg [15:0] cr0=0;
    integer errors=0;
    integer k=0;                 // CK cycle index inside a CS window
    reg [47:0] ca_shift=0;
    reg is_read=0,is_reg=0;
    integer base=0;
    reg [7:0] rd_pipe_r [0:7];
    reg [7:0] rd_pipe_f [0:7];
    // Data the memory drives in cycle T reaches the controller in cycle T+RDL.
    assign phy_dq_i_rise=rd_pipe_r[RDL-1];
    assign phy_dq_i_fall=rd_pipe_f[RDL-1];
    integer i;
    integer cs_high_run=100;
    integer cfg_writes=0;
    reg reset_seen_low=0;
    reg cs_n_q=1;

    task automatic fail(input [255:0] msg);
        begin errors=errors+1; $display("FAIL: %0s at %0t",msg,$time); end
    endtask

    always @(posedge clk) begin
        // shift the memory-driven pair toward the controller by RDL cycles
        for(i=RDL-1;i>0;i=i-1) begin rd_pipe_r[i]<=rd_pipe_r[i-1]; rd_pipe_f[i]<=rd_pipe_f[i-1]; end
        rd_pipe_r[0]<=8'hxx; rd_pipe_f[0]<=8'hxx;
        if(!phy_reset_n) reset_seen_low<=1;
        cs_n_q<=phy_cs_n;

        if(phy_cs_n) begin
            if(!cs_n_q) begin cs_high_run<=1; end else cs_high_run<=cs_high_run+1;
            k<=0;
        end else begin
            if(cs_n_q) begin
                if(cs_high_run<CSHI) fail("CS high time");
                if(!reset_seen_low || !phy_reset_n) fail("access without reset pulse");
                k<=0;
            end
            if(phy_ck_en) begin
                if(k<3) begin
                    if(!phy_dq_oe) fail("CA not driven");
                    ca_shift={ca_shift[31:0],phy_dq_o_rise,phy_dq_o_fall};
                    if(k==2) begin
                        // reconstruct the CA that includes this last pair
                        is_read=ca_shift[47];
                        is_reg=ca_shift[46];
                        if(!ca_shift[45]) fail("burst type not linear");
                        if(ca_shift[15:3]!==0) fail("reserved CA bits");
                        base={ca_shift[44:16],ca_shift[2:0]}*2;
                        if(ca_shift[46] && ({ca_shift[44:16],ca_shift[2:0]})!==32'h800) fail("CR0 address");
                    end
                end else begin
                    if(is_reg && is_read) begin
                        if(phy_dq_oe) fail("bus contention on register read");
                        if(k==LAT) begin
                            rd_pipe_r[0]<=cr0[15:8];
                            rd_pipe_f[0]<=cr0[7:0];
                        end else if(k==LAT+1) begin
                            rd_pipe_r[0]<=8'h00;
                            rd_pipe_f[0]<=8'h00;
                        end
                    end else if(is_reg) begin
                        if(k==3) begin
                            if(!phy_dq_oe) fail("CR write not driven");
                            if(phy_rwds_oe) fail("RWDS driven on register write");
                            cr0<={phy_dq_o_rise,phy_dq_o_fall};
                            cfg_writes<=cfg_writes+1;
                        end
                    end else if(k>=LAT && k<LAT+2) begin
                        if(is_read) begin
                            if(phy_dq_oe) fail("bus contention on read");
                            rd_pipe_r[0]<=mem[base+2*(k-LAT)];
                            rd_pipe_f[0]<=mem[base+2*(k-LAT)+1];
                        end else begin
                            if(!phy_dq_oe || !phy_rwds_oe) fail("write data not driven");
                            if(!phy_rwds_o_rise) mem[base+2*(k-LAT)]<=phy_dq_o_rise;
                            if(!phy_rwds_o_fall) mem[base+2*(k-LAT)+1]<=phy_dq_o_fall;
                        end
                    end else if(phy_dq_oe) fail("DQ driven during latency");
                end
                k<=k+1;
            end
        end
        if(phy_cs_n && (phy_ck_en||phy_dq_oe||phy_rwds_oe)) fail("activity with CS high");
    end

    task automatic issue(input is_write,input [ADDR_W-1:0] a,input [31:0] d,input [3:0] m);
        begin
            @(negedge clk);
            wait(cmd_rdy);
            @(negedge clk);
            cmd=is_write; cmd_en=1; addr=a; wr_data=d; data_mask=m;
            @(negedge clk);
            cmd_en=0;
        end
    endtask
    task automatic do_read(input [ADDR_W-1:0] a,input [31:0] expect_word);
        begin
            issue(0,a,0,0);
            wait(rd_data_valid);
            if(rd_data!==expect_word) begin
                errors=errors+1;
                $display("FAIL: read %0h got %h expected %h",a,rd_data,expect_word);
            end
            @(negedge clk);
        end
    endtask

    integer n;
    reg [31:0] model [0:63];
    reg [31:0] w;
    initial begin
        for(n=0;n<4096;n=n+1) mem[n]=n[7:0]^8'hA5;
        for(n=0;n<64;n=n+1) model[n]={mem[4*n+3],mem[4*n+2],mem[4*n+1],mem[4*n]};
        repeat(4) @(negedge clk);
        rst_n=1;
        wait(init_calib);
        if(cfg_writes!==1 || cr0!==16'h8F1F) begin errors=errors+1; $display("FAIL: CR0 write %h x%0d",cr0,cfg_writes); end
        if(!reset_seen_low) begin errors=errors+1; $display("FAIL: no reset pulse"); end

        // Register space: write CR0 with zero latency, then read it back.
        cmd_reg=1;
        issue(1,12'h800,32'h0000_8E2C,4'b0000);
        @(negedge clk);
        wait(cmd_rdy);
        if(cfg_writes!==2 || cr0!==16'h8E2C) begin errors=errors+1; $display("FAIL: CR0 user write %h x%0d",cr0,cfg_writes); end
        if(!init_calib) begin errors=errors+1; $display("FAIL: init_calib dropped"); end
        do_read(12'h800,32'h0000_2C8E);
        cmd_reg=0;

        do_read(0,model[0]);
        do_read(5,model[5]);
        issue(1,7,32'h11223344,4'b0000);
        model[7]=32'h11223344;
        do_read(7,model[7]);
        issue(1,7,32'hAABBCCDD,4'b0101);       // mask bytes 0 and 2
        model[7]={8'hAA,model[7][23:16],8'hCC,model[7][7:0]};
        model[7][31:24]=8'hAA; model[7][15:8]=8'hCC;
        do_read(7,model[7]);
        do_read(8,model[8]);                   // neighbours untouched
        for(n=0;n<40;n=n+1) begin
            w=$urandom;
            issue(1,n[ADDR_W-1:0]+16,w,4'b0000);
            model[n+16]=w;
        end
        for(n=39;n>=0;n=n-1) do_read(n[ADDR_W-1:0]+16,model[n+16]);

        // Idle again after the last read.
        @(negedge clk);
        wait(cmd_rdy);
        @(negedge clk);
        if(!cmd_rdy) begin errors=errors+1; $display("FAIL: not idle at end"); end
        if(errors==0) $display("PASS: tb_hyperram_ctrl");
        else $display("FAIL: tb_hyperram_ctrl %0d errors",errors);
        $finish;
    end

    initial begin
        #5000000;
        $display("FAIL: tb_hyperram_ctrl timeout");
        $finish;
    end
endmodule
