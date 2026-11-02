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

## ELF, SRAM, flash and stack (updated after memory audit)

**The original 32 KiB-stack image is retired and must not be loaded.** Its hashes
and layout in `results/rp2040-*` are historical records. ARM stack painting now
observes up to 39,940 B, so CMake requires at least 48 KiB. The present images are
eligible only as offline memory/OOM candidates; they cannot fit positive runtime
acceptance. See [../MEMORY_ANALYSIS.md](../MEMORY_ANALYSIS.md).

Current exact hashes, ELF headers, sections and symbols are in
`../results/memory-audit/pico-{audit,audit-expanded,lto}-*.txt`. All address ranges
are exclusive at the end. No physical hardware was accessed.

| Layout item | Current default | Optional scratch-expanded |
|---|---|---|
| Thumb entry | `0x20000001` | same |
| File-backed load | `0x20000000–0x2001feac`, 130,732 B | same |
| BSS | `0x2001feb0–0x200211b0`, 4,864 B | same |
| malloc range | `0x200211b0–0x20034000`, 77,392 B | `0x200211b0–0x20036000`, 85,584 B |
| Core 0 stack | `0x20034000–0x20040000`, 49,152 B NOLOAD | `0x20036000–0x20042000`, 49,152 B NOLOAD |
| Actual scratch banks | 8 KiB outside stack, unused | part of core 0 stack; no core 1 launch/data allowed |
| Flash/XIP sections | none | none |

`tools/check_layout.py ELF UF2` independently checks heap/stack boundaries,
48 KiB minimum stack, empty scratch/core-1 sections and forbidden flash/reset/
core-1 launch symbols. It rejects the archived 32 KiB binary. For positive GUI
acceptance, also require `--min-arena 135168`; all current candidates fail that
gate as expected. A layout-only pass is not a runtime-capacity pass.

The script's SCRATCH_Y-named region is repurposed for the larger contiguous
stack; it is not the physical 4 KiB bank. The heap limit and SDK `_sbrk` limit stop
at the stack bottom; the MPU bottom guard remains enabled. New linker assertions
require scratch X/Y data and core 1 stack sections to be empty. Expanded mode
requires core 1 to remain parked in its normal ROM holding pen, with no launch
or FIFO-handshake code linked. Its successful offline address checks do not
establish runtime acceptance or authorize loading.

The SDK minimum `.heap` NOLOAD section reserves 2 KiB inside malloc capacity; do
not count it again. Do not use the aggregate `size` text column as code footprint:
`.stack_dummy` can be counted there despite being NOLOAD. Section flags/program
headers are authoritative. Wren VM/value/fiber stacks are heap allocations;
the recursive source compiler uses the separate native stack.

Largest native frames are recorded in `pico-stack-largest.txt`; individual frame
sizes alone did not predict recursive compiler depth. 48 KiB is a conservative
fixed-suite reservation with IRQ/SDK margin, not a bound on arbitrary user code.
Painted stack high-water, guards and watchdog recovery remain enabled; actual
Pico stack behavior is unmeasured. Wren-only LTO was also evaluated and enlarged
the load image to 131,692 B, reducing allocator capacity by another 960 B.

## VM budgets, smallest profile and failure headroom

GC thresholds remain initial 16 KiB, minimum 8 KiB, growth 25%. They are not a
heap allocation or limit. The embedded program retains the original full suite
with requested-byte caps 1 KiB (intentional OOM), 32 KiB, 64 KiB and 96 KiB.
Physical malloc bounds apply independently and will fail before a requested-byte
cap when the image leaves insufficient room. OOM still discards the entire VM,
never reuses the interrupted VM and reports whether the cap or malloc failed.

The full-suite 98,239 B maximum is requested-live payload, not allocator capacity.
The smallest proposed positive acceptance profile is the additional persistent
`small_gui` model, specified exactly in MEMORY_ANALYSIS.md: Japanese output,
one application/rectangle/four-event model, compiled callbacks into Wren, real
C foreign calls, all existing repeat/GC/error recovery checks and 20 VM lifecycles.
Use a 96 KiB requested-live cap, **132 KiB bounded physical arena** and 48 KiB
native stack, requiring at least 4 KiB observed arena and 8 KiB native-stack
headroom. Its model answer is 173 and it makes 40 C foreign calls per VM.

CPU emulation measures 90,437 B peak payload and 124,240 B allocator minimum for
20 checked GUI lifecycles. 128 KiB arena tests pass 100 lifecycles, including
fresh-VM recovery after a real bounded malloc failure; 132 KiB is the more
conservative proposed hardware allowance for alignment and recovery margin.
These are not device results. A hypothetical 8 KiB increase to the old malloc
region still could not initialize newlib-backed Wren, let alone run this model.

Neither current SRAM-only image has enough allocator space for that profile.
**Do not request positive RP2040 runtime acceptance for these binaries.**
An OOM/boot/watchdog-only test could be separately scoped, but must not be called
GUI or full-suite acceptance. No flash-resident firmware change is authorized.

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
