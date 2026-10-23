// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
// Shooter scene inside the wall phases: fixed OAM order (anim 316, the
// wall crosses the enemy formation) and rotated order (anim 572).
module tb_demo_wall;
    tb_demo_shooter #(.START(316)) fixed_order();
endmodule
module tb_demo_flicker;
    tb_demo_shooter #(.START(572)) rotated_order();
endmodule
// 16:9 build: the same scene on 320x180 (ship at y=136) shown on 1280x720.
module tb_demo_shooter720;
    tb_demo_shooter #(.VIC(4)) wide();
endmodule
