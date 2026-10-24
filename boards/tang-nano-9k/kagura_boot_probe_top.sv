// SPDX-License-Identifier: Apache-2.0
// Stage-1 hardware probe: validate the on-board SPI NOR without a CPU/HDMI.
// LEDs (lit when low): expected JEDEC ID, valid image, error-code bits 3..0.
module kagura_boot_probe_top (
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

    wire boot_ready,boot_error,unmap_request,req_ready,rsp_valid,rsp_error;
    wire [3:0] error_code;
    wire [23:0] jedec_id;
    wire [7:0] rsp_rdata;
    kagura_boot_controller boot(system_clk,~system_release[3],
        flash_cs_n,flash_sclk,flash_mosi,flash_miso,
        boot_ready,boot_error,error_code,jedec_id,unmap_request,
        1'b0,req_ready,1'b0,5'b0,8'b0,rsp_valid,1'b1,rsp_rdata,rsp_error);

    assign boot_map=1'b0;
    assign led_n=~{jedec_id==24'h856016,boot_ready,error_code};
    wire unused=&{1'b0,pixel_lock,boot_error,unmap_request,req_ready,rsp_valid,rsp_error,rsp_rdata};
endmodule
