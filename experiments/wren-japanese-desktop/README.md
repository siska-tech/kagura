# Stage 4 — Wren Native Japanese Desktop Integration

**Host and ARM-emulated validation and the complete RP2040 link audit pass. Physical execution of this new image is pending separate approval.** The Wren script creates `神楽 Desktop` from a temporary concatenated string, clears that VM variable and calls `System.gc()` before drawing. Native-owned text remains correct through redraws, overlapping-window reveal, partial clipping/movement and VM recreation. [Wren host output](results/wren-japanese-title.png), [overlap](results/wren-overlap.png), [partly clipped title](results/wren-partial-title.png).

This is an integration, not a replacement renderer. PR #71's `kj_text` / `kj_desktop` and all **7,171 Misaki glyphs** are unchanged. The full 71,718-byte KJ8F and its separate [Misaki attribution/license](../native-text/NOTICE.md) are reused, hash `cbfb1071801f7ed3b6637bb6763219e59d86c13bd149169bbbab5bca753d9238`. The font is immutable flash data, never copied into the Wren heap.

## Branch, references and preserved evidence

Branch: `experiment/wren-japanese-desktop`, based on PR #71 head **99c4250f124c0f3c86e5e8fb77554f015744e799**. References remain Draft/open/unmerged:

| Reference | Pinned head |
|---|---|
| #68 native Desktop | be344f5c742101f0cff170a29f63d09c0a17c441 |
| #69 Wren feasibility | d03912b4339495379302b286383eb40cf8a6d53e |
| #70 physically validated Wren Desktop | 1c089f2b5d22c4cded5a87f96c8ad74dd3a55914 |
| #71 native Japanese text | 99c4250f124c0f3c86e5e8fb77554f015744e799 |

Only opt-in `WD_JAPANESE` paths in the Wren host/UI and this new experiment are added. Default PR #70 paths retain their original script/ASCII policy. Original PR #70/#71 test and hardware evidence files are not overwritten; new results are stored here. Software/MicroPython, the HAL, FPGA ABI/RTL/bitstream, native text implementation and font assets are unchanged.

One `DesktopState` owns one **34,160-byte kd_desktop**, including the **32,000-byte framebuffer**. Its complete integration state stays **34,284 bytes**. Existing damage/dirty-tile tracking, synchronous acknowledged TILE4 sink and guarded 1,280-byte render-snapshot/export sharing remain unchanged. Test-only mock external VRAM is not linked into firmware. Host demo exports stream pixels to disk without another image-sized buffer.

## Minimal foreign boundary and ownership policy

The same four methods remain: `Desktop.open(title)`, `rect`, `nextEvent`, `present`. No move/text/font API is exposed to Wren. Native movement/cover orchestration is exercised in the cover test only.

1. Check `WREN_TYPE_STRING`, then obtain **wrenGetSlotBytes plus its explicit int byte length**. Negative lengths are rejected. No strlen is applied to a Wren string pointer.
2. The whole input span is checked before conversion or window mutation, including bytes beyond the stored prefix. Maximum input is **1,024 bytes**; larger input raises a runtime error. Empty strings are allowed.
3. **Malformed UTF-8, embedded NUL, C0 and DEL are rejected atomically** by aborting the calling fiber with an error. Overlong encodings, surrogates, lone continuations and incomplete sequences are invalid. A valid unsupported scalar (such as emoji) is accepted and rendered with PR #71's documented fallback. This strict foreign policy deliberately differs from the text engine's byte-wise replacement policy for raw native text.
4. Accepted input is copied into a bounded stack buffer, retaining at most **23 complete UTF-8 bytes plus NUL**, then copied into the existing Desktop-owned 24-byte title field. Valid long titles truncate at complete code points. No GUI field size changes. A title can hold seven 3-byte Japanese characters plus two ASCII bytes; display fitting may clip further by available pixel width.
5. Only owned, terminated native text reaches the existing C Desktop string APIs. The stack copy is gone on return; no VM string pointer is stored in Desktop state. GC immediately after open therefore cannot invalidate the title.
6. Duplicate open returns false without replacing the owner. Operations after owner cleanup fail normally. OOM still closes the native owner, discards the interrupted VM and frees its complete allocation ledger without resuming it.

