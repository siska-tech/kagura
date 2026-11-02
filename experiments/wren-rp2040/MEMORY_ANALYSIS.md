# Memory discrepancy audit (PR #69 follow-up)

**No hardware accessed. PR remains Draft. The old 32 KiB-stack candidate is
retired. A positive SRAM-only RP2040 VM/GUI acceptance test is not practical
with the current official VM, ledger/newlib allocator and measured image.**
An SRAM-only boot/OOM/recovery experiment is possible, but it would not establish
that Wren can run the GUI workload. This audit does not request hardware approval.

All results below are ARMv6-M CPU emulation with Arm GNU 14.2.Rel1/newlib,
not RP2040 runtime measurements. Original PC correctness tests, all ten stress
workloads, fixed embedded GC settings and whole-VM OOM containment are retained.
One additional GUI model and stricter allocator/recovery checks were added.

## 1. What exactly is 98,239 bytes?

It is **peak simultaneously live bytes requested through Wren's allocator**,
summed over all outstanding allocations in one VM, including core objects,
compiled code, application objects, VM/fiber/value stacks and GC bookkeeping.
Realloc replaces the old requested size with the new size; free subtracts it.
The peak occurs *during execution of the `strings` workload*. Automatic GC is
enabled; it can run within that execution phase.

It is not a single allocation, cumulative allocation, reserved arena or total
physical SRAM requirement. For that same fresh-process `strings` run:

| Metric | Bytes | Meaning |
|---|---:|---|
| Largest successful single allocator request | 8,192 | Largest individual request over the lifecycle, in initialization |
| Peak requested-live bytes | 98,239 | Maximum concurrent requested payload |
| Cumulative successful requested bytes | 480,242 | Sum of new sizes of successful malloc/realloc requests; allocation traffic, not a heap size |
| Cumulative positive growth | 419,938 | Sum of increases, including new allocations; also not a heap size |
| Ledger footprint at the requested-live peak | 115,663 | 98,239 + 1,089 live blocks × 16 B headers |
| Maximum ledger footprint anywhere in this workload | 115,776 | Occurs at a different instant; do not add independent maxima |
| malloc used bytes at the requested-live peak | 126,048 | Chunk sizes plus already-initialized stdio |
| newlib arena high-water | 132,432 | Capacity actually obtained from `_sbrk`, including free chunks/padding |

The largest **ledger** peak across the full original suite is 116,391 B in
`repeat_gc`, not `strings`. Both workloads reach a 132,432 B newlib arena in
these fresh-process runs. Different maxima describe different things.

At the precise `strings` requested-live peak, the decomposition is additive:

| Component at that instant | Bytes |
|---|---:|
| Wren requested live payload | 98,239 |
| Experiment allocation ledger headers | 17,424 |
| Usable-chunk rounding/slack | 4,997 |
| newlib allocated-chunk bookkeeping | 4,356 |
| libc stdio allocation already present before the VM | 1,032 |
| Free/top chunks within the obtained arena | 6,384 |
| **Arena obtained** | **132,432** |

`malloc_usable_size()` is summed over owned blocks; `mallinfo()` independently
reports arena, allocated and free space after each allocator operation. Transient
old+new storage internal to realloc is not observed as a simultaneous *used*
snapshot, but its capacity demand is reflected in arena high-water and the
bounded-arena success/failure tests. This is why the arena test is essential.

## 2. Per-workload phases

Each row below starts a fresh process/allocator with the same binary, a 256 KiB
requested-byte cap and a 512 KiB maximum simulated arena. There are two warm-ups
and eight compiled-handle calls, explicit GC after each call, then final GC and
VM shutdown. No extra error/recompile checks are mixed into these rows.

`compile` is `wrenInterpret()` compilation **plus module initialization**, the
public API operation used by this host. `execution peak` includes automatic GC;
the GC column is the peak during **explicit** host collections only. The final
GC current value includes retained module definitions; it is not zero until VM
shutdown. Native compiler stack is separate from the allocator.

| Workload | Init live | Compile/module peak | Execution peak | Explicit GC peak | After final GC | Shutdown | Arena high-water |
|---|---:|---:|---:|---:|---:|---:|---:|
| hello / Japanese | 74,908 | 80,276 | 80,996 | 80,996 | 78,777 | 0 | 111,952 |
| arithmetic | 74,908 | 80,191 | 80,599 | 80,599 | 78,865 | 0 | 111,952 |
| strings | 74,908 | 80,282 | **98,239** | 88,429 | 78,974 | 0 | 132,432 |
| lists/maps | 74,908 | 80,869 | 84,973 | 83,949 | 79,265 | 0 | 116,048 |
| objects/methods | 74,908 | 82,890 | 87,379 | 87,379 | 81,029 | 0 | 124,240 |
| fibers | 74,908 | 81,734 | 83,230 | 83,230 | 79,695 | 0 | 116,048 |
| foreign calls | 74,908 | 81,436 | 81,844 | 81,844 | 79,628 | 0 | 111,952 |
| 16×16 sprite | 74,908 | 83,350 | 86,930 | 86,930 | 81,252 | 0 | 120,144 |
| FIFO events | 74,908 | 81,967 | 86,559 | 86,055 | 80,011 | 0 | 120,144 |
| repeated allocation/GC | 74,908 | 80,331 | 97,911 | 88,671 | 78,945 | 0 | 132,432 |
| **small GUI model** | 74,908 | 85,822 | 85,881 | 85,881 | 84,237 | 0 | 120,144 |

