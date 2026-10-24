`timescale 1ns/1ps
module tb_vdp_sprites;
    tb_vdp_frame #(.SPRITES(1)) frames();
endmodule
// 16:9 mode: the same scenes on 1280x720 (docs/wide-mode.md).
module tb_vdp_frame720;
    tb_vdp_frame #(.SPRITES(0),.VIC(4)) frames();
endmodule
module tb_vdp_sprites720;
    tb_vdp_frame #(.SPRITES(1),.VIC(4)) frames();
endmodule
// Raster scroll (ABI 0.3, docs/raster-scroll.md) on 640x480 and 1280x720.
module tb_raster_scroll;
    tb_vdp_frame #(.SPRITES(0),.VIC(1),.RASTER(1)) frames();
endmodule
module tb_raster_scroll720;
    tb_vdp_frame #(.SPRITES(0),.VIC(4),.RASTER(1)) frames();
endmodule
