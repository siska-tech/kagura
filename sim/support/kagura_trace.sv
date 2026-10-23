// SPDX-License-Identifier: Apache-2.0
// Opt-in waveform dump, bound to a testbench top by tools/test-verilator.sh
// when KAGURA_TRACE names it. Dumps only when +kagura_trace=<file> is given.
module kagura_trace;
    string path;
    initial if($value$plusargs("kagura_trace=%s",path)) begin
        $dumpfile(path);
        $dumpvars(0);
    end
endmodule
