`timescale 1ns/1ps
// ABI 0.4 through the public register interface: kagura_core with CAPS b3,
// the real HyperRAM controller and an independently CA-decoding memory model.
// PSRAM upload/readback/FILL/range checks through the ordered queue, byte
// masking, PCM PREPARE/READY/AUDIO_COMMIT start, one-shot DONE, loop across
// the top of the region, pause/resume, STOP, CONFIG_ERROR/CLEAR, and host
// traffic during playback without UNDERRUN.
module tb_psram_core;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,valid=0,wr_req=0;
    reg [4:0] addr=0; reg [7:0] data=0;
    wire ready,rsp_valid,rsp_error,init_done,sv;
    wire [7:0] rdata,status;
    wire signed [15:0] left_sample,right_sample;
    wire p_reset_n,p_cs_n,p_ck_en,p_dq_oe,p_rwds_oe,p_mask_r,p_mask_f;
    wire [7:0] p_dq_r,p_dq_f,p_read_r,p_read_f;
    kagura_core #(.CAPS(8'h5B),.PSRAM_INIT_CYCLES(64)) dut(.clk(clk),.reset(reset),.req_valid(valid),.req_ready(ready),.req_write(wr_req),
        .req_addr(addr),.req_wdata(data),.rsp_valid(rsp_valid),.rsp_ready(1'b1),.rsp_rdata(rdata),.rsp_error(rsp_error),
        .irq(),.init_done(init_done),.audio_full(1'b0),.audio_underflow_toggle(1'b0),.audio_muted(1'b0),
        .audio_sample_valid(sv),.audio_left(left_sample),.audio_right(right_sample),.audio_status(status),
        .render_start(1'b0),.render_line(8'b0),.line_write(),.line_addr(),.line_data(),.line_read(),.line_rdata(16'b0),
        .render_done(),.vblank_start(1'b0),.vblank_live(1'b0),.underrun_event(1'b0),.line_start(1'b0),.shown_line(8'b0),
        .render_cycles(),.queue_free(),
        .psram_reset_n(p_reset_n),.psram_cs_n(p_cs_n),.psram_ck_en(p_ck_en),.psram_dq_oe(p_dq_oe),.psram_rwds_oe(p_rwds_oe),
        .psram_dq_o_rise(p_dq_r),.psram_dq_o_fall(p_dq_f),.psram_rwds_o_rise(p_mask_r),.psram_rwds_o_fall(p_mask_f),
        .psram_dq_i_rise(p_read_r),.psram_dq_i_fall(p_read_f));
    kagura_hyperram_pair_model #(.BYTES(4194304)) memory(.clk,.reset_n(p_reset_n),.cs_n(p_cs_n),.ck_en(p_ck_en),
        .dq_oe(p_dq_oe),.rwds_oe(p_rwds_oe),.dq_r(p_dq_r),.dq_f(p_dq_f),.mask_r(p_mask_r),.mask_f(p_mask_f),
        .read_r(p_read_r),.read_f(p_read_f));

    localparam [4:0] R_ADDR_L=4,R_ADDR_M=5,R_ADDR_H=6,R_WRITE=7,R_READ=8,R_RESULT=9,R_EXT_I=10,R_EXT_D=11,
        R_AUD_I=12,R_AUD_D=13,R_CMD=14,R_INC_L=16,R_LEN_L=18,R_LEN_H=19,R_FILL=20,R_FTAG=21,R_DTAG=22,R_ERR=23;
    reg [7:0] value;
    task automatic access(input bit w,input [4:0] a,input [7:0] d,input bit err=0);
        @(negedge clk); valid=1; wr_req=w; addr=a; data=d;
        @(posedge clk); while(!ready) @(posedge clk);
        #1; valid=0; @(posedge clk); #1;
        if(!rsp_valid || rsp_error!==err) $fatal(1,"access w=%0d a=%02h d=%02h error=%b expected=%b",w,a,d,rsp_error,err);
        value=rdata;
    endtask
    task automatic aw(input [7:0] i,input [7:0] d); access(1,R_AUD_I,i); access(1,R_AUD_D,d); endtask
    task automatic ar(input [7:0] i); access(1,R_AUD_I,i); access(0,R_AUD_D,0); endtask
    // Queue write that respects FIFO_STATUS (PSRAM bytes drain slower than the bus).
    task automatic qwrite(input [7:0] d);
        do access(0,15,0); while(value[5:0]==0);
        access(1,R_WRITE,d);
    endtask
    task automatic qcmd(input [7:0] op,input bit err=0);
        do access(0,15,0); while(value[5:0]==0);
        access(1,R_CMD,op,err);
    endtask
    task automatic set_addr(input [23:0] a); access(1,R_ADDR_L,a[7:0]); access(1,R_ADDR_M,a[15:8]); access(1,R_ADDR_H,a[23:16]); endtask
    task automatic fence(input [7:0] tag);
        access(1,R_FTAG,tag); qcmd(2);
        do access(0,R_DTAG,0); while(value!=tag);
    endtask
    task automatic expect_error(input [7:0] bits);
        access(0,R_ERR,0);
        if(value!==bits) $fatal(1,"ERROR_CODE %02h expected %02h",value,bits);
        access(1,R_ERR,8'hff);
    endtask
    task automatic read_byte(input [23:0] a,output [7:0] v);
        set_addr(a); access(1,R_READ,0);
        do access(0,0,0); while(!value[2]);
        access(0,R_RESULT,0); v=value;
    endtask
    function automatic [7:0] s0(input integer i); s0=8'(i*7-90); endfunction        // one-shot, ch0
    function automatic [7:0] s1(input integer i); s1=8'(i*5+3); endfunction         // loop, ch1
    task automatic pcm_regs(input integer p,input [23:0] st,input [23:0] en,input [23:0] lp,input bit loop_en);
        aw(8'(96+32*p+0),st[7:0]); aw(8'(96+32*p+1),st[15:8]); aw(8'(96+32*p+2),st[23:16]);
        aw(8'(96+32*p+4),en[7:0]); aw(8'(96+32*p+5),en[15:8]); aw(8'(96+32*p+6),en[23:16]);
        aw(8'(96+32*p+8),lp[7:0]); aw(8'(96+32*p+9),lp[15:8]); aw(8'(96+32*p+10),lp[23:16]);
        aw(8'(96+32*p+14),{6'b0,loop_en,1'b0});
    endtask
    task automatic pcm_status(input integer p); ar(8'(96+32*p+15)); endtask
    task automatic wait_ready(input integer p);
        integer n=0;
        do begin pcm_status(p); n++; if(n>2000) $fatal(1,"PCM %0d never READY (%02h)",p,value); end while(!value[0]);
    endtask
    task automatic audio_commit;
        access(1,R_CMD,4);
        do ar(8'he1); while(value[0]);
    endtask

    // Sample capture: the PCM gains route ch0 only to L and ch1 only to R,
    // each at gain 128 with MASTER_GAIN 32, so an output equals sample*16.
    integer cap_n=0;
    reg capturing=0;
    reg signed [15:0] cap_l [0:4095], cap_r [0:4095];
    always @(posedge clk) if(capturing && sv && cap_n<4096) begin cap_l[cap_n]<=left_sample; cap_r[cap_n]<=right_sample; cap_n<=cap_n+1; end

    integer i,first,underruns=0;
    reg [7:0] v;
    always @(posedge clk) if(!reset && |dut.psram.pf_underrun) underruns++;
    initial begin
        #100; @(negedge clk); reset=0; wait(init_done);
        access(0,27,0); if(value!=4) $fatal(1,"ABI_MINOR %0d",value);
        access(0,28,0); if(value!=8'h5B) $fatal(1,"CAPS %02h",value);
        access(1,R_EXT_I,8'h12); access(0,R_EXT_D,0); if(value!=22) $fatal(1,"PSRAM_SIZE_LOG2 %0d",value);
        access(1,R_EXT_I,8'h13); access(0,R_EXT_D,0); if(value!=2) $fatal(1,"PCM_CHANNELS %0d",value);
        access(1,R_EXT_I,8'h14); access(1,R_EXT_D,1,1); expect_error(8'h04);
        // PCM register resets, reserved offsets, unimplemented A0.
        for(i=0;i<64;i++) begin ar(8'(96+i)); if(value!=0) $fatal(1,"PCM index %02h reset %02h",96+i,value); end
        aw(8'h63,8'h55); ar(8'h63); if(value!=0) $fatal(1,"reserved PCM offset kept a value");
        aw(8'h6c,8'h81); ar(8'h6c); if(value!=8'h81) $fatal(1,"GAIN_L shadow"); aw(8'h6c,0);
        access(1,R_AUD_I,8'ha0); access(1,R_AUD_D,1,1); expect_error(8'h04);

        // Upload through the queue, then read back. Byte writes must not
        // disturb neighbouring bytes of the same 32-bit word.
        set_addr(24'h400101);
        for(i=0;i<70;i++) qwrite(8'(i*13+1));
        fence(1);
        repeat(40) @(negedge clk);  // the last accepted write is still in the controller
        if(memory.memory[24'h000100]!==8'hA5 || memory.memory[24'h000101+70]!==8'hA5) $fatal(1,"byte mask leaked");
        for(i=0;i<70;i++) if(memory.memory[24'h000101+i]!==8'(i*13+1)) $fatal(1,"PSRAM byte %0d not written",i);
        for(i=0;i<70;i+=23) begin read_byte(24'h400101+i,v); if(v!==8'(i*13+1)) $fatal(1,"readback %0d = %02h",i,v); end
        // FILL inside the region; crossing its end or touching 800000 is refused.
        set_addr(24'h7ffff0); access(1,R_LEN_L,16); access(1,R_LEN_H,0); access(1,R_FILL,8'h3c); qcmd(1); fence(2);
        repeat(40) @(negedge clk);
        for(i=0;i<16;i++) if(memory.memory[24'h3ffff0+i]!==8'h3c) $fatal(1,"FILL byte %0d",i);
        access(1,R_LEN_L,17); access(1,R_CMD,1,1); expect_error(8'h02);
        set_addr(24'h800000); access(1,R_WRITE,1,1); expect_error(8'h02);
        set_addr(24'h3fffff); access(1,R_WRITE,1,1); expect_error(8'h02);

        // PCM data: ch0 one-shot 40 bytes, ch1 loop of 64 bytes ending at the
        // top of the region (loop back to +16).
        set_addr(24'h400200); for(i=0;i<40;i++) qwrite(s0(i));
        set_addr(24'h7fffc0); for(i=0;i<64;i++) qwrite(s1(i));
        fence(3);
        pcm_regs(0,24'h400200,24'h400228,24'h400200,0);
        pcm_regs(1,24'h7fffc0,24'h800000,24'h7fffd0,1);
        aw(8'h6f,1); aw(8'h8f,1);
        wait_ready(0); wait_ready(1);
        aw(8'h6c,128); aw(8'h6d,0); aw(8'h8c,0); aw(8'h8d,128);
        aw(8'h6e,1); aw(8'h8e,3);
        @(negedge clk); capturing=1;
        audio_commit();
        // Host traffic on another range while both channels play.
        set_addr(24'h480000); for(i=0;i<200;i++) qwrite(8'(i));
        fence(4);
        wait(cap_n>=400);
        capturing=0;
        first=-1;
        for(i=0;i<16 && first<0;i++) if(cap_l[i]!=0 || cap_r[i]!=0) first=i;
        if(first<0) $fatal(1,"no PCM output after AUDIO_COMMIT");
        for(i=0;i<300;i++) begin
            if(cap_l[first+i]!==(i<40 ? 16'($signed(s0(i)))*16 : 16'sd0))
                $fatal(1,"ch0 sample %0d = %0d expected %0d",i,cap_l[first+i],i<40 ? $signed(s0(i))*16 : 0);
            if(cap_r[first+i]!==16'($signed(s1(i<64 ? i : 16+(i-64)%48)))*16)
                $fatal(1,"ch1 sample %0d = %0d",i,cap_r[first+i]);
        end
        pcm_status(0); if(value!==8'h04) $fatal(1,"ch0 status %02h expected DONE only",value);
        pcm_status(1); if(value!==8'h03 || underruns!=0) $fatal(1,"ch1 status %02h underruns %0d",value,underruns);

        // Pause ch1 with a committed ENABLE=0, resume with ENABLE=1: the
        // nonzero samples must continue the loop order across the gap.
        cap_n=0; @(negedge clk); capturing=1;
        wait(cap_n>=20); aw(8'h8e,2); audio_commit();
        do pcm_status(1); while(value[6]);  // the kept buffer tops up first
        if(value!==8'h01) $fatal(1,"paused ch1 status %02h",value);
        begin integer start_n=cap_n; wait(cap_n>=start_n+30); end
        aw(8'h8e,3); audio_commit();
        wait(cap_n>=cap_n+0 && cap_n>=200); capturing=0;
        begin
            integer prev=-1,zeros=0,idx,j;
            for(i=0;i<200;i++) begin
                if(cap_r[i]==0) begin zeros++; continue; end
                idx=-1; for(j=0;j<64;j++) if(16'($signed(s1(j)))*16==cap_r[i]) idx=j;
                if(idx<0) $fatal(1,"resume: unknown ch1 value %0d",cap_r[i]);
                if(prev>=0 && idx!=(prev==63 ? 16 : prev+1)) $fatal(1,"resume: %0d after %0d",idx,prev);
                prev=idx;
            end
            if(zeros<20) $fatal(1,"pause produced only %0d silent samples",zeros);
        end
        // STOP halts at once and needs PREPARE again.
        aw(8'h8f,2);
        pcm_status(1); if(value!==8'h00) $fatal(1,"stopped ch1 status %02h",value);
        // AUDIO_COMMIT is not refused for an enabled channel that is not READY.
        audio_commit(); expect_error(8'h00);
        pcm_status(1); if(value[1]) $fatal(1,"stopped channel restarted");
        // Range errors are reported as CONFIG_ERROR and cleared by CLEAR.
        pcm_regs(1,24'h3ffff0,24'h400010,24'h3ffff0,0); aw(8'h8f,1);
        do pcm_status(1); while(value[6]);
        if(value!==8'h10) $fatal(1,"low START status %02h",value);
        aw(8'h8f,4); pcm_status(1); if(value!==8'h00) $fatal(1,"CLEAR left %02h",value);
        pcm_regs(1,24'h7fffc0,24'h800000,24'h800000,1); aw(8'h8f,1);
        do pcm_status(1); while(value[6]);
        if(value!==8'h10) $fatal(1,"LOOP=END status %02h",value);
        aw(8'h8f,4);
        // A finished one-shot replays from START after PREPARE + AUDIO_COMMIT.
        aw(8'h6f,4); aw(8'h6f,1); wait_ready(0);
        pcm_status(0); if(value!==8'h01) $fatal(1,"re-prepared ch0 status %02h",value);
        // A STATUS read right after PREPARE never shows the previous READY.
        aw(8'h6f,1); pcm_status(0); if(value[0] || !value[6]) $fatal(1,"status right after PREPARE %02h",value);
        wait_ready(0);
        cap_n=0; @(negedge clk); capturing=1;
        audio_commit();
        wait(cap_n>=60); capturing=0;
        first=-1;
        for(i=0;i<16 && first<0;i++) if(cap_l[i]!=0) first=i;
        for(i=0;i<40;i++) if(first<0 || cap_l[first+i]!==16'($signed(s0(i)))*16) $fatal(1,"replay sample %0d",i);
        if(underruns!=0) $fatal(1,"%0d PCM underruns",underruns);
        $display("PASS: tb_psram_core (PSRAM upload/readback/FILL/range, byte masks, PCM one-shot, loop at region top, host traffic, pause/resume, STOP, CONFIG_ERROR/CLEAR, replay)");
        $finish;
    end
    initial begin #200000000; $fatal(1,"tb_psram_core timeout"); end
endmodule
