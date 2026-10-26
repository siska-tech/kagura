// SPDX-License-Identifier: Apache-2.0
// 32-byte register window, ABI 0.5 (docs/register-map.md). Every request is
// answered two system cycles after acceptance (the ABI allows two).
// The address check is registered one cycle and the FILL range check two
// cycles after VRAM_ADDR/LENGTH change (they do not fit in one 54MHz
// cycle), and an accepted command reaches the queue one cycle later
// and takes four more to be stored. req_ready is held low during those
// cycles, which the CPU pace (one access per 16 cycles) never observes. Command-type writes
// are checked completely before anything changes: a refused operation sets
// its ERROR_CODE bits (and IRQ.ERROR) and leaves address, length, READY and
// the queue untouched; only a successful VRAM_WRITE/READ_REQUEST adds INC.
// COMMIT captures DISPLAY_CTRL and the extended shadows into its descriptor
// at acceptance: address = {4'b0, display_ctrl, scroll_x, scroll_y},
// length = {backdrop, raster_line}; only one may be outstanding.
// Indexed audio shadow/snapshot state lives in kagura_audio_registers.
module kagura_registers #(
    parameter [7:0] CAPS=8'h00, // set only bits this bitstream implements
    parameter integer LINES=240,   // EXT 0A SCREEN_HEIGHT
    parameter integer SPRITES=256, // EXT 05 MAX_SPRITES (256 reads as 0); OAM is SPRITES*8 bytes
    parameter bit DEBUG=0          // PSRAM pin capture at EXT 17/18 (debug builds only, not ABI)
) (
    input wire clk, reset,
    input wire init_done,
    input wire vblank_live,
    input wire [7:0] irq_events,      // pulses: b0 VBLANK, b1 RASTER, b5 SPR_OVERFLOW
    input wire [7:0] sprite_overflow_index,
    input wire [7:0] sprite_overflow_line,
    input wire [7:0] error_events,    // pulses: b5 LINE_UNDERRUN, b6 AUDIO_FIFO_ERROR
    input wire req_valid,
    output wire req_ready,
    input wire req_write,
    input wire [4:0] req_addr,
    input wire [7:0] req_wdata,
    output reg rsp_valid,
    input wire rsp_ready,
    output reg [7:0] rsp_rdata,
    output reg rsp_error,
    output wire irq,
    // command queue / engine
    output wire push,
    output wire [63:0] push_desc,
    input wire push_ready,
    input wire [5:0] queue_free,
    input wire queue_idle,
    input wire queue_staging,
    input wire engine_busy,
    input wire read_done,
    input wire [7:0] read_data,
    input wire fence_done,
    input wire [7:0] fence_tag,
    input wire commit_done,
    input wire [7:0] audio_index,audio_rdata,
    input wire audio_read_legal,audio_write_legal,audio_settings_valid,audio_busy,audio_settle,
    output wire audio_index_write,audio_data_write,audio_capture,
    output wire [7:0] audio_wdata,
    // Shadow state for the renderer; COMMIT snapshots it for VBlank apply.
    output reg [2:0] display_ctrl,
    output reg [8:0] scroll_x,
    output reg [7:0] scroll_y, backdrop, raster_line,
    // Raster scroll shadow table (CAPS b6): entries {y, x[8:0], line}.
    output reg [3:0] rs_count,
    output reg [199:0] rs_table,
    // DEBUG: EXT 17 selects a capture byte, EXT 18 reads it; writing 18 re-arms
    // (b0: trigger on a read instead of a write).
    output reg [7:0] dbg_index,
    output wire dbg_arm,
    output wire [7:0] dbg_arm_value,
    input wire [7:0] dbg_rdata
);
    localparam RS=CAPS[6];
    localparam PSRAM=CAPS[3];  // PSRAM region 400000-7FFFFF and PCM (ABI 0.4)
    localparam [4:0] STATUS=5'h00, IRQ_STATUS=5'h01, IRQ_ENABLE=5'h02, DISPLAY_CTRL=5'h03,
        ADDR_L=5'h04, ADDR_M=5'h05, ADDR_H=5'h06, VRAM_WRITE=5'h07, READ_REQUEST=5'h08,
        READ_RESULT=5'h09, EXT_INDEX=5'h0a, EXT_DATA=5'h0b, AUDIO_INDEX=5'h0c,AUDIO_DATA=5'h0d,COMMAND=5'h0e, FIFO_STATUS=5'h0f,
        INC_L=5'h10, INC_H=5'h11, LENGTH_L=5'h12, LENGTH_H=5'h13, FILL_VALUE=5'h14,
        FENCE_TAG=5'h15, DONE_TAG=5'h16, ERROR_CODE=5'h17, ID0=5'h18, ID1=5'h19,
        ABI_MAJOR=5'h1a, ABI_MINOR=5'h1b, CAPS_REG=5'h1c, FRAME_COUNT=5'h1d,
        SPR_OVF_INDEX=5'h1e, SPR_OVF_LINE=5'h1f;
    localparam integer E_FIFO_FULL=0, E_INVALID_ADDRESS=1, E_BAD_ACCESS=2, E_READ_COLLISION=3,
        E_NOT_READY=4, E_BUSY_CONFLICT=7;
    localparam [7:0] OP_FILL=8'h01, OP_FENCE=8'h02, OP_COMMIT=8'h03,OP_AUDIO=8'h04, OP_COPY=8'h05, OP_WRITE=8'h10, OP_READ=8'h11;

    reg [7:0] irq_status, irq_enable, error_code;
    reg [7:0] overflow_index;
    reg [7:0] overflow_line;
    reg [23:0] vram_addr;
    reg [15:0] inc, length;
    reg [7:0] fill_value, fence_value, done_tag, frame_count, ext_index;
    reg read_busy, read_ready, commit_busy;
    reg [7:0] read_result;
    reg checks_stale;
    // Input register: a request is captured on acceptance and processed in
    // the following cycle (response two cycles after acceptance), keeping the
    // CPU adapter's high-fanout request lines away from the register decode.
    reg q_valid, q_write;
    reg [4:0] q_addr;
    reg [7:0] q_wdata;
    // COMMAND opcode and READ_REQUEST value decoded at capture, so the
    // admission and error logic does not compare q_wdata (high fanout) again.
    reg q_op_fill, q_op_fence, q_op_commit, q_op_audio, q_op_copy, q_zero, q_ext_data;
    reg [2:0] rs_settle;
    assign req_ready=!q_valid && (!rsp_valid || rsp_ready) && !checks_stale && !queue_staging && !(|rs_settle) && !audio_settle;
    always @(posedge clk)
        if(reset) begin
            q_valid<=0; q_write<=0; q_addr<=0; q_wdata<=0;
            q_op_fill<=0; q_op_fence<=0; q_op_commit<=0; q_op_audio<=0; q_op_copy<=0; q_zero<=1; q_ext_data<=0;
        end
        else begin
            q_valid<=req_valid && req_ready;
            if(req_valid && req_ready) begin
                q_write<=req_write; q_addr<=req_addr; q_wdata<=req_wdata;
                q_op_fill<=req_wdata==OP_FILL; q_op_fence<=req_wdata==OP_FENCE;
                q_op_commit<=req_wdata==OP_COMMIT; q_op_audio<=req_wdata==OP_AUDIO; q_op_copy<=PSRAM && req_wdata==OP_COPY;
                q_zero<=req_wdata==0; q_ext_data<=req_addr==EXT_DATA;
            end
        end
    assign irq=|(irq_status & irq_enable);
    wire accept=q_valid;
    wire wr=accept && q_write, rd=accept && !q_write;

    // Public VRAM regions (docs/memory-map.md); 0 = not public.
    function automatic [2:0] region(input [24:0] a);
        if(a[24:15]==0) region=1;                          // pattern 000000-007FFF
        else if(a[24:12]==13'h0008) region=2;              // map 008000-008FFF
        else if(a[24:12]==13'h000a && a[11:0]<12'(SPRITES*8)) region=3; // OAM shadow 00A000-00A7FF
        else if(a[24:9]==16'h004a) region=4;               // palette shadow 009400-0095FF
        else if(a[24:9]==16'h004c) region=5;               // wave shadow 009800-0099FF
        else if(PSRAM && a[24:22]==3'b001) region=6;        // PSRAM 400000-7FFFFF
        else region=0;
    endfunction
    wire [24:0] fill_end={1'b0,vram_addr}+{9'b0,length}-25'd1;
    reg addr_ok, fill_ok;
    // FILL range check in two stages (sum, then region compare). After an
    // ADDR/LENGTH write checks_stale holds req_ready low so the next request
    // is accepted no earlier than the edge fill_ok is updated on; the same
    // holds after a VRAM_WRITE/READ address advance (advance_q).
    reg [24:0] fill_end_q;
    reg [2:0] start_region_q;
    reg length_zero_q;
    always @(posedge clk) begin
        addr_ok<=region({1'b0,vram_addr})!=0;
        start_region_q<=region({1'b0,vram_addr});
        fill_end_q<=fill_end;
        length_zero_q<=length==0;
        fill_ok<=start_region_q!=0 && (length_zero_q || region(fill_end_q)==start_region_q);
    end
    // COPY (CAPS b3): the source range lies in PSRAM and the destination range
    // (VRAM_ADDR, LENGTH) in one public region below PSRAM, checked the same way.
    reg [23:0] copy_src;
    wire [24:0] copy_end={1'b0,copy_src}+{9'b0,length}-25'd1;
    reg [24:0] copy_end_q;
    reg copy_start_q,copy_ok;
    always @(posedge clk) begin
        copy_start_q<=copy_src[23:22]==2'b01;               // region 6, PSRAM
        copy_end_q<=copy_end;
        copy_ok<=PSRAM && copy_start_q && (length_zero_q || copy_end_q[24:22]==3'b001) &&
            start_region_q!=0 && start_region_q!=3'd6 && (length_zero_q || region(fill_end_q)==start_region_q);
    end
// synthesis translate_off
    // fill_ok must reflect the current address and length when a FILL is decoded.
    reg [15:0] length_d1, length_d2;
    reg [23:0] addr_d1, addr_d2;
    always @(posedge clk) begin addr_d1<=vram_addr; addr_d2<=addr_d1; length_d1<=length; length_d2<=length_d1; end
    always @(posedge clk)
        if(!reset && q_valid && q_write && q_addr==COMMAND && q_op_fill && (addr_d2!=vram_addr || length_d2!=length))
            $fatal(1,"FILL decoded before its range check settled");
// synthesis translate_on
    // Queue full as of the previous cycle: after a push the next request is
    // stalled anyway, and after a pop this only refuses one cycle early.
    reg full;
    always @(posedge clk) full<=reset ? 1'b0 : !push_ready;

    // Extended registers (shadow; RO constants per register-map).
    reg [7:0] ext_value;
    reg ext_writable, ext_defined;
    reg [2:0] rs_idx;
    wire [24:0] rs_ent=rs_table[25*rs_idx +: 25];
    reg [24:0] rs_ent_q;
    wire [24:0] rs_ent_read=PSRAM ? rs_ent_q : rs_ent;
    // Entry registers 0B..10 are refused during COMMIT_BUSY (the COMMIT
    // copies the table at completion); out-of-range COUNT/INDEX are BAD_ACCESS.
    wire rs_is_table=RS && ext_index>=8'h0b && ext_index<=8'h10 && ext_index!=8'h0c;
    wire rs_bad_value=(ext_index==8'h0b && q_wdata>8'd8) || (ext_index==8'h0c && q_wdata>8'd7);
    wire rs_block=RS && (rs_is_table && commit_busy || rs_bad_value);
    reg rs_ok;
    always @* begin
        ext_value=0; ext_writable=0; ext_defined=1;
        case(ext_index)
            8'h0b: if(RS) begin ext_value={4'b0,rs_count}; ext_writable=1; end else ext_defined=0;
            8'h0c: if(RS) begin ext_value={5'b0,rs_idx}; ext_writable=1; end else ext_defined=0;
            8'h0d: if(RS) begin ext_value=rs_ent_read[7:0]; ext_writable=1; end else ext_defined=0;
            8'h0e: if(RS) begin ext_value=rs_ent_read[15:8]; ext_writable=1; end else ext_defined=0;
            8'h0f: if(RS) begin ext_value={7'b0,rs_ent_read[16]}; ext_writable=1; end else ext_defined=0;
            8'h10: if(RS) begin ext_value=rs_ent_read[24:17]; ext_writable=1; end else ext_defined=0;
            8'h11: if(RS) ext_value=8'd8; else ext_defined=0;
            8'h00: begin ext_value=scroll_x[7:0]; ext_writable=1; end
            8'h01: begin ext_value={7'b0,scroll_x[8]}; ext_writable=1; end
            8'h02: begin ext_value=scroll_y; ext_writable=1; end
            8'h03: begin ext_value=backdrop; ext_writable=1; end
            8'h04: begin ext_value=raster_line; ext_writable=1; end
            8'h05: ext_value=8'(SPRITES);
            8'h06: ext_value=8'd16;
            8'h07: ext_value=8'd0;
            8'h08: ext_value=8'd4;
            8'h09: ext_value=8'd8;
            8'h0a: ext_value=8'(LINES);
            8'h12: if(PSRAM) ext_value=8'd22; else ext_defined=0;
            8'h13: if(PSRAM) ext_value=8'd2; else ext_defined=0;
            8'h14: if(PSRAM) begin ext_value=copy_src[7:0]; ext_writable=1; end else ext_defined=0;
            8'h15: if(PSRAM) begin ext_value=copy_src[15:8]; ext_writable=1; end else ext_defined=0;
            8'h16: if(PSRAM) begin ext_value=copy_src[23:16]; ext_writable=1; end else ext_defined=0;
            8'h17: if(DEBUG) begin ext_value=dbg_index; ext_writable=1; end else ext_defined=0;
            8'h18: if(DEBUG) begin ext_value=dbg_rdata; ext_writable=1; end else ext_defined=0;
            default: ext_defined=0;
        endcase
    end

    // Read-side copies one cycle behind their sources, keeping the EXT decode
    // (RS entry select) and the queue free-count subtraction out of the response
    // path. A request is decoded at least two cycles after the previous one, and
    // the writes that change these (EXT index/data, a push) stall the next one.
    reg [7:0] ext_value_q;
    reg [5:0] free_q;
    always @(posedge clk) begin rs_ent_q<=rs_ent; ext_value_q<=ext_value; free_q<=queue_free; end

    // Decode: read value, whether a write is legal, and command checks.
    reg [7:0] read_value;
    reg read_legal, write_legal;
    always @* begin
        read_value=0; read_legal=1; write_legal=0;
        case(q_addr)
            STATUS: read_value={engine_busy || !queue_idle,|error_code,vblank_live,commit_busy,
                read_busy,read_ready,full,init_done};
            IRQ_STATUS: begin read_value=irq_status; write_legal=1; end
            IRQ_ENABLE: begin read_value=irq_enable; write_legal=1; end
            DISPLAY_CTRL: begin read_value={5'b0,display_ctrl}; write_legal=1; end
            ADDR_L: begin read_value=vram_addr[7:0]; write_legal=1; end
            ADDR_M: begin read_value=vram_addr[15:8]; write_legal=1; end
            ADDR_H: begin read_value=vram_addr[23:16]; write_legal=1; end
            VRAM_WRITE, READ_REQUEST, COMMAND: begin read_legal=0; write_legal=1; end
            READ_RESULT: read_value=read_ready ? read_result : 8'h00;
            EXT_INDEX: begin read_value=ext_index; write_legal=1; end
            EXT_DATA: begin read_value=ext_value_q; write_legal=ext_writable; end
            AUDIO_INDEX: begin read_value=audio_index; write_legal=1; end
            AUDIO_DATA: begin read_value=audio_rdata; read_legal=audio_read_legal; write_legal=audio_write_legal; end
            FIFO_STATUS: read_value={full,1'b0,free_q};
            INC_L: begin read_value=inc[7:0]; write_legal=1; end
            INC_H: begin read_value=inc[15:8]; write_legal=1; end
            LENGTH_L: begin read_value=length[7:0]; write_legal=1; end
            LENGTH_H: begin read_value=length[15:8]; write_legal=1; end
            FILL_VALUE: begin read_value=fill_value; write_legal=1; end
            FENCE_TAG: begin read_value=fence_value; write_legal=1; end
            DONE_TAG: read_value=done_tag;
            ERROR_CODE: begin read_value=error_code; write_legal=1; end
            ID0: read_value=8'h4b;
            ID1: read_value=8'h39;
            ABI_MAJOR: read_value=8'h00;
            ABI_MINOR: read_value=8'h05;
            CAPS_REG: read_value=CAPS;
            FRAME_COUNT: read_value=frame_count;
            SPR_OVF_INDEX: read_value=overflow_index;
            SPR_OVF_LINE: read_value=overflow_line;
            default: read_value=8'h00;
        endcase
    end

    // Per-access errors and the descriptor a successful command enqueues.
    reg [7:0] errors;
    reg enqueue, advance;
    always @* begin
        errors=0; enqueue=0; advance=0;
        if(rd) begin
            if(!read_legal) errors[E_BAD_ACCESS]=1;
            if(q_addr==READ_RESULT && !read_ready) errors[E_NOT_READY]=1;
        end
        if(wr) begin
            if(!write_legal) errors[E_BAD_ACCESS]=1;
            else case(q_addr)
                VRAM_WRITE: begin
                    if(full) errors[E_FIFO_FULL]=1;
                    if(!addr_ok) errors[E_INVALID_ADDRESS]=1;
                end
                READ_REQUEST: begin
                    if(!q_zero) errors[E_BAD_ACCESS]=1;
                    if(read_busy || read_ready) errors[E_READ_COLLISION]=1;
                    if(full) errors[E_FIFO_FULL]=1;
                    if(!addr_ok) errors[E_INVALID_ADDRESS]=1;
                end
                COMMAND: begin
                    if(q_op_fill) begin
                        if(full) errors[E_FIFO_FULL]=1;
                        if(!fill_ok) errors[E_INVALID_ADDRESS]=1;
                    end else if(q_op_fence) begin
                        if(full) errors[E_FIFO_FULL]=1;
                    end else if(q_op_commit) begin
                        if(commit_busy) errors[E_BUSY_CONFLICT]=1;
                        if(full) errors[E_FIFO_FULL]=1;
                        if(!rs_ok) errors[E_BAD_ACCESS]=1;
                    end else if(q_op_audio) begin
                        if(full) errors[E_FIFO_FULL]=1;
                        if(audio_busy) errors[E_BUSY_CONFLICT]=1;
                        if(!audio_settings_valid) errors[E_BAD_ACCESS]=1;
                    end else if(q_op_copy) begin
                        if(full) errors[E_FIFO_FULL]=1;
                        if(!copy_ok) errors[E_INVALID_ADDRESS]=1;
                    end else errors[E_BAD_ACCESS]=1;
                end
                EXT_DATA: if(rs_is_table && commit_busy) errors[E_BUSY_CONFLICT]=1;
                    else if(RS && rs_bad_value) errors[E_BAD_ACCESS]=1;
                default: ;
            endcase
            // Decode admission directly rather than passing q_addr through
            // the general error-vector mux and a reduction back to push_q.
            // Keep the same refusal conditions as the error reporting above.
            case(q_addr)
                VRAM_WRITE: enqueue=!full && addr_ok;
                READ_REQUEST: enqueue=!full && addr_ok && q_zero && !read_busy && !read_ready;
                COMMAND: enqueue=!full && (q_op_fill && fill_ok || q_op_fence || q_op_commit && !commit_busy && rs_ok
                    || q_op_audio && !audio_busy && audio_settings_valid || q_op_copy && copy_ok);
                default: ;
            endcase
            advance=enqueue && q_addr!=COMMAND;
            if(!init_done && (q_addr==VRAM_WRITE || q_addr==READ_REQUEST || q_addr==COMMAND)) begin
                errors[E_NOT_READY]=1; enqueue=0; advance=0;
            end
        end
    end
    // Descriptor fields straight from the request, independent of the error
    // checks (they only gate `enqueue`); the engine ignores unused fields.
    // COMMAND values 01..03 are the queue opcodes themselves.
    wire [7:0] desc_op=q_addr==VRAM_WRITE ? OP_WRITE : q_addr==READ_REQUEST ? OP_READ : q_wdata;
    wire [7:0] desc_data=q_addr==VRAM_WRITE ? q_wdata : q_op_fill ? fill_value : fence_value;
    wire is_commit=q_addr==COMMAND && q_op_commit;
    // COPY: address = source (PSRAM), data/flags = destination VRAM_ADDR[15:0].
    wire is_copy=q_addr==COMMAND && q_op_copy;
    wire [23:0] desc_addr=is_commit ? {4'b0,display_ctrl,scroll_x,scroll_y} : is_copy ? copy_src : vram_addr;
    wire [15:0] desc_len=is_commit ? {backdrop,raster_line} : length;
    wire [63:0] desc=is_copy ? {vram_addr[15:0],desc_len,desc_addr,desc_op} : {8'h00,desc_data,desc_len,desc_addr,desc_op};
    reg push_q, advance_q;
    reg [63:0] desc_q;
    assign push=push_q;
    assign push_desc=desc_q;
    assign audio_index_write=wr && q_addr==AUDIO_INDEX;
    assign audio_data_write=wr && q_addr==AUDIO_DATA && audio_write_legal;
    // Same admission as `enqueue` for AUDIO_COMMIT, decoded directly so the
    // snapshot capture does not wait for the full command admission mux.
    assign audio_capture=wr && q_addr==COMMAND && q_op_audio && !full && !audio_busy && audio_settings_valid && init_done;
    assign audio_wdata=q_wdata;

    // New events win over a same-cycle W1C clear.
    wire [7:0] new_errors=errors | (error_events & 8'h60);
    wire [7:0] new_irq=(irq_events & 8'h23) | {1'b0,new_errors!=0,1'b0,commit_done,read_done,fence_done,2'b00};
    wire w1c_irq=wr && q_addr==IRQ_STATUS;
    wire clear_overflow=w1c_irq && q_wdata[5];
    wire w1c_err=wr && q_addr==ERROR_CODE;
    wire ext_data_selected=PSRAM ? q_ext_data : q_addr==EXT_DATA;
    wire ext_write=wr && ext_data_selected && ext_writable && !rs_block;
    // Entry values have no value-range rejection. Decode their write enable
    // directly so q_wdata's COUNT/INDEX checks do not fan out to 200 table FFs.
    wire rs_entry_write=wr && ext_data_selected && ext_index>=8'h0d && ext_index<=8'h10
        && !(rs_is_table && commit_busy);
    assign dbg_arm=DEBUG && ext_write && ext_index==8'h18;
    assign dbg_arm_value=q_wdata;
    // Validity of the shadow raster table (lines < LINES, strictly ascending,
    // only entries below RS_COUNT), registered in two stages; rs_settle keeps
    // requests off until it reflects the latest table write.
    reg [7:0] rs_line_ok, rs_asc_ok;
    integer ri;
    always @(posedge clk)
        if(reset) begin rs_line_ok<=8'hff; rs_asc_ok<=8'hff; rs_ok<=1; end
        else begin
            for(ri=0;ri<8;ri=ri+1) begin
                rs_line_ok[ri]<=rs_table[25*ri +: 8]<8'(LINES);
                rs_asc_ok[ri]<= ri==0 ? 1'b1 : rs_table[25*ri +: 8]>rs_table[25*(ri-1) +: 8];
            end
            rs_ok<=1;
            for(ri=0;ri<8;ri=ri+1) if(ri<rs_count && !(rs_line_ok[ri] && rs_asc_ok[ri])) rs_ok<=0;
        end
    always @(posedge clk)
        if(reset) begin
            irq_status<=0; irq_enable<=0; error_code<=0; display_ctrl<=0; overflow_index<=0; overflow_line<=0;
            vram_addr<=0; inc<=16'd1; length<=0; fill_value<=0; fence_value<=0;
            done_tag<=0; frame_count<=0; ext_index<=0; read_busy<=0; read_ready<=0; read_result<=0;
            commit_busy<=0;
            scroll_x<=0; scroll_y<=0; backdrop<=0; raster_line<=8'd255;
            rs_count<=0; rs_table<=0; rs_idx<=0; rs_settle<=0; copy_src<=0; dbg_index<=0;
            rsp_valid<=0; rsp_rdata<=0; rsp_error<=0; checks_stale<=1; push_q<=0; desc_q<=0; advance_q<=0;
        end else begin
            push_q<=enqueue; desc_q<=desc; advance_q<=advance;
            checks_stale<=enqueue || advance || advance_q || (wr && (q_addr==ADDR_L || q_addr==ADDR_M || q_addr==ADDR_H
                || q_addr==LENGTH_L || q_addr==LENGTH_H)) || (ext_write && ext_index>=8'h14 && ext_index<=8'h16);
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            irq_status<=((w1c_irq ? irq_status & ~q_wdata : irq_status) | new_irq) & 8'h7f;
            if(clear_overflow) begin overflow_index<=0; overflow_line<=0; end
            if(irq_events[5] && (!irq_status[5] || clear_overflow)) begin
                overflow_index<=sprite_overflow_index; overflow_line<=sprite_overflow_line;
            end
            error_code<=(w1c_err ? error_code & ~q_wdata : error_code) | new_errors;
            if(irq_events[0]) frame_count<=frame_count+1'b1;
            if(fence_done) done_tag<=fence_tag;
            if(read_done) begin read_busy<=0; read_ready<=1; read_result<=read_data; end
            if(wr) case(q_addr)
                IRQ_ENABLE: irq_enable<=q_wdata & 8'h7f;
                DISPLAY_CTRL: display_ctrl<=q_wdata[2:0];
                ADDR_L: vram_addr[7:0]<=q_wdata;
                ADDR_M: vram_addr[15:8]<=q_wdata;
                ADDR_H: vram_addr[23:16]<=q_wdata;
                EXT_INDEX: ext_index<=q_wdata;
                INC_L: inc[7:0]<=q_wdata;
                INC_H: inc[15:8]<=q_wdata;
                LENGTH_L: length[7:0]<=q_wdata;
                LENGTH_H: length[15:8]<=q_wdata;
                FILL_VALUE: fill_value<=q_wdata;
                FENCE_TAG: fence_value<=q_wdata;
                default: ;
            endcase
            if(ext_write) case(ext_index)
                8'h00: scroll_x[7:0]<=q_wdata;
                8'h01: scroll_x[8]<=q_wdata[0];
                8'h02: scroll_y<=q_wdata;
                8'h03: backdrop<=q_wdata;
                8'h04: raster_line<=q_wdata;
                8'h14: copy_src[7:0]<=q_wdata;
                8'h15: copy_src[15:8]<=q_wdata;
                8'h16: copy_src[23:16]<=q_wdata;
                8'h17: dbg_index<=q_wdata;
                8'h0b: rs_count<=q_wdata[3:0];
                8'h0c: rs_idx<=q_wdata[2:0];
                8'h10: rs_idx<=rs_idx+1'b1;
                default: ;
            endcase
            for(ri=0;ri<8;ri=ri+1) if(rs_entry_write && rs_idx==ri[2:0]) case(ext_index)
                8'h0d: rs_table[25*ri +: 8]<=q_wdata;
                8'h0e: rs_table[25*ri+8 +: 8]<=q_wdata;
                8'h0f: rs_table[25*ri+16]<=q_wdata[0];
                8'h10: rs_table[25*ri+17 +: 8]<=q_wdata;
                default: ;
            endcase
            rs_settle<={rs_settle[1:0], ext_write && ext_index>=8'h0b && ext_index<=8'h10};
            // One cycle after acceptance (timing); the next request is stalled.
            if(advance_q) vram_addr<=vram_addr+{8'h00,inc};
            if(enqueue && q_addr==READ_REQUEST) read_busy<=1;
            if(commit_done) commit_busy<=0;
            if(enqueue && is_commit) commit_busy<=1;
            if(rd && q_addr==READ_RESULT && read_ready) read_ready<=0;
            if(accept) begin
                rsp_valid<=1;
                rsp_rdata<=q_write ? 8'h00 : read_value;
                rsp_error<=errors!=0;
            end
        end
endmodule
