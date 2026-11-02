# Stage 5 validation and memory comparison

## Scope and provenance

This stage used host GCC, sanitizers, Cortex-M0+ CPU emulation/newlib and a
flash-resident Pico build. **No device was accessed, flashed or executed.**
Physical figures below come from #72's retained historical evidence; they are
not measurements of the Stage 5 artifact. The 46-pixel thin-red-outline HDMI
colour-classification discrepancy remains unresolved with original thresholds.

Base: e2ff7ead9144136e95096a92e0d024ee051b3f66, whose source candidate is
25c7e9c. Native GUI, text engine/bridge, Wren adapter, transport, Pico main/HAL,
MicroPython, firmware/RTL/FPGA ABI and all existing test C sources are unchanged.
The sole existing-file change is the optional app-generator destination; its
default behavior and generated source bytes are verified unchanged.

Build pins: Pico SDK 2.2.0 a1438dff1d38bd9c65dbd693f0e5db4b9ae91779;
TinyUSB 86ad6e56c1700e85f1c5678607a762cfe3aa2f47; Arm GNU 14.2.Rel1;
CMake 3.31.6 for Pico; Wren 99d2f0b8fc2686134b32b18166e037639f7e9f2c.
Host and emulator tool versions are in `results/toolchain.txt`.

## Host and emulator evidence

| Suite | Release | ASan/UBSan Debug |
|---|---:|---:|
| Consolidated targets (text/native/application/Wren) | 8/8 | 8/8 |
| Reference #70 native GUI/foreign API | 18/18 | 18/18 |
| Reference #71 Japanese text/native GUI | 21/21 | 21/21 |
| Reference #72 Japanese Wren integration | 5/5 | 5/5 |
| Reference #69 Wren lifecycle/allocator correctness | 1/1 | 1/1 |
| Native-only configure, no Wren target/library | 5/5 | — |

111 CTest invocations passed. Mutation cases intentionally reject faulty GUI
variants using the existing WILL_FAIL tests; these remain part of the native
suites. SDL interactive smoke is not selected (`KD_SDL=OFF`); no interactive or
physical display acceptance is claimed. Sanitizers use leak detection and halt
on error; OOM/failure-injection assertions are unchanged.

`results/equivalence.json`: all seven normal and ten overlap/reveal/move frame
CRCs match the fresh #72 host reference; fourteen Wren/native streaming PGM files
are byte-identical to the reference, and the three native Japanese title demo
files match #71. Existing ASCII-vs-#70 CRC assertions and every ASCII glyph/profile
regression execute unchanged. The native-only application links the same owner
and direct sink, executes four events and matches the seven Wren reference
CRCs. Native archives have no Wren/MicroPython/malloc/realloc/free dependency.
This proves build/link separation, not that host mocks model real FPGA timing.

CPU-only ARM runs reuse every original acceptance assertion: integration tests,
20 cycles each of normal/cover/native-malloc-failure recovery/payload-budget
failure recovery, payload budgets 1/32,768/65,536/90,000/98,304/131,072 and arena
capacities 96,064/122,880/135,168; fixed-binary minimum searches. Each successful
cycle executes ten rounds, 161 foreign calls and at least 61 counted collections,
verifies Japanese output, closes native ownership and frees all ledger blocks.
Failure-then-fresh-VM cases recover under the same bounded arena. Cortex-M0+
emulation does not model USB, interrupts, FPGA or execution latency.

## SRAM layout: estimate versus linked result

Before measuring, this build-only step estimated zero Flash/static/arena/stack/
recovery growth because runtime source and options were preserved. Actual
growth in every category is **zero** relative to #72. Full sections, symbols,
program headers and map are under `results/`; `memory.py` reruns the original
image/range/forbidden-symbol assertions and checks font storage in Flash.

| Item | #72 baseline | Stage 5 linked | Delta |
|---|---:|---:|---:|
| Flash load payload | 227,480 | 227,480 | 0 |
| Static SRAM (vectors + data + bss) | 45,596 | 45,596 | 0 |
| Bounded native Wren arena | 135,168 | 135,168 | 0 |
| Core 0 stack reservation | 49,152 | 49,152 | 0 |
| Recovery reservation | 8,192 | 8,192 | 0 |
| Total reserved of 270,336 | 238,108 | 238,108 | 0 |
| Unassigned main RAM | 24,036 | 24,036 | 0 |
| Unused scratch X / Y | 4,096 / 4,096 | 4,096 / 4,096 | 0 |
| Total unassigned | 32,228 | 32,228 | 0 |

