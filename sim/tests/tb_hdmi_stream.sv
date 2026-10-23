`timescale 1ns/1ps
// Monitor encoded symbols before OSER10. Physical serial timing is a later test.
module serializer # (parameter int NUM_CHANNELS=3, parameter real VIDEO_RATE=25.2e6)
    (input wire clk_pixel,clk_pixel_x5,reset,
     input wire [9:0] tmds_internal[NUM_CHANNELS-1:0],
     output wire [2:0] tmds, output wire tmds_clock);
    assign tmds=0; assign tmds_clock=clk_pixel;
endmodule
// VIC1 keeps the real 54/25.2MHz ratio (1125 system clocks = 525 pixel
// clocks per sample); VIC4 keeps 54/74.25MHz (1125 = 1546.875).
module tb_hdmi_stream_core #(parameter integer VIC=1);
    localparam real PIX_HALF=VIC==4 ? 7.0*1125.0/1546.875 : 15.0;
    localparam [19:0] CTS=VIC==4 ? 20'd74250 : 20'd25200;
    reg sys=0,pix=0,fast=0,reset=1,sv=0;
    always #7 sys=~sys;
    always #(PIX_HALF) pix=~pix;
    always #(PIX_HALF/5.0) fast=~fast;
    reg [31:0] sd=0;
    wire full,ov,uf,tc,muted;
    wire [2:0] tx;
    kagura_hdmi_stream_eval #(.VIDEO_ID_CODE(VIC)) dut(sys,pix,fast,reset,sv,sd,full,ov,uf,tx,tc,muted,24'h000000,,,);
    integer div=0,produced=0,received=0,bit_index=0,j,lead_silence=0,acrs=0,avis=0,acr_samples=0;
    reg [2:0] emitted_mode;
    reg [31:0] h;
    reg [63:0] b[0:3];
    reg [3:0] nib[0:2];
    reg [8:0] packet_bits;
    function automatic [3:0] decode(input reg [9:0] symbol);
        begin
            case(symbol)
                10'b1010011100:decode=0; 10'b1001100011:decode=1;
                10'b1011100100:decode=2; 10'b1011100010:decode=3;
                10'b0101110001:decode=4; 10'b0100011110:decode=5;
                10'b0110001110:decode=6; 10'b0100111100:decode=7;
                10'b1011001100:decode=8; 10'b0100111001:decode=9;
                10'b0110011100:decode=10;10'b1011000110:decode=11;
                10'b1010001110:decode=12;10'b1001110001:decode=13;
                10'b0101100011:decode=14;10'b1011000011:decode=15;
                default:begin $fatal(1,"invalid TERC4 symbol");decode=0;end
            endcase
        end
    endfunction
    // kagura_tmds_channel emits a symbol three pixel clocks after its mode.
    reg [2:0] mode_d1, mode_d2;
    always @(posedge pix) begin mode_d1<=dut.protocol.mode; mode_d2<=mode_d1; emitted_mode<=mode_d2; end
    always @(negedge sys) begin
        sv=0;
        if(!reset && produced<1024) begin
            if(div==1124) begin
                div=0;sv=1;sd={16'(produced ^ 16'h5aa5),16'(produced)};produced=produced+1;
            end else div=div+1;
        end
    end
    always @(negedge pix) begin
        if(reset) bit_index=0;
        else if(emitted_mode==3) begin
            for(j=0;j<3;j=j+1) nib[j]=decode(dut.protocol.tmds_internal[j]);
            packet_bits={nib[2],nib[1],nib[0][2]};
            h[bit_index]=packet_bits[0];
            for(j=0;j<4;j=j+1) begin
                b[j][2*bit_index]=packet_bits[1+j];
                b[j][2*bit_index+1]=packet_bits[5+j];
            end
            if(bit_index==31) begin
                // ACR: PB1..3 CTS, PB4..6 N=6144 (bits 7:0 = PB0).
                if(h[7:0]==1) begin
                    for(j=0;j<4;j=j+1) if(b[j][55:0]!=={8'h00,8'h18,8'h00,CTS[7:0],CTS[15:8],4'h0,CTS[19:16],8'h00})
                        $fatal(1,"ACR N/CTS %014h",b[j][55:0]);
                    if(received>0) begin acrs=acrs+1; acr_samples=received; end
                end
                // AVI: PB4 is the VIC; PB2 aspect 16:9 only for VIC4.
                if(h[7:0]==8'h82) begin
                    if(b[0][38:32]!==7'(VIC) || b[0][21:20]!==(VIC==4 ? 2'b10 : 2'b00)) $fatal(1,"AVI VIC/aspect");
                    avis=avis+1;
                end
                if(h[7:0]==2) for(j=0;j<4;j=j+1) begin
                    // Startup mute emits silence until the FIFO is prefilled;
                    // any silence after the first source sample is an error.
                    if(b[j][47:0]==0 && received==0) lead_silence=lead_silence+1;
                    else if(b[j][23:0]!=={16'(received),8'b0} ||
                       b[j][47:24]!=={16'(received ^ 16'h5aa5),8'b0})
                        $fatal(1,"integrated PCM mismatch %0d",received);
                    else received=received+1;
                end
                bit_index=0;
            end else bit_index=bit_index+1;
        end else if(bit_index!=0) $fatal(1,"truncated island packet");
    end
    initial begin
        #200; @(posedge pix); #1;reset=0;
        // Discard a partial group/queued samples and restart numbering at zero.
        wait(produced==7); #1;reset=1;
        repeat(5) @(posedge pix);
        #1;produced=0;received=0;lead_silence=0;div=0;reset=0;
        wait(received==1024);
        if(ov || uf || full || lead_silence==0) $fatal(1,"integrated transport error");
        // 48kHz against the 1ms ACR period: 48 samples per ACR, +-2 for phase.
        if(acrs<10 || avis<1) $fatal(1,"%0d ACR, %0d AVI packets",acrs,avis);
        if(acr_samples*1.0/acrs<46.0 || acr_samples*1.0/acrs>50.0) $fatal(1,"%0d samples in %0d ms",acr_samples,acrs);
        $display("PASS: integrated HDMI VIC%0d timing/TERC4 path, 1024 stereo pairs after partial-group reset, ACR CTS=%0d/N=6144, %0d ACR (%0.2f samples/ms), AVI, before PHY",
            VIC,CTS,acrs,acr_samples*1.0/acrs);
        $finish;
    end
    initial begin #25000000; $fatal(1,"stream timeout"); end
endmodule

module tb_hdmi_stream; tb_hdmi_stream_core #(.VIC(1)) tb(); endmodule
module tb_hdmi_stream720; tb_hdmi_stream_core #(.VIC(4)) tb(); endmodule
