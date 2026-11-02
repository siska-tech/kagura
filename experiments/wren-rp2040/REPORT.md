# Wren feasibility report — 2026-11-02

**Follow-up:** [MEMORY_ANALYSIS.md](MEMORY_ANALYSIS.md) supersedes the original
32 KiB stack/96,064 B allocator candidate and initial coexistence estimates.
The stack reservation is now 48 KiB after ARM painting observes up to 39,940 B.
The 98,239 B figure is live Wren payload, not malloc footprint. A small GUI
needs 90,437 B payload with error/lifecycle checks and a 124,240 B simulated
newlib arena; its proposed guarded hardware profile uses a 132 KiB arena.
No positive SRAM-only RP2040 acceptance candidate fits. Hardware remains unrun.

## Evidence and decision

| Question | Finding |
|---|---|
| Can Wren run reliably on RP2040? | Not established. Host/sanitizer and ARM emulation pass; Pico hardware has not run. The current SRAM-only layout cannot fit all workloads with this allocator. |
| Real minimum memory? | ARM emulation: 74,908 B live after VM initialization; about 81 KB for the smallest complete workload, 98,239 B requested-live cap for all ten. Instrumentation and libc need more; see below. No actual RP2040 minimum is claimed. |
| Coexist with a C GUI? | Plausible with code in flash and an explicit budget, not demonstrated. Keeping code, GUI, VM and compilation stack all in SRAM is impractical in this build. |
| Suitable C FFI? | Slots, opaque handles and foreign methods are a small, workable interface. Reused compiled handles pass all tests. Production resource lifetime and OOM policy remain unsolved. |
| Meaningful advantage over MicroPython? | Smaller compiled runtime candidate and simple embedding are promising. No matched RP2040 speed or heap win is established. Existing MicroPython has a much broader development environment. |
| Does RP2350 help? | Yes, its 520 KiB SRAM adds 256 KiB over RP2040, substantially easing both SRAM-only testing and integrated heap/stack headroom. Rebuild and hardware measurements are still required. |

Recommendation: **continue as an experiment; do not replace MicroPython or start
Desktop integration yet**. The 0.4.0 GC defect and large compilation stack are
material findings, not reasons to hide unsuccessful budget tests.

Inspected refs: latest fetched `main` = `1dea60068039441831cbf2255fbb50676c0bc2db`;
C Desktop = `be344f5c742101f0cff170a29f63d09c0a17c441`. The pre-existing local
Stage 3A branch had commit `9552c975f143ce6b777043554776aa46b9ca701e` plus
uncommitted work; it was read without modification. This experiment branches
from main in a separate worktree.

## Measurement model

Wren is built unmodified from the pinned official commit, with NaN-tagged values,
computed-goto dispatch, and optional meta/random modules disabled. Host uses
GCC 15.2.0, `-O2`, x86-64 WSL2 Ubuntu/glibc 2.43 on Intel i7-1360P. Each workload
gets a new VM, compiles once, retains a receiver and `run()` call handle, runs two
warm-ups and eight measured calls, then releases handles and shuts down.
Each result checks the exact expected numeric answer. Timing loops print nothing.
Five independent VM runs per budget are recorded, not device performance.

The custom `reallocateFn` maintains a doubly linked allocation ledger. It reports
requested-live current/peak bytes, successful allocation/reallocation/free counts,
largest requested and largest successful allocation, and memory at initialization,
after compile-and-module-initialization, after final GC, and after shutdown.
`compiled` includes executing top-level module definitions; it is not a
compile-only heap measurement. `compile_us` likewise includes module execution.
Counts and whole-run peaks include core bootstrap; `run_allocs` and
`run_reallocs` cover only the eight measured calls. `run_us / 8` is mean time per
call; the table takes the median across five runs. Microsecond resolution makes
the hello timing approximate. The largest successful request is 8,192 B in these
workloads. All normal shutdowns and all OOM discards return ledger live bytes and
blocks to zero, with successful allocations equalling frees.

GC configuration is explicit: **initial threshold 16,384 B, minimum threshold
8,192 B, growth 25%**. These are collection triggers, not reserved or maximum
heaps. The allocator enforces the separately supplied budget on *all* VM requests,
including the VM structure and GC gray array. Wren's internal accounting is not
used as a physical-memory measurement. Explicit GC occurs after every call and
at shutdown; automatic GC remains enabled and its pauses are included in call
times. `explicit_gc_us/count` excludes automatic collections. No automatic-GC
count or pause distribution is claimed; these remain hardware acceptance work.

The ledger header is 32 B per live block on x86-64 and 16 B on ARM. `physical_peak`
is requested bytes plus those headers, **excluding** libc chunk metadata,
alignment slack, fragmentation, transient realloc copies, stdio, native stack
and static data. ARM newlib arena high-water is reported separately. Thus even
`physical_peak` is a lower bound on the actual malloc arena requirement.