Compiled calls retain the receiver/method handles within one VM. An opt-in private call ticket checks **VM, registered receiver/method and a monotonically advancing session** before any Wren API use. Registrations clear before release/shutdown and on OOM; the borrowed C test-source pointer also clears before return. Tests reject stale-session, NULL receiver/method/VM and released tickets **without passing dangling handles into Wren**, which would be undefined behavior. No raw handles/window IDs are exposed to scripts.

ASCII rendering remains byte-identical: Stage 4's ASCII script matches all seven physically validated PR #70 CRC goldens exactly. Native system/small ASCII glyph overrides remain those from PR #71. The title is measured in advances, not UTF-8 bytes.

## Deterministic validation

| Suite | Release | ASan+UBSan |
|---|---:|---:|
| Stage 4 integration, Wren/native export demos, text core/oracle | **5/5** | **5/5** |
| Original PR #70 regression/mutation suite | **18/18** | **18/18** |
| Original PR #71 text/native GUI regression suite | **21/21** | **21/21** |
| Original Wren runtime feasibility | **1/1** | unchanged baseline |

The Stage 4 ARM/newlib suite uses the original PR #70 checker and assertions with only artifact/result routing changed: full correctness, budget/physical-cap sweeps, twenty VMs × ten compiled callbacks in normal/cover mode, native malloc OOM and requested-limit OOM followed by successful fresh VMs. The hard physical cap remains **135,168 B**. No stress/correctness test or allocator check was removed. [ARM summary](results/arm-summary.json).

Additional tests include:

* Native/Wren title equality after temporary VM-string collection; mixed Japanese/ASCII and valid unsupported emoji.
* Exact 23-byte titles, 24-byte ASCII truncation, seven Japanese glyphs + two ASCII bytes, a 3-byte glyph crossing the capacity, and empty titles.
* Explicit NUL, malformed and truncated/overlong/surrogate encodings, wrong argument types, forbidden controls, 1,025-byte input and an invalid byte **after** a valid stored-size prefix. Error paths have zero remaining VM blocks and no owner.
* Duplicate ownership, stale/private handle guards, immediate `System.gc()`, VM recreation, sampled Nth-allocation failures and the original ABI/write/DONE/FENCE/error transport regressions.
* The cover crosses the Japanese title itself, then reveals it. The window moves to x=-100 for partial title clipping and returns; no new scripting method is needed. Dirty tile behavior is checked byte-for-byte through the existing mock sink.

Native C, Wren and ARM-emulated frame CRCs agree: seven normal frames and ten overlap/reveal/move frames. The normal native/Wren indexed image exports are byte-identical. [Goldens](results/goldens.json), [host trace](results/japanese-trace.txt), [ARM correctness](results/arm-correctness.txt). These are mock transport results, **not new physical FPGA readbacks**.

Normal CRC sequence: `be72ff88`, `32f7ed69`, `8bfbed7c`, `1371f7cb`, `0b96b49e`, `505973a9`, `be72ff88`.

## Actual complete RP2040 link

ELF SHA-256 **af6f1679e7b1e4577bec5eca6d0781aacb3ffa527aa07215cddb04a2bbf456f9**. Entry **0x100001e9**. [Detailed map](results/flash-linker.map), [program headers/sections](results/flash-readelf.txt), [symbols](results/flash-symbols.txt), [machine-readable audit](results/flash-layout.json).

| Reservation | PR #70 validated baseline | Stage 4 linked | Difference |
|---|---:|---:|---:|
| Flash load payload | 152,832 B | **227,480 B** | **+74,648 B** |
| Static SRAM | 45,556 B | **45,596 B** | **+40 B** |
| Bounded native allocator | 135,168 B | **135,168 B** | 0 |
| Native stack incl. MPU guard | 49,152 B | **49,152 B** | 0 |
| Recovery reserve | 8,192 B | **8,192 B** | 0 |
| Unassigned physical SRAM | 32,268 B | **32,228 B** | **-40 B** |

