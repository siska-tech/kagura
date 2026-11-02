# RP2040 hardware validation — 2026-11-03

**The minimal runtime, memory, framebuffer CRC and OOM acceptance run passed on Pico RP2040 + Tang Nano 9K. Original MicroPython flash was restored and verified by complete readback.** HDMI shows the expected window/title/rectangle and all four updates, with a remaining colour-classification caveat described below. This is a bounded feasibility test, not a long-duration reliability qualification. PRs #68, #69 and #70 remain Draft and unmerged.

## Exact inputs and hardware

| Item | Revision / setting |
|---|---|
| Successful firmware source | **0aa0974938a150d84bccf98dae7482977f17926c** |
| ELF SHA-256 | **c35cd4a58c75907215b183616516eb16bd0cd89e74080aa59a0be4977123bd2b** |
| Failed initial firmware source | fdd45fbfc31453032d22930e3dcde2ea79c42a25 |
| Initial ELF SHA-256 | 1b90d5d63f8775e49724651bfffa6b906fcb5bd8d39d075af77f0ace8611bb39 |
| Native Desktop input / Wren experiment input | PR #68 be344f5c742101f0cff170a29f63d09c0a17c441 / PR #69 d03912b4339495379302b286383eb40cf8a6d53e |
| Official Wren | 99d2f0b8fc2686134b32b18166e037639f7e9f2c, MIT |
| Pico SDK / TinyUSB | 2.2.0 a1438dff1d38bd9c65dbd693f0e5db4b9ae91779 / 86ad6e56c1700e85f1c5678607a762cfe3aa2f47 |
| Compiler / programmer | Arm GCC 14.2.1 / Windows picotool 2.3.1 |
| RP2040 | Raspberry Pi Pico, silicon **B2**, 2 MiB flash, **125 MHz** |
| FPGA | Existing Tang Nano 9K; ID **4b39**, ABI **0.6**, CAPS **0x5b**, 240 lines, 1,200 patterns, ERROR_CODE zero |
| External QSPI | **5 MHz**, four lanes; GP2–5 IO0–3, GP6 SCK, GP7 CS, GP8 BUSY, GP9 READY, GP10 IRQ |
| HDMI capture | UGREEN 15390, 1280×960 YUYV 60 fps; 4×4 capture pixels per logical pixel |

The user confirmed unchanged wiring/power, HDMI connection and physical BOOTSEL/USB recovery access. The FPGA's exact loaded bitstream hash is not exposed through this ABI and was not independently established. ABI/CAPS were measured; no invented bitstream revision is claimed. No FPGA firmware or unrelated storage was modified.

PR #70 originally reviewed at a86d735a22b95b94b184b79fe5fb1da7ca8a79d5 had ELF hash 91d63f88…69e4d81. Measurement instrumentation and the diagnosed SDK allocation fix are separate commits above. Later evidence/documentation commits do not change the tested firmware sources.

## Backup, write boundaries and verified restoration

Before programming, a fresh full 2,097,152-byte backup was read through MicroPython and checked against device hashes before/after and an independent file reread. A control reboot preserved that hash and started a healthy KAGURA console. Windows initially lacked the BOOTSEL vendor driver; **no flash write occurred while that prerequisite failed**. After the user installed WinUSB on RP2 Boot Interface 1, a complete ROM readback matched the backup, followed by another verified MicroPython boot/hash. [Successful recovery preflight](results/hardware/20261103-preflight.txt).

The original backup remains private at the parent workspace's:
`build/wren-desktop-hardware/flash-backup-20261102T142039Z/flash-2MiB.bin`.

Original and final complete-flash SHA-256:
**d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b**.

Known-good program-only MicroPython UF2:
`build/micropython-src/ports/rp2/build-KAGURA_PICO_PINNED/firmware.uf2`,
SHA-256 **9ebfa459351e7e402d7c5690a0ddfc405b91d65093162586e89198733d03f95c**.
All 1,667 payload blocks match the backup through offset 0x68300. The complete backup, including the filesystem, remains the restoration authority.