Wren does not safely propagate allocator NULL: `wrenNewVM()` immediately uses the
result, and other allocation sites assume success. On budget/system malloc
failure this host `longjmp`s to the boundary, frees the entire ledger and never
touches that interrupted VM again. `OOM_DISCARDED` is **host containment**, not
Wren raising MemoryError or continuing that VM. All handles become invalid.
This is valid only for the experiment's single-threaded pure-C host with no
foreign objects, finalizers, external resources or reentrant calls. It is not a
production resource cleanup solution. Budget failures and actual malloc failures
are distinguished by `oom_kind`.

## PC results

The complete timing/allocation table is [results/host-table.md](results/host-table.md).
Raw phase metrics and counts are in `results/host-{32,64,96,128,160,192,256}k.txt`.
For example, the sprite workload paints all 256 cells four times and checks sum
1,920. Events construct and consume 64 three-field records, checking 2,592.
Fibers schedule four fibers for 16 yields each, checking 480. Foreign calls
perform 1,000 additions per call, 10,000 across warm-up plus timing.

| Budget (KiB = 1,024 B) | x86-64 outcome | ARM allocation-only emulation |
|---:|---|---|
| 32 | all OOM in VM initialization | all OOM in VM initialization |
| 64 | all OOM in VM initialization | all OOM in VM initialization |
| 96 | all OOM in VM initialization | all ten pass under requested-byte cap |
| 128 | hello, arithmetic, foreign pass; seven OOM | all ten pass |
| 160, 192, 256 | all ten pass | 160 and 256 tested, all pass |

Exact per-workload budget bisections are committed in `host-summary.json` and
`arm-emulated-summary.json`. x86-64 initialization uses 119,784 B; the smallest
tested workload peak is arithmetic at 128,731 B. Full-suite peak is 156,423 B
(152.76 KiB) requested, or 195,495 B including ledger headers. This is not an
RP2040 heap requirement. The 128 KiB partial-suite result must not be presented
as a full-suite pass.

UTF-8 `System.print` emits `こんにちは、神楽！` byte-exactly. The script counts
nine code points, and concatenating 128 `あ` characters checks 384 bytes.
This validates string storage, iteration and transport to the host write callback;
it does not validate fonts, display rendering, normalization, IME or graphemes.
Wren `Num` uses doubles, including the integer arithmetic test; integer values
are exact only within the double integer range. M0+ soft-double costs cannot be
inferred from these PC timings.

The foreign benchmark time includes the Wren loop, dispatch, slot reads and the
C addition. It is not isolated FFI latency and cannot be compared as such with
the Stage 3A loop-subtracted native-call measurements. C-to-Wren callbacks reuse
compiled handles. Separate repeated-script checks interpret 50 block-scoped
temporary allocations in the same module, collect after each, exercise compile
and runtime errors, and verify subsequent script success. Reusing module-scope
`var` declarations would be a redeclaration error, not a lifecycle test.

## ARM allocation emulation and SRAM-only constraint

`tools/build_arm_memory.sh` compiles the same VM/workloads for Cortex-M0+ Thumb-1
using Arm GNU 14.2.Rel1 and newlib. `qemu-arm` 10.2.1 runs that freestanding ELF
with a Linux process stack, raw output syscalls and an artificial 512 KiB malloc
arena. All times are deliberately zero. It models 32-bit structure sizes and
allocation behavior, **not Pico execution, peripherals, cycle costs or stack use**.
Reproduce with `QEMU=/path/to/qemu-arm bash tools/build_arm_memory.sh`, then
`python3 tools/arm_sweep.py`. This extra evidence is kept separate from PC timing
and from the entirely unperformed hardware run.

Initialization uses 74,908 B requested live (3,128 successful allocations over
bootstrap). Full-suite maximum requested-live is 98,239 B (strings); peak with
ledger headers is 116,391 B (repeat/GC). In the original 256 KiB suite-wide sweep,
newlib arena high-water was 130,720 B (including libc/stdio), exceeding live-byte
figures. Shutdown ledger bytes are zero; libc retains arena space and its stdio
allocation (1,032 B in this emulator). This is allocator retention, not a VM leak.
The corrected trimming model and fresh-process audit now measure 132,432 B for
the largest-workload arenas; see MEMORY_ANALYSIS.md for the exact decomposition.
Each workload gets its own VM, so these numbers do not promise that ten resident
applications can coexist. A budget exactly matching this small suite is not an
adequate production application allowance.

The original no_flash ELF had about 128 KB of loadable code/constants/data, plus
BSS and a 32 KiB stack. Its allocator range was 96,064 B (93.81 KiB). That is
less than the full-suite requested-live peak even before headers, newlib metadata
or fragmentation. **The current SRAM-only target is expected to report OOM,
not ten passes.** Running it cannot establish full runtime acceptance. A future
smaller SRAM image/allocator, or an approved different test platform, is needed
to close that gap; changing flash firmware is outside this experiment.

That stack reservation is now retired: ARM stack painting exceeds it, and the
current guarded builds require 48 KiB, leaving still less malloc space. See
[MEMORY_ANALYSIS.md](MEMORY_ANALYSIS.md), [pico/ACCEPTANCE.md](pico/ACCEPTANCE.md)
and `results/memory-audit/pico-*-image.txt` for current layouts/gates.
`results/rp2040-image.txt` is the historical candidate. No actual RP2040 heap,
stack peak, runtime timing, MicroPython restoration or flash-hash result exists.

