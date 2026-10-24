// SPDX-License-Identifier: Apache-2.0
// Read-only hardware diagnostic for JEDEC ID and K9BT magic at 0x100000.
// Lit LED1..6: K, 9, B, T, JEDEC 856016, transaction complete.
module kagura_flash_magic_probe_top (
    input wire clk27,reset_n,
    output wire [5:0] led_n,
    output wire boot_map,
    output wire flash_cs_n,flash_sclk,flash_mosi,
    input wire flash_miso
);
    wire pixel_unused,serial_unused,system_clk,pixel_lock,system_lock;
    kagura_nano9k_clocks clocks(clk27,reset_n,pixel_unused,serial_unused,
        system_clk,pixel_lock,system_lock);
    wire release_ok=reset_n && system_lock;
    (* ASYNC_REG="TRUE" *) reg [3:0] system_release;
    always @(posedge system_clk or negedge release_ok)
        if(!release_ok) system_release<=0;
        else system_release<={system_release[2:0],1'b1};

    localparam [2:0] ID_CMD=0,ID_DATA=1,READ_CMD=2,READ_DATA=3,DONE=4,FAIL=5;
    reg [2:0] state;
    reg [1:0] index;
    reg [23:0] jedec_id;
    reg [3:0] magic_match;
    wire cmd_ready,data_valid,reader_done,reader_error;
    wire [7:0] data;
    wire cmd_valid=state==ID_CMD || state==READ_CMD;
    wire cmd_jedec=state==ID_CMD;
    wire data_ready=state==ID_DATA || state==READ_DATA;
    kagura_flash_reader reader(system_clk,~system_release[3],
        cmd_valid,cmd_ready,cmd_jedec,24'h100000,24'd4,
        data_valid,data_ready,data,reader_done,reader_error,
        flash_cs_n,flash_sclk,flash_mosi,flash_miso);

    function automatic [7:0] expected(input [1:0] position);
        case(position)
            0: expected=8'h4b; 1: expected=8'h39;
            2: expected=8'h42; default: expected=8'h54;
        endcase
    endfunction

    always @(posedge system_clk) begin
        if(!system_release[3]) begin
            state<=ID_CMD; index<=0; jedec_id<=0; magic_match<=0;
        end else case(state)
            ID_CMD: if(cmd_ready) begin index<=0; jedec_id<=0; state<=ID_DATA; end
            ID_DATA: begin
                if(data_valid) begin jedec_id<={jedec_id[15:0],data}; index<=index+1'b1; end
                if(reader_done) begin index<=0; state<=reader_error ? FAIL : READ_CMD; end
            end
            READ_CMD: if(cmd_ready) begin index<=0; magic_match<=0; state<=READ_DATA; end
            READ_DATA: begin
                if(data_valid) begin
                    magic_match[index]<=data==expected(index);
                    index<=index+1'b1;
                end
                if(reader_done) state<=reader_error ? FAIL : DONE;
            end
            default: state<=state;
        endcase
    end

    assign boot_map=1'b0;
    // Vector bit 0 is physical LED1 in the board CST.
    assign led_n=~{state==DONE,jedec_id==24'h856016,
        magic_match[3],magic_match[2],magic_match[1],magic_match[0]};
    wire unused=&{1'b0,pixel_lock};
endmodule