Both tests programmed/restored only **0x10000000–0x10026000** (155,648 bytes, end exclusive). The host generated this sector-aligned prefix from ELF physical load segments, checked the exact ELF hash and linker bounds, programmed without executing, then read **all 2 MiB** before boot. Bytes beyond the prefix were required to remain identical to the backup. No all-flash erase was used.

| Complete-flash checkpoint | SHA-256 |
|---|---|
| Original / preflight / before both writes | d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b |
| First measurement image, verified before execution | 56bbdb5f4e4f66e0dd174ea62d185603960d0406faae25cb3ea0d329c2a76924 |
| Corrected image, verified before execution | 297f10319dbba4f39627799a8d1709680a12163ef61584a97527dd7b2df58c12 |
| Restored image, ROM readback after **each** run | d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b |
| Restored MicroPython, device rehash after **each** run | d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b |

The successful run ends with **HARDWARE_VALIDATION_PASS restored_and_verified**. MicroPython v1.26.0 starts normally, and its HDMI console is attached/unpaused with no error. The console was resumed after hashing, and its [restored HDMI image](results/hardware/20261103-fixed/restored-micropython.png) was captured. [Full verification record](results/hardware/20261103-fixed/flash-verification.json). Flash/filesystem images are retained locally and excluded from Git.

## Initial failure and correction

The first run passed all seven readback CRCs, the timed application loop, requested-budget OOM and live-owner OOM. The **real native malloc failure probe produced SDK PANIC**. Workloads stopped; USB disconnected; BOOTSEL became available and the host restored and verified the original flash. [Failure log and screenshots](results/hardware/20261103-first/device-log.txt) are preserved. The intermediate reset reason/precise recovery latency was not captured, so no exact watchdog-reset timing is claimed.

The pinned Pico SDK defaults to PICO_MALLOC_PANIC: failed malloc/realloc panics rather than returning NULL to Wren's allocator. The CPU-emulated newlib host did not have that wrapper, explaining why emulation missed this integration problem.

The corrected build sets **PICO_MALLOC_PANIC=0** so an expected native allocation failure reaches the existing whole-VM discard boundary. Allocation safety is retained: the SDK sbrk limit remains the linker's hard 132 KiB endpoint, every successful Wren native allocation receives an explicit **lower/upper/end range check**, and an invalid range still panics/stops. This check includes ledger headers. The 48 KiB stack, MPU guard, 8 KiB recovery reserve, normal 96 KiB payload cap and eight-second watchdog remain unchanged. No OOM probe or correctness assertion was removed.

The corrected run passes the same real malloc-failure probe and twenty subsequent fresh VMs, with no unexpected panic/reset. Boot reports watchdog=0 and raw reset_reason=1 for the host-requested boot; normal completion explicitly enters ROM BOOTSEL. The automatic USB reset interfaces remain disabled. Watchdog alone does not restore MicroPython; the verified host restoration is still required.

After the correction and before reflashing, Release host tests passed **18/18**, ASan/UBSan with leak detection **18/18**, and ARM CPU-emulated correctness/CRC/cap sweeps/native-malloc recovery all passed. The unchanged Wren baseline also passes **1/1**. [Host log](results/host-tests.txt), [sanitizers](results/asan-tests.txt), [ARM correctness](results/arm-correctness.txt), [ARM memory/recovery summary](results/arm-summary.json). Input verification confirms PR #68/#69 source directories, MicroPython/native software and HAL are unchanged.

## Actual SRAM and stack measurements

The runtime-reported addresses match the ELF exactly. See the [detailed linker map](results/flash-linker.map), [ELF analysis](results/flash-layout.json), and [physical measurements](results/hardware/20261103-fixed/measurements.json).

