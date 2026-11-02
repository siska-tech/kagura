# RP2040 SRAM-only build and hardware acceptance plan

**Hardware status: NOT RUN. Separate explicit approval is required.**
This document and the offline tools do not access a device. The current binary
is a memory-feasibility candidate: its SRAM-only layout cannot fit the entire
suite's observed ARM allocation requirements. Do not call a partial/OOM run
runtime acceptance. No existing firmware restoration or flash-hash result is
claimed for Wren.

## Reproducible build

Pinned inputs:

- Wren `99d2f0b8fc2686134b32b18166e037639f7e9f2c`, MIT, source manifest verified.
- Pico SDK 2.2.0 `a1438dff1d38bd9c65dbd693f0e5db4b9ae91779`.
- TinyUSB `86ad6e56c1700e85f1c5678607a762cfe3aa2f47`.
- Arm GNU Toolchain 14.2.Rel1, GCC `14.2.1 20241119`.
- CMake 3.31.6; picotool 2.2.0 `a7eb3988f0645239185fadb4e25d8279478c2dbb`,
  existing Linux build without USB support, reused only to package UF2.
- Cortex-M0+, Thumb, soft float, `-Os`, function/data sections and linker GC.

The SDK and compiler are external build inputs, not changes to KAGURA's SDK.
For a fresh environment, clone Raspberry Pi's official pico-sdk at the exact
revision and initialize its TinyUSB submodule; install the pinned Arm GNU
toolchain and CMake. Set their paths, then from this experiment directory:

```sh
python3 tools/acquire.py
export PICO_SDK_PATH=/path/to/pico-sdk-2.2.0
export PATH=/path/to/arm-gnu-toolchain-14.2.rel1/bin:/path/to/cmake-3.31.6/bin:$PATH
bash tools/build_pico.sh -Dpicotool_DIR=/path/to/picotoolConfigDirectory
# If not reusing picotool, the SDK's pinned picotool dependency can be built.
```

`build-pico/wren_rp2040.{elf,uf2,map}` (map filename may be `.elf.map`) are the
outputs. The script checks input revisions/toolchain and runs the offline image
validator. Fixed inputs reproduce source/build configuration; byte-for-byte ELF
hashes can differ with checkout paths because debug information embeds paths.
Use the hash of the actual candidate for approval and verify it immediately
before loading. No build or validation command programs flash or starts a Pico.

## ELF, SRAM, flash and stack

Exact final records are in `../results/rp2040-image.txt`,
`rp2040-program-headers.txt`, `rp2040-sections.txt` and `rp2040-symbols.txt`.
All ranges below are exclusive at the end; consult those records after a rebuild.

| Allocation | Layout / interpretation |
|---|---|
| Entry | `0x20000001`, Thumb; lowest load address `0x20000000` |
| File-backed PT_LOAD | `0x20000000–0x2001f82c`, filesz 129,068 B, memsz 135,360 B including BSS and minimum heap |
| Text | `0x20000000–0x20019280`, 103,040 B |
| rodata | `0x20019280–0x2001eb2c`, 22,700 B |
| binary_info | `0x2001eb2c–0x2001eb44`, 24 B |
| data | `0x2001eb50–0x2001f82c`, 3,292 B |
| BSS | `0x2001f830–0x200208c0`, 4,240 B including ledger context, USB and system globals |
| malloc | `0x200208c0–0x20038000`, 96,064 B (93.81 KiB) total capacity, not an additional allocation |
| Core 0 stack | `0x20038000–0x20040000`, 32,768 B, NOLOAD |
| Real SCRATCH_X/Y | `0x20040000–0x20042000`, 8 KB, not used as additional application heap |
| Flash | no section in `0x10000000+`, no flash-programming code linked |

