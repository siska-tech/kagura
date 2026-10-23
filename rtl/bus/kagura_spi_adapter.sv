// SPDX-License-Identifier: Apache-2.0
// SPI (LANES=1) / QSPI (LANES=4) host adapter (docs/host-interface.md).
// SCK, /CS and IO are oversampled on the 54MHz system clock through 2FF
// synchronizers; SPI mode 0, MSB first, one byte = 8/LANES chunks.
// - Input data is the synchronized sample taken together with the first
//   SCK-high sample of a rising edge.
// - Output changes right after a detected rising edge, so the host keeps
//   almost a full SCK period of setup and >=37ns of hold.
// Transaction (one /CS low): header {rw, inc, reserved, offset[4:0]}, then
// write: data bytes, each one write request once complete;
// read:  count N (0 = 256), one dummy byte, then N data bytes. The read for
//        data byte k is issued at the second-to-last chunk of the byte
//        before it; exactly N reads are issued, later bytes return 0.
// SPI returns FIFO_STATUS, fetched at /CS fall, on MISO during the header.
// QSPI drives IO3..0 from the first dummy edge until /CS rises.
// One request is held at a time; a byte completing while the previous
// request is still unaccepted, or read data missing its deadline, sets the
// sticky `late`.
module kagura_spi_adapter #(
    parameter integer LANES=1,
    parameter integer BUSY_MARGIN=3
) (
    input wire clk, reset,
    // host pins (tri-state resolved at the top level)
    input wire spi_sck, spi_cs_n,
    input wire [3:0] spi_io_in,
    output wire [3:0] spi_io_out,
    output reg [3:0] spi_io_oe,
    output reg busy,
    output reg irq_drive,              // 1 pulls /IRQ low (open drain)
    input wire irq_level,
    input wire [5:0] queue_free,
    // CPU-independent request/response interface (docs/architecture.md)
    output reg req_valid,
    input wire req_ready,
    output reg req_write,
    output reg [4:0] req_addr,
    output reg [7:0] req_wdata,
    input wire rsp_valid,
    output wire rsp_ready,
    input wire [7:0] rsp_rdata,
    input wire rsp_error,
    output reg late
);
    localparam integer CHUNKS=8/LANES;
    localparam [4:0] FIFO_STATUS=5'h0f;
    localparam [1:0] HEADER=2'd0, COUNT=2'd1, DUMMY=2'd2, DATA=2'd3;
    (* ASYNC_REG="TRUE" *) reg [1:0] sck_sync, cs_sync;
    (* ASYNC_REG="TRUE" *) reg [3:0] io_sync0, io_sync1;
    reg sck_q, cs_q;
    wire active=!cs_sync[1];
    wire start=active && cs_q;
    wire rise=active && !cs_q && sck_sync[1] && !sck_q;
    wire [LANES-1:0] lanes_in=io_sync1[LANES-1:0];

    reg [1:0] phase;
    reg [2:0] chunk;
    reg is_read, inc, discard;
    reg [4:0] offset;
    reg [8:0] fetch_left;
    reg [7:0] in_shift, out_shift, next_out;
    reg next_valid, fetched, pending_read, status_pending;
    wire last_chunk=chunk==CHUNKS-1;
    wire fetch_chunk=chunk==CHUNKS-2;
    wire [7:0] byte_in={in_shift[7-LANES:0],lanes_in};
    wire fetch=is_read && (phase==DUMMY || phase==DATA) && fetch_chunk && fetch_left!=0;
    // SPI drives MISO (IO1); QSPI drives IO3..IO0.
    assign spi_io_out=LANES==1 ? {2'b00,out_shift[7],1'b0} : out_shift[7:4];
    assign rsp_ready=1'b1;

    always @(posedge clk)
        if(reset) begin
            sck_sync<=0; cs_sync<=2'b11; io_sync0<=0; io_sync1<=0; sck_q<=0; cs_q<=1;
            phase<=HEADER; chunk<=0; is_read<=0; inc<=0; discard<=1; offset<=0; fetch_left<=0;
            in_shift<=0; out_shift<=0; next_out<=0; next_valid<=0; fetched<=0;
            pending_read<=0; status_pending<=0;
            spi_io_oe<=0; busy<=1; irq_drive<=0; late<=0;
            req_valid<=0; req_write<=0; req_addr<=0; req_wdata<=0;
        end else begin
            sck_sync<={sck_sync[0],spi_sck}; cs_sync<={cs_sync[0],spi_cs_n};
            io_sync0<=spi_io_in; io_sync1<=io_sync0;
            sck_q<=sck_sync[1]; cs_q<=cs_sync[1];
            busy<=queue_free<BUSY_MARGIN;
            irq_drive<=irq_level;
            if(req_valid && req_ready) req_valid<=0;
            if(rsp_valid && pending_read) begin
                pending_read<=0;
                if(status_pending) begin
                    status_pending<=0;
                    if(active && phase==HEADER && chunk==0) out_shift<=rsp_rdata;
                end else begin next_out<=rsp_rdata; next_valid<=1; end
            end
            if(start) begin
                phase<=HEADER; chunk<=0; discard<=0; out_shift<=0; next_valid<=0; fetched<=0;
                // The previous transaction must be finished (t_CSW).
                if(req_valid || pending_read) late<=1;
                else if(LANES==1) begin
                    spi_io_oe<=4'b0010;
                    req_valid<=1; req_write<=0; req_addr<=FIFO_STATUS;
                    pending_read<=1; status_pending<=1;
                end
            end else if(!active) begin
                spi_io_oe<=0; phase<=HEADER; discard<=1;
            end else if(rise && !discard) begin
                chunk<=last_chunk ? 3'd0 : chunk+1'b1;
                in_shift<=byte_in;
                out_shift<=out_shift<<LANES;
                if(phase==HEADER && chunk==0 && status_pending) late<=1;
                // QSPI turns the bus around on the first dummy edge.
                if(LANES!=1 && phase==DUMMY && chunk==0) spi_io_oe<=4'b1111;
                if(fetch) begin
                    if(req_valid && !req_ready) late<=1;
                    else begin
                        req_valid<=1; req_write<=0; req_addr<=offset;
                        pending_read<=1; fetched<=1; fetch_left<=fetch_left-1'b1;
                        if(inc) offset<=offset+1'b1;
                    end
                end
                if(last_chunk) case(phase)
                    HEADER: begin
                        is_read<=byte_in[7]; inc<=byte_in[6]; discard<=byte_in[5]; offset<=byte_in[4:0];
                        phase<=byte_in[7] ? COUNT : DATA;
                        out_shift<=0;
                    end
                    COUNT: begin fetch_left<={byte_in==0,byte_in}; phase<=DUMMY; out_shift<=0; end
                    default: begin
                        phase<=DATA;
                        if(is_read) begin
                            // Bytes after the N-th return 0 without a request.
                            out_shift<=fetched ? next_out : 8'h00;
                            if(fetched && !next_valid) late<=1;
                            fetched<=0; next_valid<=0;
                        end else if(req_valid && !req_ready) late<=1;
                        else begin
                            req_valid<=1; req_write<=1; req_addr<=offset; req_wdata<=byte_in;
                            if(inc) offset<=offset+1'b1;
                        end
                    end
                endcase
            end
        end
endmodule
