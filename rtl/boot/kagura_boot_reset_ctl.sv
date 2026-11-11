// SPDX-License-Identifier: Apache-2.0
// CPU reset control for the ROM-less boot (docs/romless-boot.md): every CPU reset re-runs the boot.
//   reset_req_n  carrier request (debounced reset button / software), active low, any phase.
//                Acted on at the next phase-2 edge (PHI2 low, after the CPU's write strobes):
//                the CPU is held (run_ok = 0 -> the adapter drops cpu_reset_release one clock later),
//                BOOT_MAP returns to 1 and the boot controller is held in reset until the request ends.
//   resb_sense   the CPU RESB net. Any low pulse while KAGURA has released the CPU (an external reset:
//                supervisor, GreenPAK) is caught by an asynchronously set flag, so pulses shorter than a
//                system clock are not lost; the boot restarts and BOOT_MAP returns to 1 at the next phase 2.
//   cpu_reset_release falling for any other reason (ready loss) also restarts the boot.
//   A restart resets the boot controller: flash reader, image check and boot window start again from the
//   JEDEC ID; the CPU stays in reset until the image passes again (boot_ready gates the adapter).
//   vector_ok (to the boot window): bit 0 = at least 3 consecutive valid CPU cycles that did not select
//   KAGURA came just before (stack reads before the reset vector, stack pushes before the BRK vector);
//   bit 1 = fewer than VECTOR_CYCLES valid cycles since the release.
// Phases follow kagura_w65c02_adapter: PHI2 falls on the edge that starts phase 0; "p2" marks the edge that
// starts phase 2 (where the adapter releases RESB and BOOT_MAP is switched).
module kagura_boot_reset_ctl #(
    parameter integer VECTOR_CYCLES=64
) (
    input wire clk,
    input wire sys_reset,
    input wire cpu_phi2,                 // the adapter's PHI2 register
    input wire cpu_reset_release,        // the adapter's RESB release
    input wire cpu_cs_n,                 // KAGURA /CS pin (external decode)
    input wire reset_req_n,              // pin, asynchronous
    input wire resb_sense,               // pin, asynchronous
    input wire unmap_request,            // boot controller: BRK vector read, leave the boot mapping
    output reg boot_map,
    output wire boot_reset,              // boot controller reset
    output wire run_ok,                  // ANDed into the adapter's ready
    output wire [1:0] vector_ok
);
    reg phi2_q, p2, unmap_pending, restart_pending, restart_q, hold_req, rel_q, armed, cv;
    reg [1:0] req_s, seen_s, hi_s;
    reg [6:0] cyc;
    reg [1:0] nonsel;
    wire fall = phi2_q && !cpu_phi2, rise = !phi2_q && cpu_phi2;
    // RESB_SENSE: asynchronously set on any low level; cleared synchronously once RESB is seen high again
    reg low_seen;
    wire seen_clr = sys_reset || (cpu_reset_release && hi_s[1] && !armed);
    always @(posedge clk or negedge resb_sense)
        if(!resb_sense) low_seen<=1;
        else if(seen_clr) low_seen<=0;
    wire ext_event = armed && seen_s[1];
    wire new_req = p2 && req_s[1] && !hold_req;
    wire rel_fall = rel_q && !cpu_reset_release;
    always @(posedge clk) begin
        if(sys_reset) begin
            phi2_q<=0; p2<=0; unmap_pending<=0; restart_pending<=0; restart_q<=0; hold_req<=0; rel_q<=0;
            armed<=0; cv<=0; req_s<=0; seen_s<=0; hi_s<=0; cyc<=0; nonsel<=0; boot_map<=1;
        end else begin
            phi2_q<=cpu_phi2; p2<=fall; rel_q<=cpu_reset_release;
            req_s<={req_s[0],!reset_req_n}; seen_s<={seen_s[0],low_seen}; hi_s<={hi_s[0],resb_sense};
            if(p2) hold_req<=req_s[1];
            // detection of an external RESB pulse is armed once RESB is seen high after the release
            if(!cpu_reset_release || ext_event) armed<=0;
            else if(hi_s[1] && !low_seen && seen_s==2'b00) armed<=1;   // also wait until the synchronised flag is clear
            restart_q<=new_req || ext_event || rel_fall;
            if(new_req || ext_event || rel_fall) restart_pending<=1;
            // BOOT_MAP: leave after the BRK vector (as before); back to 1 at the phase-2 edge after a restart
            if(fall && unmap_request) unmap_pending<=1;
            if(unmap_pending) begin boot_map<=0; unmap_pending<=0; end
            if(p2 && (restart_pending || new_req || req_s[1])) begin boot_map<=1; unmap_pending<=0; restart_pending<=0; end
            // CPU cycle bookkeeping for vector_ok: a cycle is valid if RESB was released when it began
            if(fall) cv<=cpu_reset_release;
            if(!cpu_reset_release) begin cyc<=0; nonsel<=0; end
            else if(rise && cv) begin
                if(cyc!=7'h7f) cyc<=cyc+1'b1;
                nonsel <= cpu_cs_n ? (nonsel==2'd3 ? 2'd3 : nonsel+1'b1) : 2'd0;
            end
        end
    end
    assign boot_reset = sys_reset || hold_req || restart_q;
    assign run_ok = !hold_req;
    assign vector_ok = {cyc < VECTOR_CYCLES, nonsel == 2'd3};
endmodule
