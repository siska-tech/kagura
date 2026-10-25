// SPDX-License-Identifier: Apache-2.0
// Public PCM channel control (docs/audio-spec.md, ABI 0.4) between the audio
// registers, kagura_pcm_prefetch and the synthesizer's AUDIO_COMMIT boundary.
//
// PREPARE stops the channel if needed, loads START/END/LOOP into the
// prefetcher once it accepts a configuration, and drops the PSRAM read cache.
// READY means the prefill completed for a configuration that has not ended,
// underrun or failed since; only a READY channel can start. Playback starts or
// pauses on the sample boundary where an AUDIO_COMMIT applies: a committed
// ENABLE=1 starts a READY, inactive channel, ENABLE=0 pauses an active one
// (its buffer and position are kept). STOP halts at once. DONE, UNDERRUN,
// CONFIG_ERROR and MEMORY_ERROR are sticky until CLEAR; after any of them (or
// STOP) the channel needs a new PREPARE before it is READY again.
module kagura_pcm_control (
    input  wire clk,
    input  wire reset,
    input  wire [1:0] prepare,         // pulses from the register block
    input  wire [1:0] stop,
    input  wire [1:0] clear,
    input  wire apply_boundary,        // AUDIO_COMMIT applies on this sample boundary
    input  wire [1:0] commit_enable,   // ENABLE in the snapshot being applied

    output wire [1:0] cfg_valid,
    input  wire [1:0] cfg_ready,
    output wire [1:0] start_play,
    output wire [1:0] stop_play,
    output wire cache_flush,
    input  wire [1:0] pf_ready,
    input  wire [1:0] pf_active,
    input  wire [1:0] pf_done,         // pulses
    input  wire [1:0] pf_underrun,
    input  wire [1:0] pf_config_error,
    input  wire [1:0] pf_memory_error,

    output wire [7:0] status0,
    output wire [7:0] status1
);
    reg [1:0] pending,need_prepare,done,underrun,config_error,memory_error;
    wire [1:0] accept=cfg_valid & cfg_ready;
    wire [1:0] ready=pf_ready & ~need_prepare & ~pending;
    assign cfg_valid=pending & cfg_ready;
    assign cache_flush=|accept;
    assign stop_play=stop | (prepare & pf_active) | ({2{apply_boundary}} & ~commit_enable & pf_active);
    assign start_play={2{apply_boundary}} & commit_enable & ready & ~pf_active & ~prepare & ~stop;
    // b0 READY, b1 ACTIVE, b2 DONE, b3 UNDERRUN, b4 CONFIG_ERROR, b5 MEMORY_ERROR, b6 PREPARING
    assign status0={1'b0,pending[0] || (!need_prepare[0] && !pf_ready[0] && !pf_active[0]),
        memory_error[0],config_error[0],underrun[0],done[0],pf_active[0],ready[0]};
    assign status1={1'b0,pending[1] || (!need_prepare[1] && !pf_ready[1] && !pf_active[1]),
        memory_error[1],config_error[1],underrun[1],done[1],pf_active[1],ready[1]};
    always @(posedge clk)
        if(reset) begin
            pending<=0; need_prepare<=2'b11; done<=0; underrun<=0; config_error<=0; memory_error<=0;
        end else begin
            pending<=(pending & ~accept) | prepare;
            need_prepare<=(need_prepare & ~accept) | stop | pf_done | pf_underrun | pf_config_error | pf_memory_error;
            done<=(done & ~clear) | pf_done;
            underrun<=(underrun & ~clear) | pf_underrun;
            config_error<=(config_error & ~clear) | pf_config_error;
            memory_error<=(memory_error & ~clear) | pf_memory_error;
        end
endmodule