| Half-open address range | Bytes | Ownership |
|---|---:|---|
| `0x20000000–0x200000c0` | 192 | RAM vector table |
| `0x200000c0–0x20001900` | 6,208 | `.data`, including SDK/newlib/USB initial state |
| `0x20001900–0x2000b21c` | 39,196 | `.bss`, including one Desktop, runtime, USB/SDK buffers |
| `0x2000b21c–0x2002c21c` | 135,168 | Native malloc arena; `__HeapLimit == __StackLimit` |
| `0x2002c21c–0x20032000` | 24,036 | Contiguous unassigned main address range; not automatically arena space |
| `0x20032000–0x20034000` | 8,192 | NOLOAD recovery reserve |
| `0x20034000–0x20040000` | 49,152 | Core 0 stack; SDK stack guards retained |
| `0x20040000–0x20041000` | 4,096 | Scratch X unassigned/reserved by policy |
| `0x20041000–0x20042000` | 4,096 | Scratch Y unassigned/reserved by policy |

The 2,048-byte `.heap` NOLOAD marker starts at `0x2000b21c` and is **inside**
the 135,168-byte arena, not another allocation. Core 1 and scratch sections are
empty. Main RAM is word-interleaved across SRAM0–3: unassigned contributions
6,008/6,008/6,008/6,012 B; scratch X/Y are separate banks. Do not call the total
32,228 B a single available heap or allocate the recovery reserve.

`desktop_state` is 34,284 B, including `kd_desktop` 34,160 B, whose 32,000-byte
framebuffer, 1,280-byte shared scratch, dirty map and GUI state are already
counted. There is no second CPU framebuffer or full-screen TILE4 staging buffer.
Other named static objects include `runtime` 312 B, timing spans 192 B,
newlib malloc bins 1,032 B, SDK `rules` 1,280 B, USB `hw_endpoints` 1,024 B,
vendor interface 588 B, vendor/CDC endpoint buffers and control state. SDK
`rules` is not a Desktop tile buffer. All named static objects and padding/
archive contributions are available in the complete map; do not sum selected
large symbols as if that were the complete static footprint.

Flash: boot2 256 B; `.text` 123,756 B; `.rodata` 97,228 B; binary info 28 B;
initialized `.data` load image 6,208 B.
The Flash segment also contains 4 B of alignment padding between text and rodata.
Entry `0x100001e9`; Flash load data ends `0x10037898`. Font bytes occupy
`0x10023ff0–0x10035816` and its 24-byte descriptor is also in Flash.
This is a flash-resident build, not suitable for the previous SRAM-only loader.
No UF2 or hardware programming target is produced.

`results/load-equivalence.json` compares a fresh build of the old #72 entry
point in this same checkout against the new entry point: **every PT_LOAD
address, memory size, flags/alignment and initialized byte matches**. Whole ELF
hashes differ because nonloaded build/debug information differs. Both hashes
and per-segment hashes are retained. This static identity is stronger than
equal size, but still does not constitute new physical acceptance.

## Heap and stack observations

| Metric | #72 physical, historical | #72 ARM, historical | Stage 5 ARM |
|---|---:|---:|---:|
| Wren payload peak | 91,994 | 91,994 | 91,994 |
| Payload + ledger peak | 111,418 | 111,418 | 111,418 |
| Native arena backing high-water | 126,436 | 128,648 | 128,640 |
| Painted stack upper usage | 33,848 | 33,648 | 33,648 |
| Shutdown tracked live / blocks | 0 / 0 | 0 / 0 | 0 / 0 |

The 8-byte emulator backing difference is alignment, not an optimization:
historical arena base `0x44978` + 128,648 and new base `0x44980` + 128,640
both reach `0x64000`. Do not spend it as capacity. The emulated fixed-workload
payload minimum is 91,994 B; native capacity minimum 128,640 B is specific to
this executable's alignment/newlib and is **not** a general Wren minimum or a
new hardware-safe budget. The configured payload budget remains 98,304 B and
arena remains 135,168 B. At the new emulated peak, arena headroom is 6,528 B;
historical physical headroom was 8,732 B. Fragmentation/metadata are included in
backing and must not be inferred by subtracting peaks reached at different times.

Stack reservation stays 49,152 B. Historical physical painted margin is 15,304 B;
new emulated margin is 15,504 B. Neither is a worst-case recursion/interrupt
proof. Compiler frames include Wren `method.isra` 12,568 B, `methodCall` 6,392 B,
`wrenCompile` 6,360 B, native compositor render 880 B and `kj_draw` 200 B.
Individual `.su` frames are not additive whole-program stack maxima. Keep the
48 KiB reservation and guards; additional callbacks/features need new evidence.

## Result and limits

Minimal consolidation is safe within the validated static budget; source
boundaries support independent native C use and shared Japanese rendering.
This step removes monolithic build coupling, not experimental source-path
ownership. No Japanese GUI features or runtime semantics were added. The next
steps are small source-ownership migrations and a separately reviewed bounded
native text API, followed by one GUI role at a time. Follow the dependency/risk
plan rather than merging the experiments wholesale.
