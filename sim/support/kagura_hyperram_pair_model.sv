// SPDX-License-Identifier: Apache-2.0
// Simulation-only memory at the controller's byte-pair PHY boundary.
// Decodes CA independently; does not model DDR pins, phase margin or RWDS capture.
module kagura_hyperram_pair_model #(
    parameter integer LAT=14, RDL=6, BYTES=256
) (
    input wire clk, reset_n, cs_n, ck_en, dq_oe, rwds_oe,
    input wire [7:0] dq_r, dq_f,
    input wire mask_r, mask_f,
    output wire [7:0] read_r, read_f
);
    reg [7:0] memory [0:BYTES-1];
    reg [7:0] pipe_r [0:RDL-1], pipe_f [0:RDL-1];
    reg [47:0] ca=0;
    reg [15:0] cr0=0;
    integer cycle=0, base=0;
    reg reading=0, registers=0;
    assign read_r=pipe_r[RDL-1];
    assign read_f=pipe_f[RDL-1];
    initial for(integer n=0;n<BYTES;n++) memory[n]=8'hA5;
    always @(posedge clk) begin
        for(integer n=RDL-1;n>0;n--) begin
            pipe_r[n]<=pipe_r[n-1]; pipe_f[n]<=pipe_f[n-1];
        end
        pipe_r[0]<=0; pipe_f[0]<=0;
        if(cs_n || !reset_n) cycle=0;
        else if(ck_en) begin
            if(cycle<3) begin
                if(!dq_oe || rwds_oe) $fatal(1,"invalid CA drive");
                ca={ca[31:0],dq_r,dq_f};
                if(cycle==2) begin
                    if(!ca[45] || ca[15:3]!=0) $fatal(1,"invalid CA encoding");
                    reading=ca[47]; registers=ca[46];
                    base=int'({ca[44:16],ca[2:0]})*2;
                    if(registers && (reading || base!=4096)) $fatal(1,"unexpected register command");
                    if(!registers && (base<0 || base+3>=BYTES)) $fatal(1,"memory address out of range");
                end
            end else if(registers) begin
                if(cycle!=3 || !dq_oe || rwds_oe) $fatal(1,"invalid CR0 write");
                cr0={dq_r,dq_f};
                if(cr0!=16'h8F1F) $fatal(1,"unexpected CR0 value");
            end else if(cycle>=LAT && cycle<LAT+2) begin
                if(reading) begin
                    if(dq_oe || rwds_oe) $fatal(1,"read contention");
                    pipe_r[0]<=memory[base+2*(cycle-LAT)];
                    pipe_f[0]<=memory[base+2*(cycle-LAT)+1];
                end else begin
                    if(!dq_oe || !rwds_oe) $fatal(1,"missing write drive");
                    if(!mask_r) memory[base+2*(cycle-LAT)]<=dq_r;
                    if(!mask_f) memory[base+2*(cycle-LAT)+1]<=dq_f;
                end
            end else if(dq_oe || rwds_oe) $fatal(1,"drive during latency");
            cycle=cycle+1;
        end
        if(cs_n && (ck_en || dq_oe || rwds_oe)) $fatal(1,"activity with CS high");
    end
endmodule
