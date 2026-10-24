// SPDX-License-Identifier: Apache-2.0
// Mode-0, single-lane SPI NOR reader.  The generated SCLK stays in the
// system-clock domain; CLK_DIV is the number of clk cycles per half SCLK.
//
// A command is accepted when cmd_valid && cmd_ready.  JEDEC_ID sends 9f and
// returns three bytes.  READ sends 03 plus a 24-bit address and returns
// byte_count bytes.  data_valid is held until data_ready, so SCLK may pause
// low between bytes without losing the flash stream position.
module kagura_flash_reader #(
    parameter integer CLK_DIV=4
) (
    input wire clk,
    input wire reset,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire cmd_jedec_id,
    input wire [23:0] cmd_addr,
    input wire [23:0] cmd_byte_count,
    output reg data_valid,
    input wire data_ready,
    output reg [7:0] data,
    output reg done,
    output reg error,
    output reg flash_cs_n,
    output reg flash_sclk,
    output reg flash_mosi,
    input wire flash_miso
);
    localparam integer DIV_W = CLK_DIV <= 1 ? 1 : $clog2(CLK_DIV);
    localparam integer DIV_LAST = CLK_DIV-1;
    localparam [2:0] IDLE=0, SEND=1, RECEIVE=2, HOLD=3, FINISH=4;
    reg [2:0] state;
    reg [DIV_W-1:0] divider;
    reg [31:0] tx_shift;
    reg [5:0] tx_bits;
    reg [7:0] rx_shift;
    reg [2:0] rx_bits;
    reg [23:0] bytes_left;

    assign cmd_ready=(state==IDLE);

    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE; divider<=0; tx_shift<=0; tx_bits<=0;
            rx_shift<=0; rx_bits<=0; bytes_left<=0;
            data_valid<=0; data<=0; done<=0; error<=0;
            flash_cs_n<=1; flash_sclk<=0; flash_mosi<=0;
        end else begin
            done<=0;
            case(state)
                IDLE: begin
                    flash_cs_n<=1; flash_sclk<=0; flash_mosi<=0;
                    data_valid<=0; divider<=0;
                    if(cmd_valid) begin
                        error<=0; flash_cs_n<=0;
                        if(cmd_jedec_id) begin
                            tx_shift<=32'h9f000000; tx_bits<=8;
                            bytes_left<=3; flash_mosi<=1;
                            state<=SEND;
                        end else if(cmd_byte_count!=0) begin
                            tx_shift<={8'h03,cmd_addr}; tx_bits<=32;
                            bytes_left<=cmd_byte_count; flash_mosi<=0;
                            state<=SEND;
                        end else begin
                            error<=1; state<=FINISH;
                        end
                    end
                end
                SEND: begin
                    if(divider==DIV_LAST[DIV_W-1:0]) begin
                        divider<=0;
                        if(!flash_sclk) begin
                            flash_sclk<=1;
                        end else begin
                            flash_sclk<=0;
                            tx_shift<={tx_shift[30:0],1'b0};
                            if(tx_bits==1) begin
                                tx_bits<=0; rx_bits<=0; rx_shift<=0;
                                flash_mosi<=0; state<=RECEIVE;
                            end else begin
                                tx_bits<=tx_bits-1'b1;
                                flash_mosi<=tx_shift[30];
                            end
                        end
                    end else divider<=divider+1'b1;
                end
                RECEIVE: begin
                    if(divider==DIV_LAST[DIV_W-1:0]) begin
                        divider<=0;
                        if(!flash_sclk) begin
                            flash_sclk<=1;
                            rx_shift<={rx_shift[6:0],flash_miso};
                            if(rx_bits==7) begin
                                data<={rx_shift[6:0],flash_miso};
                                rx_bits<=0; state<=HOLD;
                            end else rx_bits<=rx_bits+1'b1;
                        end else flash_sclk<=0;
                    end else divider<=divider+1'b1;
                end
                HOLD: begin
                    // Complete the final high half-cycle before presenting a
                    // stable low SCLK pause to the stream consumer.
                    if(flash_sclk) begin
                        if(divider==DIV_LAST[DIV_W-1:0]) begin
                            divider<=0; flash_sclk<=0;
                        end else divider<=divider+1'b1;
                    end else if(!data_valid) begin
                        data_valid<=1;
                    end else if(data_ready) begin
                        data_valid<=0;
                        if(bytes_left==1) begin
                            bytes_left<=0; state<=FINISH;
                        end else begin
                            bytes_left<=bytes_left-1'b1;
                            rx_shift<=0; state<=RECEIVE;
                        end
                    end
                end
                FINISH: begin
                    flash_cs_n<=1; flash_sclk<=0; flash_mosi<=0;
                    data_valid<=0; done<=1; state<=IDLE;
                end
                default: begin error<=1; state<=FINISH; end
            endcase
        end
    end

    initial begin
        if(CLK_DIV<1) $error("CLK_DIV must be at least 1");
    end
endmodule
