// SPDX-License-Identifier: Apache-2.0
module tb_demo_audio;
    tb_demo_sequencer #(.SPRITES(1),.AUDIO(1)) test();
    integer samples=0;
    always @(negedge test.sys) if(test.configured && test.dut.core.audio_sample_valid) begin
        if(test.dut.core.audio_status[2:1]!=0) $fatal(1,"demo audio FIFO error");
        if(test.dut.core.audio_left!=0 || test.dut.core.audio_right!=0) samples=samples+1;
    end
    final begin
        if(samples<100) $error("demo did not produce audio");
    end
endmodule