Raw `RESULT`, `AUDIT` and `PHASE` rows in `results/memory-audit/arm-*.txt` include
phase current/peak payload and ledger sizes, counts, cumulative requests, largest
requests, malloc used/free/top-chunk sizes, and native usable bytes. Handle
creation has its own phase. Repeated visits to a phase accumulate maxima/counts;
`end` is its last observation, including resumption after GC. `AUDIT.executed`
separately captures the final callback return before explicit GC.

All successful shutdowns and OOM discards have zero requested bytes, zero ledger
blocks and zero owned usable bytes, with successful allocations equalling frees.
libc retains its 1,032 B stdio allocation. Small arenas can remain reserved after
shutdown; larger free top chunks can be trimmed. Neither is a Wren leak.

## 3. Smallest GUI-oriented acceptance model and practical budget

`workloads/small_gui.wren` is a small persistent application model, not Desktop
bindings. It contains one `App` object, a Japanese title, one four-number window
rectangle and a four-entry event list. Each compiled `Bench.run()` calls
`App.step()`, processes four events through the real C foreign `Native.add`,
updates the model's x coordinate, verifies rectangle state, counts nine Japanese
code points and returns **173**. It allocates no framebuffer, sprite list, fonts
or filesystem objects; those belong to the native GUI in the intended split.

The exact smallest **proposed positive acceptance profile** is:

1. Deliberately fail a 4 KiB requested-byte VM budget; require whole-VM cleanup.
2. Create a fresh VM with a **96 KiB requested-live cap and a separately bounded
   132 KiB malloc arena**. Compile the GUI model once; retain receiver/method
   handles; execute two warm-ups and eight callbacks, checking 173 every time.
   Require 40 C foreign calls per VM and byte-exact Japanese output.
3. Keep the existing 50 repeated block-scoped interpretations/GC checks, expected
   compile/runtime errors and subsequent successful execution. Release all
   handles, final GC, shutdown; require zero ledger/owned usable bytes.
4. Repeat step 2–3 for **20 VMs**: 200 callbacks, 800 C foreign calls, 1,000
   repeated interpretations. Measure native stack and malloc high-water; require
   at least 4 KiB arena headroom and 8 KiB native-stack headroom, no unexpected
   OOM/guard corruption and all existing flash/recovery gates before acceptance.

This profile does not require the stress string/fiber/sprite workload peaks to
fit. Those tests remain present and continue to run on the host/emulator.
It is the smallest application *profile proposed for acceptance*, not a proof
that this script is the globally smallest possible Wren GUI program.
The host/ARM runner can select it by name; the current Pico entry point still
runs the full original suite and is an OOM-only candidate. A future positive
candidate must wire this profile into its entry point and revalidate that exact
binary after sufficient memory becomes available.

Exact bisections for this fixed emulated binary/layout:

| Profile | Minimum requested-live cap | Minimum real arena bound |
|---|---:|---:|
| GUI model, one lifecycle, ordinary callback/GC checks | 85,881 B | 120,144 B |
| GUI model, error/recompile checks, 20 lifecycles | 90,437 B | 124,240 B |

The minimum practical **tested emulator** choice is 96 KiB requested + 128 KiB
arena, not a 90,437 B arena. The observed checked arena leaves 6,832 B under
128 KiB. Arena minima depend on `_sbrk` start alignment and newlib page growth;
allowing a full 4,095 B alignment difference leaves only about 2.7 KiB. Therefore
the **proposed hardware profile** reserves **96 KiB requested + 132 KiB physical
arena + 48 KiB native stack**. That leaves 6,833 B after the observed arena and
worst-case alignment adjustment, of which 4,096 B is reserved for recovery. The actual
linked/runtime candidate must still demonstrate the margin; these calculations
are not device proof. Do not lower correctness/error checks or stack to fit.

## 4. Allocator, fragmentation and recovery

Even initialization explains why a 96,064 B malloc *region* fails:
74,908 B requested + 15,504 B ledger headers + 4,576 B usable rounding + 3,876 B
chunk bookkeeping + 1,032 B stdio = **99,896 B allocated**, with another 7,960 B
free/top space in the **107,856 B** obtained arena. Thus it cannot initialize
under either 96,064 B or the old hypothetical 104,256 B expansion.