| Reservation | Range, end exclusive | Bytes |
|---|---|---:|
| Static SRAM: vectors + .data + .bss | 0x20000000–0x2000b1f4 | **45,556** |
| Bounded malloc arena | 0x2000b1f4–0x2002c1f4 | **135,168** |
| Unassigned main SRAM | 0x2002c1f4–0x20032000 | 24,076 |
| Recovery reserve | 0x20032000–0x20034000 | **8,192** |
| Native stack, including MPU guard | 0x20034000–0x20040000 | **49,152** |
| Unused scratch X/Y | 0x20040000–0x20042000 | 8,192 |

Total reserved **238,068 B**, unassigned **32,268 B (31.51 KiB)** in separate main/scratch regions. Actual reservation is **3,216 B below** the prior minimal native integration estimate of 241,284 B. Instrumentation added 196 B to the initial PR #70 static layout. No reservation was reduced to force the build to fit.

| Observed measure | Real RP2040 | CPU-emulated host |
|---|---:|---:|
| Initialization live payload | 74,908 B | 74,908 B |
| Post-application compilation live payload | 84,895 B | 84,895 B |
| Peak requested live payload, including error/recompile checks | **91,970 B** | **91,970 B** |
| Peak payload + custom ledger headers | 111,378 B | 111,378 B |
| Peak newlib used occupancy, timed run | 122,740 B | 122,752 B |
| Peak arena backing | **126,476 B** | **125,976 B** |
| Painted stack upper-bound observation | **33,760 B** | **33,560 B** |
| VM ledger after each normal/OOM shutdown | **0 B / 0 blocks** | **0 B / 0 blocks** |

The different harnesses mean the stack observations are not an isolated IRQ overhead measurement. Physical backing is 500 B above the CPU-host observation; this is why payload/ledger totals alone are insufficient. The tested cap retains **8,692 B** of arena backing slack. Stack reservation exceeds the observed upper bound by **15,392 B**; all sixteen checked bottom-canary words and the entire 8 KiB recovery canary remain intact. A 1,036-byte non-Wren newlib baseline remains after VM cleanup; allocation/free ledger counts balance.

The tested application uses a 96 KiB requested-payload limit over 132 KiB native backing. A real 32 KiB payload test fails cleanly during initialization. A physical minimum was not bisected; 91,970 B is the measured peak for this exact workload, not a universal safe minimum. GC thresholds remain 16 KiB initial / 8 KiB minimum / 25% growth, distinct from both caps and actual backing.

## Workloads, FFI, GC and latency

Exactly one static native desktop and its original 32,000-byte framebuffer are used. No second framebuffer or dynamic GUI binding pool is introduced. Snapshot/export storage shares the existing 1,280 bytes under the synchronous non-reentrant guard. The four foreign methods and ASCII title renderer are unchanged.

The successful test performs one captured application, twenty compiled calls in one VM, three expected OOM paths, then twenty fresh VM lifecycles. Each successful application opens one window, outlines one rectangle, consumes four events and presents each update; 41 applications complete in total. Syntax/runtime/invalid-foreign-argument errors and repeated interpretation/GC also pass. Exact Japanese UTF-8 output is verified; this is USB string output, not Japanese font integration.

The timed twenty-call phase reports 321 foreign calls: twenty opens, 101 rectangle calls (including one deliberately rejected invalid call), 100 event polls (including twenty empty polls), and 100 presents. It includes **71 explicit collections**; automatically triggered collections are not separately counted. Post-GC live payload is 88,666 B in that run. Each fresh VM performs 52 explicit collections and returns its complete ledger to zero.

| Measurement | Samples | Minimum | Mean | Maximum |
|---|---:|---:|---:|---:|
| Foreign open body | 20 | 61 us | 71.45 us | 124 us |
| Foreign rectangle body | 101 | 48 us | 63.96 us | 127 us |
| Foreign event body | 100 | 4 us | 9.32 us | 33 us |
| Foreign present body | 100 | 6.308 ms | 9.707 ms | 22.828 ms |
| Explicit GC | 71 | 1.292 ms | 1.370 ms | 1.541 ms |
| Previously compiled App.run() | 20 | 49.395 ms | 49.505 ms | 49.974 ms |
| Initialization | 1 | 210.139 ms | single sample | 210.139 ms |
| Application compilation | 1 | 22.318 ms | single sample | 22.318 ms |

