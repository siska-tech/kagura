`timescale 1ns/1ps
// Real VRAM path: bank boundaries, 11-bit map/OAM IDs, all palettes/flips,
// transparent invalid IDs, 16px alignment, clipping and system-only reset.
module tb_tile1200_frame;
    tb_vdp_frame #(.SPRITES(1),.EXTENDED(1),.VIC(1)) test_frame();
endmodule
module tb_tile1200_frame720;
    tb_vdp_frame #(.SPRITES(1),.EXTENDED(1),.VIC(4)) test_frame();
endmodule
