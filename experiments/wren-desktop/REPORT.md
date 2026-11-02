# Integration feasibility result

The minimal Wren-powered desktop fits a flash-resident RP2040 link while preserving the original framebuffer, 48 KiB stack, allocator safety and 8 KiB recovery reserve. Host and ARM CPU-emulated correctness pass. This establishes a plausible minimal integration, **not physical RP2040/FPGA reliability or performance**. Read-only hardware preflight is recorded separately; no Wren image has yet been flashed. PR #68 and PR #69 remain independent Draft experiments.

The hardware validation preflight is currently blocked before flashing; see [HARDWARE.md](HARDWARE.md). The linked figures below include the measurement harness added after the initial review. The foreign API is unchanged.

## Actual linked SRAM, not an executable-size estimate

The final ELF SHA-256 is `1b90d5d63f8775e49724651bfffa6b906fcb5bd8d39d075af77f0ace8611bb39`. Detailed evidence: [linker map](results/flash-linker.map), [ELF layout](results/flash-layout.json), [sections/program headers](results/flash-readelf.txt), [symbols](results/flash-symbols.txt).

| Region | Address range (end exclusive) | Bytes |
|---|---|---:|
| RAM vector table | 0x20000000–0x200000c0 | 192 |
| .data / RAM functions | 0x200000c0–0x20001900 | 6,208 |
| .bss | 0x20001900–0x2000b1f4 | 39,156 |
| Bounded native malloc arena | 0x2000b1f4–0x2002c1f4 | 135,168 |
| Unassigned main SRAM | 0x2002c1f4–0x20032000 | 24,076 |
| Recovery reserve, canary protected | 0x20032000–0x20034000 | 8,192 |
| Core 0 stack, including MPU guard | 0x20034000–0x20040000 | 49,152 |
| Unused scratch X/Y | 0x20040000–0x20042000 | 8,192 |
| **Total physical SRAM** | | **270,336** |

Static SRAM is **45,556 B**. Its `DesktopState` is 34,284 B, including the **34,160-byte `kd_desktop` and its 32,000-byte framebuffer**, snapshot and damage/window structures. The Wren runtime context adds 280 B; the remaining 10,992 B cover SDK, USB, HAL, C library state, RAM code and alignment, all itemized in the map. There is no second framebuffer, dynamic GUI object allocation, Stage 3A binding record pool, or standalone tile staging allocation. The linker's .heap 2 KiB marker lies inside the bounded 132 KiB arena and must not be counted twice.

Total reserved is **238,068 B (232.49 KiB)**; unassigned is **32,268 B (31.51 KiB)**. The latter comprises two separate areas; it is not a contiguous 31.51 KiB block. It is 500 B below 32 KiB and this experiment does not shrink any reservation to claim otherwise. Heap/stack/recovery boundaries and unused core-1/scratch sections are linker assertions, with the SDK sbrk bound at the arena end.

The preceding native-integration estimate was **241,284 B**. The actual reservation is **3,216 B lower**. This comparison uses the same flash-resident minimal native model; a generic full binding estimate is not interchangeable with this four-method prototype. In particular, this experiment does not import the Stage 3A per-object binding pools, additional framebuffer or standalone SRAM executable image. It does not prove a full desktop application suite fits.

File-backed load segments have flash physical addresses. Flash-resident text/rodata/boot occupies 146,584 B plus 6,208 B initialized RAM image = **152,792 B**. Entry is 0x100001e9. No file-backed SRAM execution image, flash erase/program symbols or UF2 are present. This is intentionally a different deployment model from PR #69's SRAM-only VM target.

## Measured allocator and stack requirements

Measurements below are **Cortex-M0+ code under qemu-arm**, linked against the same Arm newlib, not physical Pico results. [Raw runs](results/arm-normal.txt), [summary](results/arm-summary.json) and [recovery run](results/arm-malloc-recovery.txt) distinguish requested payload from allocator occupancy. Pico USB/interrupt allocation patterns remain unmeasured.

| Metric | Bytes |
|---|---:|
| VM initialization live / peak | 74,908 |
| Post application compilation live | 84,895 |
| Compilation peak | 85,213 |
| Post-GC live (last sampled collection) | 88,666 |
| Peak requested live payload, including error/recompile checks | **91,970** |
| Peak payload + 16-byte allocation ledger headers | 111,378 |
| Peak newlib allocated occupancy | 122,752 |
| Peak arena break / practical backing used | **126,032** |
| Largest successful single payload request | 8,192 |
| Wren payload cap in firmware | 98,304 |
| Native backing cap in firmware | 135,168 |
| Shutdown VM payload / blocks | **0 / 0** |