Foreign-body measurements include slot validation/native work, not VM dispatch overhead. Present includes rendering and actual blocking TILE4 write/FENCE/error acknowledgement. The 49.5 ms call presents five frames and processes four events; it is not a single-frame latency. HDMI capture waits and the ~2.86-second full-plane readback are excluded from this timed phase. CPU emulation supplies memory/correctness evidence and does not predict hardware latency.

Expected failures all discard the VM, close native ownership and reach zero live blocks with allocations=frees:
* 32 KiB requested-budget limit: OOM kind 1, initialization stage.
* Failure injected while owning a native window: OOM kind 3, execution stage.
* Actual native realloc failure on a 160,000-byte request: OOM kind 2, execution stage, while the hard 132 KiB arena stays unchanged.

All twenty fresh VMs after these failures succeed in the same arena without growth. These are deterministic fragmentation/recovery checks, not a proof against arbitrary future application fragmentation.

## CRC, acknowledged transport and HDMI

Each of seven frames reads the complete 32,000-byte FPGA pattern plane and compares every byte to native TILE4 export, then compares its CRC with the host/native golden. Every mismatch count and remaining dirty count is zero.

| Frame | Host = native framebuffer = FPGA readback CRC |
|---|---|
| Initial plane, before display enable | be72ff88 |
| Window + first rectangle | c91b4078 |
| Event 1 | 7017406d |
| Event 2 | e89d5ada |
| Event 3 | f07a198f |
| Event 4 | abb5deb8 |
| Native owner closed | be72ff88 |

The visible run accumulates 75 acknowledged runs / 1,592 tiles by cleanup. A run is acknowledged only after its blocking write, fresh DONE-tag FENCE and error check. Across the whole test the unchanged HAL clocks 4,718,594 bytes in 756,838 transactions, with no observed BUSY waiting. These aggregate counts include the intentionally slow bytewise readback and are not a transport-throughput benchmark.

Six settled HDMI captures show the window/title, rectangle/event updates and cleanup. [First frame](results/hardware/20261103-fixed/frame-1.png), [fourth event](results/hardware/20261103-fixed/frame-5.png).

**HDMI colour comparison is qualified, not a clean pixel-colour pass.** The unchanged native capture classifier explains 1,940 of 1,986 class mismatches as capture chroma/filter effects, leaving **46 unexplained pixels** on the final thin red outline (of 76,800 logical pixels in that frame). Both hardware runs reproduce this. No tolerance or correctness test was relaxed. The red has no uniform 3×3 reference interior, so the classifier falls back to uncalibrated nominal RGB; capture-colour conversion is a plausible explanation, not independently proven.

A supplementary fixed red-dominance geometry check at the already selected global sample phase finds **all 140 expected red-outline pixels, zero missing and zero extra**, while the full FPGA byte readback/CRC is exact. This supports correct geometry but does not replace the retained colour-test failure or establish absolute HDMI colour fidelity. [Original classifier report](results/hardware/20261103-fixed/hdmi-compare.md), [supplementary geometry](results/hardware/20261103-fixed/red-geometry.json).

## Decision and limits

The tested minimal **flash-resident** Wren + Native Desktop is viable on RP2040 under the retained memory reservations. The real native-OOM policy mismatch was material and had to be corrected; emulated success alone was insufficient. Native FFI ownership, compiled calls, error/GC recovery and acknowledged rendering work on the physical installation.

This result does not establish full GUI binding/application-suite capacity, an SRAM-only integrated image, long-duration reliability, exact FPGA bitstream provenance or absolute HDMI colour accuracy. RP2350 is not measured here. Keep the thin-red capture classification issue visible for follow-up; do not treat the supplementary geometry check as a waived acceptance assertion. No API expansion, Japanese font integration, FPGA firmware update or automatic merge occurred.
