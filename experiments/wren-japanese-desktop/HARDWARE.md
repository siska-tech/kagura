# Stage 4 physical validation — 2026-11-03

**The approved, unchanged candidate renders the Wren-created Japanese title on Pico RP2040 + Tang Nano 9K. Full-plane CRC, GC/lifecycles, expected OOM recovery, memory guards and complete MicroPython restoration pass.** The pre-existing thin-red HDMI colour-classification discrepancy remains open; its thresholds are unchanged.

## Exact candidate and preflight

Firmware source: **25c7e9c03a5bfe6508dea91ee3faeebb0a57874d**. ELF SHA-256: **af6f1679e7b1e4577bec5eca6d0781aacb3ffa527aa07215cddb04a2bbf456f9**. This exact artifact and **0x10000000–0x10038000** write/restore range were separately approved after host/emulator tests and the integrated memory audit. Later capture/report changes do not change the target firmware.

Hardware: Pico **RP2040 B2 / 125 MHz / 2 MiB flash**, existing Tang Nano 9K ID **4b39**, ABI **0.6**, CAPS **0x5b**, 240 lines, 1,200 patterns, error code zero. QSPI **5 MHz, four lanes**, GP2–5 IO, GP6 SCK, GP7 CS, GP8 BUSY, GP9 READY, GP10 IRQ. UGREEN 15390 capture is 1280×960 YUYV, 60 fps. The FPGA bitstream's exact hash is not exposed by this ABI and was not independently established; no FPGA bitstream/storage update occurred.

The existing verified backup and known-good MicroPython UF2 were checked locally. After approval, a **fresh complete 2 MiB backup** was obtained and verified against device hashes before/after and host reread. It matches the previous backup exactly:

**d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b**.

Fresh private backup: parent workspace `build/wren-japanese-hardware/flash-backup-20261102T182540Z/flash-2MiB.bin` (directory timestamp is UTC). Known-good MicroPython program UF2 remains SHA-256 **9ebfa459351e7e402d7c5690a0ddfc405b91d65093162586e89198733d03f95c**. Flash/filesystem images are retained privately, not committed. [Device checks](results/hardware/preflight.txt), [BOOTSEL full-readback/control-boot gate](results/hardware/recovery-preflight.txt).

Both hardware attempts wrote/restored only the approved **229,376-byte prefix**. Full 2 MiB readbacks before boot verify the expected image and unchanged tail. Programmed complete-flash SHA-256 in both attempts:

**98526fd2dfd1e975cce83e4c6f232c6a64aa194fa05f4b0c91b87674b4d864ab**.

## First capture failure, retained evidence

The first attempt passed runtime, all seven byte/CRC checks, guards and restoration, but its 20-frame (0.33 s) captures were black/UGREEN no-signal images. **Those images are not accepted as Japanese HDMI evidence**, regardless of the original harness's runtime PASS banner. [First-attempt diagnostic](results/hardware/first-capture/hdmi-compare.md), [raw log](results/hardware/first-capture/device-log.txt), [restoration verification](results/hardware/first-capture/flash-verification.json).

The user confirmed the capture passthrough displayed the restored `KAGURA Wren validation` message; an independent longer capture also showed healthy MicroPython video. The same target ELF was therefore rerun with **180-frame / 3-second receiver settling**, plus a host-side signal-presence check of fixed desktop-green/menu-white locations. This check rejects black/no-signal capture and aborts into restoration; it does not replace the full colour comparison. All six presence checks pass. The outcome is consistent with receiver relocking; exact receiver lock latency/root cause was not independently instrumented.

**No Pico firmware, FPGA bitstream, colour tolerance, heap/stack limit, OOM path or watchdog/MPU guard was changed to fix capture.**

## Japanese drawing and CRC

[Physical Japanese title](results/hardware/validated/frame-1.png), [event 4](results/hardware/validated/frame-5.png), [raw validated run](results/hardware/validated/device-log.txt), [structured measurements](results/hardware/validated/measurements.json).

The application forms `神楽 Desktop` by concatenating Wren strings, opens the native window, clears the temporary reference and calls **System.gc() before drawing**. The captured title is therefore backed by the Desktop-owned copy, not a retained VM string pointer. One static Desktop and its sole 32,000-byte framebuffer are used. Four events change rectangle position/colour and produce the expected frames.

Every captured frame's complete 32,000-byte FPGA plane is compared byte-for-byte with native TILE4 export, and CRCs match the independent native/Wren/ARM goldens:

| Frame | Native C = Wren = ARM = real FPGA CRC |
|---|---|
| Initial plane before display enable | be72ff88 |
| Japanese title + rectangle | 32f7ed69 |
| Event 1 | 8bfbed7c |
| Event 2 | 1371f7cb |
| Event 3 | 0b96b49e |
| Event 4 | 505973a9 |
| Owner cleanup | be72ff88 |

All mismatch and remaining-dirty counts are zero. The visual sequence accumulates 75 acknowledged runs / 1,592 tiles, with each run cleared only after write + fresh DONE/FENCE + error check. Six settled HDMI captures show Japanese/ASCII title glyphs and updates. Frame zero is read before display enable and is not claimed as a visible image.

Overlap across the title, reveal, partial clipping/movement, storage boundaries, invalid UTF-8/NUL and stale handle guards have deterministic native/Wren/ARM coverage. The physical acceptance image intentionally runs the one-window minimal workload; it does **not** claim a separate physical overlap/move capture or every malformed-input case on Pico.