The 91,970 B peak is live payload, not cumulative allocation or a single request. The backing arena includes headers, newlib metadata, rounding and fragmented free space. It leaves 9,136 B within the 132 KiB cap in the emulated run. A persistent 1,032-byte newlib stdio allocation is outside the Wren ledger and is not a VM leak. Payload cap slack is 6,334 B. Wren GC thresholds are explicitly 16 KiB initial, 8 KiB minimum and 25% growth; these thresholds do not describe the actual arena capacity.

Bisection for this fixed binary/workload found 91,970 B payload and 126,032 B physical backing as minima. Neither is proposed as a safe deployment limit. 32/64 KiB payload fail cleanly; a 96,064-byte backing region and 120 KiB backing are insufficient. 96 KiB payload with 132 KiB backing passes. Recovery tests force both payload-limit and actual native malloc failure with a live native window, verify ledger balance and owner cleanup, then run 20 fresh VMs with ten compiled callbacks apiece in the same arena. Repeated success is useful fragmentation evidence, not a universal fragmentation bound.

Stack painting reports a **33,552 B upper bound** in the CPU-emulated harness, including its call path. [Compiler frames](results/stack-frames.txt) are per-function evidence, not a whole-call-chain bound. The 48 KiB reservation remains unchanged, leaving about 15 KiB relative to this emulated observation; actual USB IRQ/driver/libc stack usage must be measured on approved hardware. The independent 8 KiB recovery region is reserved even though the current recovery path does not allocate from it.

## Correctness and recovery evidence

* Release host: **18/18** CTest cases pass, including unchanged native correctness/mutation/reference tests.
* ASan/UBSan host: **18/18** pass, leak detection enabled.
* Original Wren host baseline: **1/1** passes, unchanged.
* ARM CPU-emulated integration suite passes: direct-sink bytes match the retained framebuffer for every observed tile; native C and Wren sequences have identical frame CRCs (seven frames normal, eight with overlap/reveal, including final owner cleanup; final CRC `be72ff88`). There is only one desktop instance, reused sequentially for reference and script runs.
* Overlap/reveal, negative clipping, unchanged-overdraw damage suppression and invalid rectangle rejection pass. Faults at ABI preflight, commit, write, DONE read, fence and error acknowledgement are tested. Failed acknowledgements retain dirtiness and disable blind retries; explicit reinitialization restores service.
* Reentrant mutation during export is rejected. Snapshot sharing is synchronous and non-reentrant, with no DMA or second-core access. Rendering ends before export uses the snapshot; initialization uses it before rendering. No storage is shared across concurrent lifetimes.
* Initialization/compilation/live-owner and sampled allocator-call failures clean up; compiled method handles are reused, syntax/runtime/foreign-argument errors recover, repeated interpretation and GC run without losing ownership. Each checked ten-callback run reports 161 foreign calls, 61 collections and ten completed four-event workloads. Japanese output is checked exactly once per VM.

See committed `results/*tests.txt` and `arm-correctness.txt`. No baseline stress workload or OOM handling was weakened to obtain these results.

## Decision and next boundary

The smallest useful acceptance application is exactly the committed `src/app.wren`: one native window titled `Wren Window`, one retained 48×24 rectangle, four deterministic native events that update position/color, and acknowledged presentation after each change. The VM compiles once and C calls `App.run()` through retained handles. Firmware repeats it twenty times, exercises error/GC checks, releases the window and reports allocator/stack/recovery-canary results. Native test-only cover/reveal is validated on host and ARM emulation; it does not add a second window to the firmware acceptance workload.

RP2040 viability is realistically plausible for this minimal flash-resident application. It still requires approved physical verification of USB/interrupt stack use, transport acknowledgements, watchdog behavior and allocator headroom before any reliability claim. The 31.51 KiB free space is finite growth capacity, not permission to add arbitrary GUI/application state. RP2350 has more SRAM, but this RP2040 binary/layout is not an RP2350 build and no RP2350 measurement is claimed.

No Wren physical execution, flash write, firmware replacement or PR merge has occurred. Flash-resident execution is now authorized, conditional on passing the recovery prerequisites in HARDWARE.md; a watchdog reset alone cannot restore the previous flash image.