In the bounded 128 KiB arena, `strings` fails a **387 B payload request** after
1,367 moved reallocations over bootstrap/compilation/execution. It then has
2,696 B free in existing chunks, but only 24 B in the top chunk. The arena has
grown to 128,336 B; only 2,736 B remain below its bound, while newlib requests
another 4,096 B from `_sbrk`. This is fragmentation/growth granularity, not a
387 B minimum-heap claim. `keepcost` measures the top chunk, **not** the largest
free block; this audit does not invent a largest-free-block statistic.

The whole interrupted VM is discarded without invoking Wren again. The ledger
returns to zero, native usable ownership returns to zero and the freed arena
coalesces to 127,304 B free (stdio remains). **100 checked GUI lifecycles then
pass in that same unchanged 128 KiB arena**, no reset or arena expansion. A
separate requested-budget failure during GUI compilation also cleans up and
permits 100 checked GUI lifecycles. A third run does 100 successful checked GUI
lifecycles with no injected failure. All logs are retained.

The emulator's `_sbrk` now supports negative increments like pinned Pico SDK
`pico_clib_interface/newlib_interface.c`; the original emulator rejected trimming.
Arena high-water and current program break are now distinct. These improvements
and fresh-process runs explain small changes from the original suite-wide
allocator figures; the 98,239 B requested peak is unchanged.

Recovery uses a static context/jump buffer and walks/frees existing blocks; it
does not allocate a replacement VM until discard completes. Pico's error/status
output uses SDK printf, with no application resource/finalizer to unwind. This
remains a single-threaded experimental containment policy, not safe general
cleanup for resource-owning GUI bindings. The future budget below also keeps
unassigned recovery/integration margin outside the tested arena.

## 5. Native stack correction

ARM stack painting from the original entry SP, including the emulator entry
frame, observes **33,840 B** for the GUI model and most simple workloads and
**39,940 B** for fibers. It is a conservative painted high-water observation for
this build, not an exhaustive bound or a hardware measurement. The init-time
core library compilation contributes substantially even for Hello World.

The individual upstream frames (12,568 B method, 6,392 B methodCall, 6,360 B
wrenCompile) did not establish the nesting depth. The previous 32 KiB reservation
was therefore inadequate and must not be reused. Current CMake requires at least
**48 KiB**, with the MPU bottom guard preserved. The full suite's emulated peak
leaves 9,212 B for SDK/IRQ differences and guard/headroom. Actual device peaks
would still need a separately approved, otherwise eligible candidate. Arbitrary
source nesting is not bounded, so this is for the fixed suite only.

## 6. Can the malloc region expand safely?

Blindly moving `__HeapLimit` upward would overlap the native stack/MPU guard.
The old 96,064 B region ended at `0x20038000`, the old 32 KiB stack bottom.
Keeping that already-inadequate stack size and relocating its top through both
scratch banks could recover only **8,192 B**, to 104,256 B for the *old* image.
That remains below the measured initializer's 107,856 B arena, before any app.

Three current images were built and verified offline, with all original stress
workloads retained, no upstream source patches and no weakening of OOM:

| Image | Requested stack | BSS end / malloc start | malloc limit | malloc capacity |
|---|---:|---|---|---:|
| Current default | 49,152 B | `0x200211b0` | `0x20034000` | 77,392 B |
| Scratch-expanded | 49,152 B | `0x200211b0` | `0x20036000` | **85,584 B** |
| Wren-only LTO | 49,152 B | `0x20021570` | `0x20034000` | 76,432 B |

The default load image is 130,732 B; BSS is 4,864 B. These include the instrumented
host/USB/system state. The SDK minimum `.heap` section is inside malloc capacity,
not an additional requirement. LTO enlarged the load image to 131,692 B rather
than producing a useful saving. SDK stdio/malloc wrapper sources stay outside
LTO; whole-SDK LTO was rejected after wrapper-symbol internalization link errors.