## Coexistence estimate (code in flash, not the SRAM-only test image)

An integrated firmware would execute most runtime and GUI code from flash, retain
only selected routines/constants in SRAM, and share system/USB code. Adding the
standalone Desktop ELF size to the standalone Wren ELF size is invalid.

| SRAM component | Conservative allowance, KiB | Basis |
|---|---:|---|
| Existing retained C GUI state | 45 | 45,960 B ARM ABI; framebuffer and staging included |
| Wren/newlib arena, including all allocator overhead | 144 | 132 KiB proposed GUI acceptance arena plus integration cushion |
| System/USB/static runtime state | 16 | Outside the Wren arena, estimate |
| Native compiler/IRQ stack and guard | 48 | Corrected fixed-suite reservation; arbitrary source nesting remains unbounded |
| Additional transport buffers | 4 | Beyond existing retained GUI state, estimate |
| RAM-resident code/constants | 16 | Most code in flash; actual integrated map required |
| Unassigned recovery margin | 8 | Outside the tested Wren arena |
| **Total** | **281** | Conservative scenario, not measured integrated firmware |

RP2040 has 264 KiB: this scenario has a 17 KiB deficit before additional font
caches or larger applications. Leaner allocations may fit, but a conservative
coexistence claim is not established. Script-owned pixel lists cost 8 B per value plus array
overhead); a future native packed sprite buffer would avoid duplicating GUI
pixels, but no such binding is implemented here.

RP2350 has 520 KiB, giving approximately 239 KiB spare in this scenario.
Different M33 code sizes, SDK, stacks and workload behavior require a real
build/run. Its single-precision FPU does not directly make Wren double arithmetic
hardware-native. Larger SRAM is the strongest established benefit here.

## Comparison with MicroPython

Existing local Stage 3A host results were found in `build/c-gem-mp`, copied into
`results/reference-stage3a-host-*.md` and marked provisional: their source had
uncommitted changes. They are **MicroPython Unix host results**, not RP2040.
They report 32,416 B for scene objects including a 32,000 B mirror bytearray,
46,552 B native state on x86-64, and a configured 2,072,832 B GC arena. That arena
size is not a minimum requirement. The local Stage 3A RP2 ELF was inspected only
for static footprint; it was never loaded by this experiment.

| Aspect | Wren evidence | MicroPython evidence / qualification |
|---|---|---|
| Runtime/code footprint | Final no_flash load image ~128 KB including USB, C host, test strings, math/libc | Local Stage 3A RP2 build: `size` text 463,560 B, BSS 51,088 B; includes desktop, firmware modules and SDK. Not an isolated VM comparison |
| Static SRAM | Experiment BSS ~4.2 KB + initialized data ~3.3 KB; VM core is dynamically allocated | Stage 3A BSS 51,088 B includes native GUI state; RAM before GC heap ends at `0x2000daa8`. This is not MicroPython-only overhead |
| Minimum viable heap | ARM emulated full suite 98,239 requested B; runtime hardware unknown | Not established by Stage 3A; its Unix arena is a configuration, RP2 GC space is a linker allowance |
| Peak application memory | ARM full suite peak above core live state ~23 KB; headers and allocator overhead separate | Stage 3A scene allocation 32,416 B includes mirror. Different workload/representation; no direct ratio |
| Script speed | PC table only; soft doubles on M0+ require hardware timing | Stage 3A host renders/updates native GUI; different workloads, so no speedup claim |
| C calls | 1,000 foreign calls per timed method, correct results; loop-inclusive | Stage 3A reports 15 ns for `w.is_open()` and 52 ns for unchanged color setter, host, loop-subtracted; cannot compare to Wren loop-inclusive timing |
| GC | Precise non-moving mark/sweep; explicit and automatic collections tested; OOM needs host boundary | Stage 3A host explicit GC 12 us with scene, 15 us with another 38,400 B live buffer. Different live graph and runtime; device latency unknown here |
| UTF-8 | Byte-exact Japanese output, code point count and byte count tested | Existing KAGURA Japanese rendering support is already present; Wren output does not replace it |
| Development | Small C API, opaque handles, errors with module/line/trace, fibers for cooperative events | Established REPL, mpremote, modules, drivers and broader tooling; no Wren REPL/debugger/module ecosystem is added here |
| Exhaustion | VM discarded, including all handles; no native recoverable OOM | MicroPython ordinarily raises MemoryError; actual binding resource behavior still needs testing |

Stage 3A RP2 ELF exposes GC heap `0x2000daa8–0x20040000`; see the recorded
reference inspection for size/hash. It is a compile-time capacity, not a measured
minimum or high-water. No new MicroPython benchmark or device claim is invented.

Sources: pinned Wren `src/include/wren.h`, `src/vm/wren_vm.c`,
`src/vm/wren_compiler.c`, `src/vm/wren_value.h`; official
[VM configuration](https://wren.io/embedding/configuring-the-vm.html),
[slots and handles](https://wren.io/embedding/slots-and-handles.html), and
[RP2350 specifications](https://www.raspberrypi.com/products/rp2350/).
