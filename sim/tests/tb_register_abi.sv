`timescale 1ns/1ps
// Compares the register RTL with the generated ABI package (spec/registers.json):
// direct-window reset values and access legality, EXT reset values for the
// 4:3 and 16:9 builds, and audio indexed reset values and legality. Behaviour
// is still covered by the hand-written tests; this only keeps the generated
// host constants honest against the hardware.
module tb_register_abi;
    import kagura_abi_pkg::*;
    reg clk=0; always #9.259 clk=~clk;
    reg reset=1,valid=0,write_req=0;
    reg [4:0] addr=0;
    reg [7:0] wdata=0;
    reg sel=0;
    wire [1:0] ready,rsp_valid,rsp_error;
    wire [7:0] rdata [0:1];
    reg [7:0] value;
    reg err;
    integer checks=0;
    genvar g;
    generate for(g=0;g<2;g=g+1) begin: dut
        kagura_registers #(.CAPS(g ? CAPS_VALUE_WIDE : CAPS_VALUE_FULL),.LINES(g ? 180 : 240)) regs(
            .clk(clk),.reset(reset),.init_done(1'b0),.vblank_live(1'b0),
            .irq_events(8'b0),.sprite_overflow_index(8'b0),.sprite_overflow_line(8'b0),.error_events(8'b0),
            .req_valid(valid && sel==g),.req_ready(ready[g]),.req_write(write_req),.req_addr(addr),.req_wdata(wdata),
            .rsp_valid(rsp_valid[g]),.rsp_ready(1'b1),.rsp_rdata(rdata[g]),.rsp_error(rsp_error[g]),.irq(),
            .push(),.push_desc(),.push_ready(1'b1),.queue_free(6'd32),.queue_idle(1'b1),.queue_staging(1'b0),
            .engine_busy(1'b0),.read_done(1'b0),.read_data(8'b0),.fence_done(1'b0),.fence_tag(8'b0),.commit_done(1'b0),
            .audio_index(8'b0),.audio_rdata(8'b0),.audio_read_legal(1'b1),.audio_write_legal(1'b0),
            .audio_settings_valid(1'b1),.audio_busy(1'b0),.audio_settle(1'b0),.audio_index_write(),.audio_data_write(),.audio_capture(),.audio_wdata(),
            .display_ctrl(),.scroll_x(),.scroll_y(),.backdrop(),.raster_line());
    end endgenerate

    reg a_index_write=0,a_data_write=0;
    reg [7:0] a_wdata=0;
    wire [7:0] a_index,a_rdata,a_status;
    wire a_read_legal,a_write_legal;
    kagura_audio_registers audio(.clk(clk),.reset(reset),.index_write(a_index_write),.data_write(a_data_write),
        .wdata(a_wdata),.index(a_index),.rdata(a_rdata),.read_legal(a_read_legal),.write_legal(a_write_legal),
        .settings_valid(),.capture(1'b0),.commit_done(1'b0),.apply_busy(),
        .underflow_event(1'b0),.overflow_event(1'b0),.muted(1'b0),.status(a_status),
        .snapshot_step(),.snapshot_duty(),.snapshot_l(),.snapshot_r(),.snapshot_enable(),.snapshot_reset(),
        .snapshot_len(),.snapshot_master(),.snapshot_period());

    task automatic access(input reg s,input reg wr,input reg[4:0] a,input reg[7:0] d);
        begin
            @(negedge clk); sel=s; valid=1; write_req=wr; addr=a; wdata=d;
            @(posedge clk); while(!ready[s]) @(posedge clk);
            @(negedge clk); valid=0;
            while(!rsp_valid[s]) @(posedge clk);
            #1; value=rdata[s]; err=rsp_error[s];
        end
    endtask
    task automatic clear_errors(input reg s);
        begin
            access(s,1,REG_ERROR_CODE,8'hff); access(s,1,REG_IRQ_STATUS,8'hff);
        end
    endtask
    function automatic [7:0] direct_reset(input integer off);
        direct_reset=DIRECT_RESET_VALUES[8*off +: 8];
    endfunction

    task automatic check_direct(input reg s,input [7:0] caps_value);
        integer off;
        begin
            // Reset values first: later illegal accesses set ERROR_CODE/STATUS.
            for(off=0;off<32;off=off+1) if(DIRECT_READABLE[off]) begin
                access(s,0,off[4:0],0);
                if(off==REG_VRAM_READ_RESULT) begin
                    if(!err || value!=0) $fatal(1,"inst %0d READ_RESULT before READY: value %h err %b",s,value,err);
                    clear_errors(s);
                end else if(err) $fatal(1,"inst %0d offset %h: read refused",s,off);
                else if(off==REG_CAPS) begin if(value!=caps_value) $fatal(1,"inst %0d CAPS %h expected %h",s,value,caps_value); end
                else if(off==REG_FIFO_STATUS) begin
                    if((value & FIFO_STATUS_FREE_MASK)!=32 || (value & FIFO_STATUS_FULL)!=0) $fatal(1,"FIFO_STATUS %h",value);
                end else if(DIRECT_HAS_RESET[off] && value!=direct_reset(off))
                    $fatal(1,"inst %0d offset %h: reset %h, spec %h",s,off,value,direct_reset(off));
                checks=checks+1;
            end
            // Access legality: RO refuses writes, WO refuses reads (indexed ports excluded).
            for(off=0;off<32;off=off+1) if(off!=REG_EXT_REG_DATA && off!=REG_AUDIO_REG_DATA) begin
                if(!DIRECT_WRITABLE[off]) begin
                    access(s,1,off[4:0],8'h5a);
                    if(!err) $fatal(1,"inst %0d offset %h: write to RO accepted",s,off);
                    access(s,0,REG_ERROR_CODE,0);
                    if(value!=ERROR_CODE_BAD_ACCESS) $fatal(1,"inst %0d offset %h: RO write error %h",s,off,value);
                    clear_errors(s); checks=checks+1;
                end
                if(!DIRECT_READABLE[off]) begin
                    access(s,0,off[4:0],0);
                    if(!err) $fatal(1,"inst %0d offset %h: read of WO accepted",s,off);
                    clear_errors(s); checks=checks+1;
                end
            end
        end
    endtask

    task automatic check_ext(input reg s,input [7:0] height);
        integer i;
        reg [7:0] expected [0:17];
        begin
            expected[0]=EXT_SCROLL_X_L_RESET; expected[1]=EXT_SCROLL_X_H_RESET; expected[2]=EXT_SCROLL_Y_RESET;
            expected[3]=EXT_BACKDROP_RESET; expected[4]=EXT_RASTER_LINE_RESET; expected[5]=EXT_MAX_SPRITES_RESET;
            expected[6]=EXT_MAX_LINE_SPRITES_RESET; expected[7]=EXT_PATTERN_COUNT_L_RESET; expected[8]=EXT_PATTERN_COUNT_H_RESET;
            expected[9]=EXT_WAVE_LENGTH_MAX_RESET; expected[10]=height;
            expected[11]=EXT_RS_COUNT_RESET; expected[12]=EXT_RS_INDEX_RESET; expected[13]=EXT_RS_LINE_RESET;
            expected[14]=EXT_RS_X_L_RESET; expected[15]=EXT_RS_X_H_RESET; expected[16]=EXT_RS_Y_RESET; expected[17]=EXT_RS_MAX_RESET;
            for(i=0;i<=17;i=i+1) begin
                access(s,1,REG_EXT_REG_INDEX,i[7:0]);
                access(s,0,REG_EXT_REG_DATA,0);
                if(err || value!=expected[i]) $fatal(1,"inst %0d EXT %h: %h err %b, spec %h",s,i,value,err,expected[i]);
                if((i>=EXT_MAX_SPRITES && i<=10) || i==17) begin
                    access(s,1,REG_EXT_REG_DATA,8'h01);
                    if(!err) $fatal(1,"inst %0d EXT %h: write to RO accepted",s,i);
                    clear_errors(s);
                end
                checks=checks+1;
            end
            access(s,1,REG_EXT_REG_INDEX,8'h12);
            access(s,0,REG_EXT_REG_DATA,0);
            if(err || value!=0) $fatal(1,"EXT 12 read");
            access(s,1,REG_EXT_REG_DATA,8'h01);
            if(!err) $fatal(1,"EXT 12 write accepted");
            clear_errors(s); checks=checks+1;
        end
    endtask

    task automatic audio_index(input [7:0] i);
        begin
            @(negedge clk); a_wdata=i; a_index_write=1;
            @(negedge clk); a_index_write=0;
            @(negedge clk); @(negedge clk);
        end
    endtask
    task automatic check_audio;
        integer c,o;
        reg [7:0] expected;
        reg [2:0] kind; // 0 pulse, 1 noise, 2 wave
        begin
            for(c=0;c<AUDIO_CHANNELS;c=c+1) for(o=0;o<AUDIO_CH_STRIDE;o=o+1) begin
                kind= c<3 ? 0 : c==3 ? 1 : 2;
                case(o)
                    AUDIO_STEP_L: expected= kind!=1 ? AUDIO_STEP_L_RESET : 0;
                    AUDIO_STEP_M: expected= kind!=1 ? AUDIO_STEP_M_RESET : 0;
                    AUDIO_STEP_H: expected= kind!=1 ? AUDIO_STEP_H_RESET : 0;
                    AUDIO_DUTY: expected= kind==0 ? AUDIO_DUTY_RESET : 0;
                    AUDIO_GAIN_L: expected=AUDIO_GAIN_L_RESET;
                    AUDIO_GAIN_R: expected=AUDIO_GAIN_R_RESET;
                    AUDIO_CONTROL: expected=AUDIO_CONTROL_RESET;
                    AUDIO_LEN_LOG2: expected= kind==2 ? AUDIO_LEN_LOG2_RESET : 0;
                    AUDIO_NOISE_PERIOD_L: expected= kind==1 ? AUDIO_NOISE_PERIOD_L_RESET : 0;
                    AUDIO_NOISE_PERIOD_H: expected= kind==1 ? AUDIO_NOISE_PERIOD_H_RESET : 0;
                    default: expected=0;
                endcase
                audio_index(8'(c*AUDIO_CH_STRIDE+o));
                if(a_rdata!=expected || !a_read_legal || !a_write_legal)
                    $fatal(1,"audio ch%0d offset %h: %h legal %b%b, spec %h",c,o,a_rdata,a_read_legal,a_write_legal,expected);
                checks=checks+1;
            end
            audio_index(AUDIO_MASTER_GAIN);
            if(a_rdata!=AUDIO_MASTER_GAIN_RESET || !a_write_legal) $fatal(1,"MASTER_GAIN %h",a_rdata);
            audio_index(AUDIO_STATUS);
            if(a_rdata!=AUDIO_STATUS_RESET || a_write_legal || !a_read_legal) $fatal(1,"AUDIO_STATUS %h",a_rdata);
            audio_index(AUDIO_ERROR_CLEAR);
            if(a_read_legal || !a_write_legal) $fatal(1,"AUDIO_ERROR_CLEAR legality");
            audio_index(8'(AUDIO_CHANNELS*AUDIO_CH_STRIDE));
            if(a_rdata!=0 || a_write_legal) $fatal(1,"audio index after channels");
            audio_index(AUDIO_ERROR_CLEAR+8'd1);
            if(a_rdata!=0 || a_write_legal) $fatal(1,"audio index after globals");
            checks=checks+5;
        end
    endtask

    initial begin
        #100; @(negedge clk); reset=0;
        repeat(4) @(negedge clk);
        check_direct(0,CAPS_VALUE_FULL); check_ext(0,EXT_SCREEN_HEIGHT_FULL);
        check_direct(1,CAPS_VALUE_WIDE); check_ext(1,EXT_SCREEN_HEIGHT_WIDE);
        check_audio();
        $display("PASS: register ABI package vs RTL, %0d checks; direct reset/access, EXT 4:3 and 16:9, audio indexed resets/legality",checks);
        $finish;
    end
endmodule