Candidate ELF SHA-256:
`939ea2abe57a81ea48a08e650d04f5b8ad09c1d824650715b3fe8465185b7b4f`.
Candidate UF2 SHA-256:
`3399a06b6877ea90099ee236dadcac3d185118b6aa38ac802195809e19633e39`.
UF2 has 505 blocks. These identify the locally built candidate only; a rebuild
must be verified and identified independently before any loading approval.

The SDK default no_flash linker script is SHA-256 pinned in CMake, then two
memory-region values are changed: main RAM ends at `0x20038000`; the script's
SCRATCH_Y-named region is repurposed as a 32 KB **main SRAM** stack. It is not the
physical 4 KB SCRATCH_Y bank. Main malloc cannot grow into that stack; the linker
heap limit and `__StackLimit` both stop at `0x20038000`. The `.heap` NOLOAD section
reserves the SDK's minimum 2 KB inside the malloc range; it must not be added
again to available-memory calculations.

Do not use the aggregate `size` text column as the firmware code footprint: this
linker's `.stack_dummy` can appear there despite being NOLOAD. Section flags and
program headers are the source of truth. The Wren VM and application allocations
are dynamic, not part of BSS.

Largest final `-fstack-usage` frames are in `rp2040-stack.txt`. The upstream
compiler's method frame is about 12.6 KB, `methodCall` about 6.4 KB and
`wrenCompile` about 6.4 KB. A compile → method → nested closure chain can already
consume approximately 25.3 KB, plus helper frames, C host, exception frame and
USB IRQ stack. A conventional 4 KB Pico stack is unsuitable. **32 KB is a
provisional reservation for these shallow fixed scripts, not a proven bound for
arbitrary user programs.** Compiler nesting is recursive and not bounded by this
experiment. Wren VM value/fiber stacks are heap allocations, separate from the
native C stack. MPU guards and a painted high-water measurement are enabled;
only a completed approved run could establish an observed device peak.

## VM budgets and likely OOM

The embedded configuration is initial GC threshold 16 KB, minimum 8 KB, 25%
growth, separately enforced requested-byte budgets 1 KB (fault injection),
32 KB, 64 KB and 96 KB. Each runs the same ten workload sources twice, with
extra repeat/GC/error checks in hello. The 128 KB cap cannot be supported by
the current SRAM allocator range and is tested on the PC/ARM emulator instead.

ARM allocation emulation gives 74,908 B requested-live initialization,
98,239 B full-suite requested peak, 116,391 B peak including ledger headers,
and an even larger newlib malloc arena. These are not RP2040 runtime results.
Even an ideal allocator would have insufficient contiguous main SRAM for this
suite in the current layout; a real allocator also needs headers, rounding,
realloc growth and fragmentation space. The 96 KB cap is not a promise that
96 KB can actually be allocated. System malloc failure triggers whole-VM discard
and is distinguished from hitting the requested-byte cap.

This target can test OOM containment and recovery after approval, but **full
runtime acceptance remains open until an offline-validated candidate can fit all
workloads**. Do not reduce stack below the compilation requirement to force a
positive memory result. A smaller image/allocator is future experimental work;
putting code in flash would require a different authorization and is excluded.

## Offline UF2 checks

`tools/verify_image.py ELF UF2 --selftest` independently parses ELF32 headers and
UF2 blocks using Python's standard library. It checks ARM/Thumb entry at the
lowest SRAM address; all allocated sections and PT_LOAD ranges inside
`0x20000000–0x20042000`; no XIP/cache aliases or flash targets; exact UF2 magic,
family `0xe48bff56`, flags `0x2000` (family present only), 256-byte payloads,
unique/complete numbering and target addresses; first block selects SRAM;
byte-for-byte ELF payload equality and zero padding. Eight mutations are rejected:
first/later flash target, NOT_MAIN_FLASH flag, SRAM overflow, wrong family,
wrong count, duplicate block number and altered payload.