The 40 bytes are handle/session/source registration state: Runtime grows 280→312 B, plus an 8-byte session counter. The font adds no writable static RAM, but **this does not imply zero runtime memory impact**. Native titles remain byte-capacity limited and VM UTF-8 strings still allocate.

| SRAM allocation | Address range, end exclusive | Bytes |
|---|---|---:|
| Vectors | 0x20000000–0x200000c0 | 192 |
| .data / RAM functions | 0x200000c0–0x20001900 | 6,208 |
| .bss | 0x20001900–0x2000b21c | 39,196 |
| Bounded malloc | 0x2000b21c–0x2002c21c | 135,168 |
| Unassigned main SRAM | 0x2002c21c–0x20032000 | 24,036 |
| Recovery | 0x20032000–0x20034000 | 8,192 |
| Stack | 0x20034000–0x20040000 | 49,152 |
| Free scratch X | 0x20040000–0x20041000 | 4,096 |
| Free scratch Y | 0x20041000–0x20042000 | 4,096 |

The 256 KiB main region is **word-interleaved across four physical 64 KiB banks**: unused bytes are bank 0/1/2 **6,008 B each**, bank 3 **6,012 B**. These are striped attribution counts, not four contiguous heap regions. Scratch banks each retain 4,096 B. Total physical SRAM is 270,336 B; total unassigned is 31.47 KiB across separate regions. The .heap 2 KiB linker marker lies inside the bounded arena and is not counted again.

Full Misaki glyph bytes occupy **0x10023ff0–0x10035816**, size **71,718**, in flash; the 24-byte descriptor is also in flash. No file-backed load segment targets SRAM physical addresses. Flash text/rodata/boot occupies 0x10000000–0x10036058; the initialized RAM image is stored at 0x10036058–0x10037898. Sector-aligned programming would cover **0x10000000–0x10038000 (229,376 B)** only. No UF2/upload target is generated, and no flash erase/program routine is linked.

Every PR #70 ELF safety assertion is reused unchanged: 132 KiB hard sbrk limit, exact 48 KiB stack, 8 KiB recovery, no overlap, empty scratch/core-1 sections, no mock framebuffer or flash-program symbols. Stage 4 adds exact font placement/size and unchanged Desktop-state checks. Pico SDK **2.2.0 a1438dff…**, TinyUSB **86ad6e56…**, Arm GCC **14.2.1**, official Wren **99d2f0b8…** remain pinned. SDK malloc returns NULL for expected failure; explicit successful-allocation bounds, watchdog and MPU protection remain enabled.

## Runtime measurements and performance limits

| Observation | PR #70 ARM emulation | Stage 4 ARM emulation | PR #70 actual Pico reference |
|---|---:|---:|---:|
| Init live payload | 74,908 | **74,908** | 74,908 |
| Post-application compile live | 84,895 | **84,919** | 84,895 |
| Peak requested live payload | 91,970 | **91,994** | 91,970 |
| Peak payload + allocation ledger | 111,378 | **111,418** | 111,378 |
| Native arena high water | 125,976 | **128,648** | 126,476 |
| Painted stack upper observation | 33,560 | **33,648** | 33,760 |
| Shutdown VM ledger | 0 / 0 blocks | **0 / 0 blocks** | 0 / 0 blocks |

The current exact emulator workload needs 24 more live payload bytes, **2,672 more backing bytes** and an 88-byte higher stack observation than the old emulator. It leaves 6,520 B below the native backing cap in that harness. This is useful fragmentation evidence, not proof that physical USB/IRQ/libc behavior will match. A 1,032-byte non-Wren emulated stdio allocation remains after VM cleanup. [Raw run](results/arm-normal.txt), [native malloc recovery](results/arm-malloc-recovery.txt).