In expanded mode core 0 stack spans `0x20036000–0x20042000`, with its bottom MPU
guard; malloc stops exactly at `0x20036000`. All addresses remain inside physical
SRAM. Linker assertions require `.scratch_x`, `.scratch_y` data and the core 1
stack section to be empty. No core 1 launch or FIFO-handshake code is linked.
The official [RP2040 boot ROM holding-pen source](https://github.com/raspberrypi/pico-bootrom-rp2040/blob/master/bootrom/bootrom_rt0.S)
supports treating core 1 as parked until explicitly launched; this reasoning is
conditional on that normal boot state, not permission to reuse scratch banks in
an arbitrary multicore firmware.

ELF/UF2 byte checks and eight malformed-image rejection tests pass for each
variant; exact hashes, PT_LOAD ranges, symbols and sections are recorded under
`results/memory-audit/pico-*`. The expanded case is address-safe under these
conditions, but its 85,584 B allocator cannot fit even the GUI's **85,881 B raw
payload peak**, much less ledger, newlib overhead or recovery margin. A 40 KiB
stack would recover only another 8 KiB and still fail newlib initialization;
shrinking stacks does not solve this experiment.

**Conclusion:** there is no safe positive SRAM-only RP2040 acceptance candidate
here. Boot/OOM/watchdog recovery testing is technically possible with the 48 KiB
stack, but does not meet the proposed positive GUI acceptance workload. Further
image/allocator engineering or a larger-SRAM test platform is required before
requesting that hardware acceptance. Dropping the source compiler cannot be
assumed: official Wren compiles its core source during VM initialization.

## 7. Conservative Wren + existing C Desktop budget

This is a **flash-resident integrated firmware estimate**, not the sum of two
standalone SRAM executables. Exact ARM ABI sizing against the existing headers
gives `sizeof(kd_desktop) = 34,160 B`, `sizeof(kdm) = 45,960 B`. The larger retained
state includes the 32,000 B framebuffer, records, text/sprite/event pools and
1,280 B TILE4 staging. Do not add those buffers again. The previously quoted
34,792 B was not the isolated structure size. No existing Desktop file changed.

| SRAM component | Conservative allowance (KiB) | Basis |
|---|---:|---|
| Existing retained C Desktop state | 45 | 45,960 B measured ARM ABI, rounded up |
| Wren/newlib arena | 144 | 132 KiB proposed acceptance arena plus 12 KiB integration cushion; includes VM core, app, ledger, libc metadata and fragmentation |
| Core 0 native stack/guard/IRQ headroom | 48 | Current fixed-suite reservation; not an arbitrary-program bound |
| USB/system/static state outside the arena | 16 | Current static state plus system/buffer reserve; no duplicate VM core |
| Additional transport buffers outside retained state | 4 | Estimate; existing staging already counted in Desktop state |
| RAM-resident functions/constants | 16 | Conservative estimate; most code/fonts assumed in flash, actual linked map needed |
| Unassigned failure/recovery margin | 8 | Additional reserve, not double-counted as Wren payload |
| **Total** | **281** | Single-core, no second framebuffer |

| Device | SRAM | Remainder under this budget | Assessment |
|---|---:|---:|---|
| RP2040 | 264 KiB | **17 KiB deficit** | No conservative coexistence claim; would need measured reductions |
| RP2350 | 520 KiB | **239 KiB spare** | Materially better memory viability; M33 build/runtime still unmeasured |

Using only the tested 128 KiB arena reduces the total to 265 KiB, still 1 KiB
over RP2040 before additional applications or font caches. Smaller system/RAM-code
allowances or a better allocator could yield a lean fit, but none is measured
here; it would not be a conservative approval basis. A future active core 1 needs
its own stack/buffers in addition. No Japanese IME or font-cache implementation
is included, and no second 32 KiB framebuffer/mirror is assumed.

For an entirely SRAM-only image, the current Wren host alone needs about
132.4 KiB image+BSS + 132 KiB proposed arena + 48 KiB native stack, roughly
**312 KiB** before adding the GUI (even the tested 128 KiB arena totals 308 KiB).
The existing GUI's code/state would add more; an RP2350
could plausibly host such an experiment, but no RP2350 binary or hardware result
is claimed. Code-resident-in-flash and code-resident-in-SRAM estimates must not
be interchanged.

## Reproduction and scope of evidence

With the pinned compiler on PATH and `QEMU=/path/to/qemu-arm`:

```sh
python3 tools/gen_workloads.py
bash tools/build_arm_memory.sh
python3 tools/memory_audit.py
# Proposed profile in CPU emulation only:
"$QEMU" build-arm-memory/wren_memory.elf 98304 checks small_gui 135168 20
# Current guarded image; use the pinned SDK and picotool as in pico/ACCEPTANCE.md
cmake -S pico -B build-pico-audit -DCMAKE_BUILD_TYPE=Release -Dpicotool_DIR=...
cmake --build build-pico-audit -j4
# Separate address-expansion and Wren-only LTO experiments:
cmake -S pico -B build-pico-audit-expanded -DWREN_USE_ALL_SRAM=ON -Dpicotool_DIR=...
cmake -S pico -B build-pico-lto -DWREN_LTO=ON -Dpicotool_DIR=...
```

`tools/memory_audit.py` checks phase results, exact bisections, real bounded-arena
failures, 100-cycle recovery and zero cleanup balances. The original host suite
plus the new 20-lifecycle GUI test pass in Release and ASan/UBSan. Detailed
allocator snapshots are for memory investigation, not new timing benchmarks.
The original benchmark logs remain historical results of their original binary.