The unchanged full colour classifier gives the **same** historical result as PR #70: 1,986 class mismatches across six images, 1,940 explained as chroma/filter effects and **46 unexplained pixels on the thin red outline**. No additional unexplained pixels occur in the Japanese title. This remains a separate open issue, not a waived assertion. A supplementary unchanged red-geometry diagnostic sees all 140 expected red pixels with zero missing/extra, but does not prove absolute colour accuracy. [Original-threshold comparison](results/hardware/validated/hdmi-compare.md), [supplementary diagnostic](results/hardware/validated/red-geometry.json).

## Actual memory and runtime safety

Runtime-reported heap, stack and recovery addresses equal the audited ELF. Static SRAM is **45,596 B** (+40 B vs PR #70); allocator reservation **135,168 B**, stack **49,152 B**, recovery **8,192 B**, unassigned **32,228 B**. Full font remains in flash, with no VM copy or second framebuffer. See README and the linker map for bank attribution.

| Observation | PR #70 physical | Stage 4 physical |
|---|---:|---:|
| Init live Wren payload | 74,908 B | **74,908 B** |
| Post-compile live | 84,895 B | **84,919 B** |
| Post-GC live, timed phase | 88,666 B | **88,690 B** |
| Peak live requested payload | 91,970 B | **91,994 B** |
| Peak payload + custom ledger | 111,378 B | **111,418 B** |
| Peak newlib used occupancy | 122,740 B | **122,796 B** |
| Newlib arena high water | 126,476 B | **126,436 B** |
| Stack painted upper observation | 33,760 B | **33,848 B** |
| VM shutdown live / blocks | 0 / 0 | **0 / 0** |

The 40-byte lower arena count is **not a memory-saving claim**: heap start moves up 40 bytes, and both physical high-water endpoints are 0x2002a000. Requested payload, ledger, used occupancy and stack all grow. The current physical arena retains 8,732 B within its hard cap; the observed stack is 15,304 B below its unchanged reservation. All sixteen bottom canaries and the whole recovery reserve are intact. A 1,036-byte non-Wren newlib baseline remains after cleanup, as before.

Stage 4 CPU emulation reaches 128,648 B backing and a 33,648 B stack observation. The differing harnesses/allocation layouts make physical/emulated backing and stack numbers non-interchangeable. Neither measurement authorizes reducing protections or predicts arbitrary application fragmentation.

The final run completes one visual app, twenty compiled calls, requested-limit OOM, native-owner injected OOM, **actual native allocation failure on a 160,000-byte request**, and twenty fresh VMs afterward in the same bounded arena. All normal/error/OOM exits have zero VM ledger blocks and balanced allocations/frees. The private ticket guard tests also run in checked VM sessions; no dangling Wren handle is passed to its C API.

No unexpected panic or MCU reset occurred in either Stage 4 attempt. Boot reports enabled-watchdog failure=false, raw reset_reason=1 for the host-requested boot. The eight-second watchdog, MPU stack guard, explicit allocation range checks and hard sbrk bound remain enabled. SDK malloc failure still returns NULL to the existing whole-VM discard boundary. Normal completion explicitly enters ROM BOOTSEL for restoration.

## Physical performance

The final timed phase reuses compiled handles, twenty callbacks and 321 foreign calls. Capture waits and ~2.86-second full-plane readbacks are excluded by resetting counters before the timed phase. Foreign measurements cover the native body/slot validation; they do not isolate VM dispatch overhead.

| Span | Samples | Min | Mean | Max |
|---|---:|---:|---:|---:|
| Foreign open | 20 | 100 us | **112.70 us** | 175 us |
| Foreign rect (includes one rejected probe) | 101 | 42 us | **50.86 us** | 134 us |
| Foreign event | 100 | 3 us | **11.29 us** | 34 us |
| Foreign present | 100 | 6.772 ms | **10.288 ms** | 23.952 ms |
| Explicit host-triggered GC | 71 | 1.200 ms | **1.381 ms** | 1.556 ms |
| App.run: five presents / four events | 20 | 53.525 ms | **53.711 ms** | 54.299 ms |
| VM initialization | 1 | 220.263 ms | single sample | 220.263 ms |
| Application compilation | 1 | 24.313 ms | single sample | 24.313 ms |

PR #70's historical App.run mean is 49.505 ms; this run is approximately **4.206 ms / 8.5% longer**. This includes extra script-triggered GC, string construction, UTF-8/native title work and call guards; it is not a controlled isolation of font rendering cost. Script System.gc() and automatic collections are not included in the host's count of 71 explicit collections, but their cost inside App.run is included in that call span. Do not interpret the five-present callback time as a single-frame FPS benchmark.

## Complete restoration and conclusion

After **both** attempts, the original 229,376-byte prefix was restored, then all **2,097,152 bytes** were read back and required to equal the fresh original backup. A subsequent device-side complete-flash hash also equals:

**d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b**.

The final log ends **HARDWARE_VALIDATION_PASS restored_and_verified** with MicroPython v1.26.0's console attached, unpaused, screen present and last_error=None. The console was resumed and its [restored HDMI output](results/hardware/validated/restored-micropython.png) captured. [Complete readback/tail verification](results/hardware/validated/flash-verification.json). No restoration success is inferred merely from a reboot.

The smallest reliable Wren UTF-8 → native Japanese title → acknowledged FPGA plane/HDMI path is now demonstrated within the original memory protections. Limits remain: 24-byte title storage, bounded 1,024-byte input policy, host/emulator-only overlap/movement matrix, the historical red-colour discrepancy, receiver settling, and no long-duration qualification. No IME/editor/filesystem integration, font redesign, FPGA change, guard reduction or PR merge is included.