GC settings remain 16 KiB initial / 8 KiB minimum / 25% growth; normal ARM/Pico payload cap is **96 KiB**, backed by the hard 132 KiB arena. The 64-bit PC demo uses PR #70's 256 KiB host cap because pointer/object/header sizes differ; it is not an enlarged MCU heap. Emulated bisection finds 91,994 B payload / 128,648 B backing for this exact binary, **not a recommended safe deployment minimum**.

`System.gc()` after open is real VM collection; the host's existing explicit-collection metric counts its own `wrenCollectGarbage` calls, not every automatic or script-triggered collection. Compiled method handles are reused; only the separate repeated-interpretation stress intentionally recompiles.

New physical latency and stack/heap high-water measurements are **pending**. Emulator timer hooks are not cycle models and cannot predict MCU latency. PR #70's measured 49.505 ms per five-present/four-event App.run and 1.370 ms explicit GC mean are historical references, not Stage 4 results. A separate approved run will capture the same timing spans without including readback/capture waits. The 48 KiB stack reservation must not be reduced based on compiler or emulator observations.

## Reproduction

From this directory, with the same pinned toolchain/SDK used by PR #70:

```sh
python3 ../wren-rp2040/tools/acquire.py
cmake -S . -B build-host -DCMAKE_BUILD_TYPE=Release
cmake --build build-host -j4
ctest --test-dir build-host --output-on-failure
bash tools/regressions.sh
bash tools/build_arm.sh
QEMU=/path/to/qemu-arm python3 tools/arm_checks.py
python3 tools/goldens.py
bash tools/build_pico.sh
bash tools/evidence.sh
```

ARM CPU tests use qemu-arm **10.2.1**, not Pico peripheral emulation. `tools/regressions.sh` configures PR #70 and #71 suites separately and writes results here. Their original tests/evidence remain intact. The standalone Wren baseline is also configured/tested separately. No physical operation occurs in these commands.

## Hardware gate and remaining acceptance

Stage 4 explicitly says **“Only then perform the separately approved hardware-validation procedure.”** This candidate has not yet been physically executed or programmed. Host/ARM/mock CRC success does not satisfy the physical FPGA/HDMI part of acceptance.

The existing complete 2 MiB MicroPython backup remains readable locally at parent-workspace `build/wren-desktop-hardware/flash-backup-20261102T142039Z/flash-2MiB.bin`, SHA-256 **d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b**. The known-good `build/micropython-src/ports/rp2/build-KAGURA_PICO_PINNED/firmware.uf2` still hashes to **9ebfa459351e7e402d7c5690a0ddfc405b91d65093162586e89198733d03f95c**. Neither private flash/filesystem image is committed.

Prepared procedure: after separate approval, verify current board/wiring/ABI/power/recovery, make or validate a fresh complete backup, prove ROM readback and normal MicroPython recovery, then use `tools/hardware_run.py`. It reuses PR #70's bounded-prefix program/readback/restore procedure and all its assertions, replacing **only** the frozen frame CRC input with the Stage 4 native/Wren/ARM goldens. Exact artifact/backup hashes and --approved remain required; --plan-only accesses no device. If current flash differs from the retained backup, stop and preserve current state rather than restoring an obsolete image.

The candidate's proposed write/restore range is 0x10000000–0x10038000. Read all 2 MiB after programming and before execution, require the tail outside that range unchanged, then run Japanese visual frames, GC/lifecycles/OOM and canary/timing capture. Restore the original same-sized prefix, read all flash and require full backup equality/hash, reboot MicroPython and verify its hash/normal KAGURA console before claiming restoration. Never touch FPGA firmware or other device storage.

The existing **46-pixel thin-red HDMI colour-classification discrepancy remains a separate open issue**. The original comparison thresholds are unchanged. No new physical result or resolution is claimed here. A new capture uses the unchanged native classifier and Stage 4 native reference images.

No SKK, IME, editor, filesystem, GUI redesign, font redesign, new runtime, framebuffer elimination or unrelated optimization is included. All reference PRs and this integration must remain Draft and unmerged pending review and the hardware gate.
