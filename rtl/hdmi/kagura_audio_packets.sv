// SPDX-License-Identifier: Apache-2.0
// Fixed-mode 48kHz/16bit stereo scheduler, entirely in the pixel domain.
// ACR uses N=6144 and CTS = pixel clocks per millisecond (25200 for VIC1,
// 74250 for VIC4), sent once every CTS pixel clocks.
// packet_enable must precede a complete 32-pixel packet, as in hdl-util hdmi.
// header/sub are registers loaded on the packet_enable edge with the chosen
// packet (the audio sample packet is built from the samples being consumed),
// so no selection mux sits in front of the assembler's BCH logic; this is
// needed at 74.25MHz. sample_ready is likewise registered from the next count.
module kagura_audio_packets #(
    parameter integer VIDEO_ID_CODE=1,
    parameter integer CTS=25200,
    parameter integer N=6144
) (
    input wire clk_pixel, reset, video_field_end, packet_enable,
    input wire sample_valid,
    input wire [31:0] sample_data, // {right,left}, signed 16bit
    output reg sample_ready,
    output reg [23:0] header,
    output reg [55:0] sub [3:0]
);
    reg [31:0] collected [0:3];
    reg [2:0] count;
    reg [7:0] frame_base;
    reg [16:0] acr_timer;
    localparam [19:0] CTS20=20'(CTS), N20=20'(N);
    // VIC4 is 16:9; VIC1 keeps the original "no data" aspect field.
    localparam [1:0] ASPECT=VIDEO_ID_CODE==4 ? 2'b10 : 2'b00;
    // PB1..3 CTS, PB4..6 N (big endian 20bit); PB0 reserved.
    localparam [55:0] ACR_SUB={N20[7:0],N20[15:8],4'h0,N20[19:16],CTS20[7:0],CTS20[15:8],4'h0,CTS20[19:16],8'h00};
    reg acr_pending,audio_sent,avi_sent,spd_sent;
    wire [23:0] ah,ih,vh,sh;
    wire [55:0] ab[3:0],ib[3:0],vb[3:0],sb[3:0];
    wire [23:0] words [3:0][1:0];
    wire [1:0] zero_bits[3:0];
    genvar g;
    generate for(g=0;g<4;g=g+1) begin: zero
        assign zero_bits[g]=0;
        assign words[g][0]={collected[g][15:0],8'b0};
        assign words[g][1]={collected[g][31:16],8'b0};
    end endgenerate
    audio_sample_packet #(.SAMPLING_FREQUENCY(4'b0010),.WORD_LENGTH(4'b0010)) asp(
        .frame_counter(frame_base),.valid_bit(zero_bits),.user_data_bit(zero_bits),
        .audio_sample_word(words),.audio_sample_word_present(4'b1111),.header(ah),.sub(ab));
    audio_info_frame aif(.header(ih),.sub(ib));
    auxiliary_video_information_info_frame #(.VIDEO_ID_CODE(VIDEO_ID_CODE),.PICTURE_ASPECT_RATIO(ASPECT),.IT_CONTENT(1'b1)) avi(.header(vh),.sub(vb));
    source_product_description_info_frame #(.VENDOR_NAME("KAGURA\0\0"),
        .PRODUCT_DESCRIPTION("KAGURA-9\0\0\0\0\0\0\0\0"),.SOURCE_DEVICE_INFORMATION(8'h08)) spd(.header(sh),.sub(sb));
    wire take_audio=packet_enable && !acr_pending && count==4;
    wire [2:0] count_next=take_audio ? 3'd0 : count+{2'b0,sample_valid && sample_ready};
    integer i;
    always @(posedge clk_pixel) begin
        if(reset) begin
            count<=0; sample_ready<=1; frame_base<=0; header<=0;
            acr_timer<=0; acr_pending<=1; audio_sent<=0; avi_sent<=0; spd_sent<=0;
            for(i=0;i<4;i=i+1) begin collected[i]<=0; sub[i]<=0; end
        end else begin
            if(acr_timer==17'(CTS-1)) begin acr_timer<=0; acr_pending<=1; end
            else acr_timer<=acr_timer+1'b1;
            if(video_field_end) begin audio_sent<=0; avi_sent<=0; spd_sent<=0; end
            if(sample_valid && sample_ready) collected[count[1:0]]<=sample_data;
            count<=count_next;
            sample_ready<=count_next<4;
            if(packet_enable) begin
                header<=0;
                for(i=0;i<4;i=i+1) sub[i]<=0;
                if(acr_pending) begin
                    header<=24'h000001;
                    for(i=0;i<4;i=i+1) sub[i]<=ACR_SUB;
                    // Preserve a new due event occurring on this exact edge.
                    acr_pending<=acr_timer==17'(CTS-1);
                end else if(count==4) begin
                    header<=ah;
                    for(i=0;i<4;i=i+1) sub[i]<=ab[i];
                    frame_base<=frame_base==188 ? 8'd0 : frame_base+8'd4;
                end else if(!audio_sent) begin
                    header<=ih; for(i=0;i<4;i=i+1) sub[i]<=ib[i]; audio_sent<=1;
                end else if(!avi_sent) begin
                    header<=vh; for(i=0;i<4;i=i+1) sub[i]<=vb[i]; avi_sent<=1;
                end else if(!spd_sent) begin
                    header<=sh; for(i=0;i<4;i=i+1) sub[i]<=sb[i]; spd_sent<=1;
                end
            end
        end
    end
endmodule
