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