The final symbol record contains no `flash_*` or `rom_reset_usb_boot*` function.
UART is disabled. USB CDC is enabled with both 1200-baud and vendor reset paths
disabled. No KAGURA/FPGA driver, GPIO application IO, filesystem, MicroPython or
flash programming implementation is linked. SDK references to flash-related
interface macros do not imply programming code is present; inspect final symbols
and the load image.

## Approved run protocol (future, not executed)

The reference procedure is the C Desktop SRAM experiment at commit
`be344f5c742101f0cff170a29f63d09c0a17c441`,
`experiments/c-gem-desktop/pico/README.md`. Its verifier/loader is not assumed to
be reusable: it expects KDRP markers, different heap/stack assumptions and a
different binary. Wren uses the following protocol instead:

1. Enable watchdog (8 s) first in `main`, replacing RAM-boot scratch magic;
   select 125 MHz; paint stack below current SP; initialize USB.
2. Wait at most about 60 seconds for USB and `g`, feeding watchdog while waiting.
   On timeout, reboot to installed flash firmware.
3. Print `WR_INFO` clock/linker layout, workload `RESULT` lines and `WR_BUDGET`
   statuses. Feed watchdog between workloads/callbacks; keep USB interrupts
   enabled. Timings include normal SDK interrupt activity, not cycle isolation.
4. Print `WR_MEMORY` conservative stack high-water, stack capacity, malloc arena,
   live libc allocation and program break, followed by `WR_DONE`.
5. Reboot to flash on `r` or after 10 seconds. A hang/hard fault also returns by
   watchdog; power cycling discards all SRAM and boots the existing firmware.

Before any hardware action, approval must identify the exact ELF/UF2 hashes and
whether the scope is **OOM/recovery feasibility only** or a later full-suite
candidate. A memory-failed candidate cannot receive a full-suite PASS label.

The approved operator/loader must perform all of these gates:

1. Verify exact candidate hashes and rerun offline verifier. Inspect final
   watchdog, USB reset flags, SRAM load ranges, stack and allocator budget.
   Close other serial sessions; identify exactly one intended RP2040 device.
2. Use the installed MicroPython for read-only whole-flash SHA-256 and a fresh
   full-flash backup; verify the saved backup independently. Determine flash
   extent from this device/firmware, not a guessed size. Do not assume a past
   Desktop backup hash is still current.
3. Normal control reboot, verify MicroPython/console recovery and repeat the
   full-flash hash. Stop if the hashes differ; boot code may write to flash.
4. Only after approval and all gates, enter BOOTSEL, confirm `Board-ID: RPI-RP2`,
   verify the **new Wren** UF2 against its ELF again, then copy only that verified
   RAM-address UF2. Never run `picotool load` without explicit SRAM validation.
5. Capture USB CDC at 115200, never 1200. Send `g`. Save complete UTF-8 raw log,
   clock, layout, every workload/budget/cycle, allocation metrics, failures,
   explicit GC timings, final malloc and stack metrics. Use a bounded timeout;
   absence of `WR_DONE` is failure, even if a few results printed.
6. For full acceptance: require all expected workload checks, foreign counts,
   expected ordinary errors plus recovery, zero shutdown allocations, no
   unexpected OOM, no stack guard hit and adequate measured stack/heap headroom.
   Compare checksums to host, not host timings. Budget-induced OOM must discard
   all blocks and allow a fresh VM; the intentionally tiny budgets may fail.
7. Send `r`; confirm installed MicroPython version and console are back. Repeat
   whole-flash hash and require equality with both pre-run/control hashes. Keep
   full backup and logs. No firmware reflashing is part of this procedure.

If USB never enumerates or a test hangs, allow watchdog recovery; unplug/replug
if necessary. If BOOTSEL remains after an incomplete transfer, power-cycle into
the installed firmware. If the flash hash differs, stop and preserve evidence;
do not automatically write a backup or claim restoration. Any flash restore is
a separate action requiring explicit authorization.
