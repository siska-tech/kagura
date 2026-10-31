# MicroPython SDK: reusable per-frame operations

## Scope and contracts

This change is independent of the cherry-blossom demo. It adds `ext_writes(pairs)`
alongside `audio_writes(pairs)`, reuses register scratch buffers, avoids transient
argument tuples/views in frequently called operations, and sends scalar register
reads/writes directly through the existing Link ownership/recovery wrapper.
No new scalar, sprite, drawing or synchronization API is needed.

The public signatures and keyword calls remain supported. `busy` is held across
compound operations and restored in `finally`; Link checks closed/reentrant use,
aborts on `BaseException` including Ctrl-C, and retains READY, FIFO timeout,
device error and STATUS timeout translation. `accelerate=False` and closing an
acceleration session retain the Python path. The implementation does not disable
GC or change the PIO, ABI, FPGA, MicroPython runtime or firmware on the board.

`ext_writes` takes an even-length byte buffer of index/value pairs. Odd lengths
raise `ValueError('EXT pairs: index, value bytes')`. The accelerated kernel keeps
each pair as an INDEX/DATA transaction, in order, under one device ownership
scope. Arbitrary registers and values retain the old `ext_write` validation on
the fallback path. It follows the existing `audio_writes` buffer convention.

## Reuse in an editor or animation

An OAM batch is already supported by `write_memory`; keep one 2048-byte
`bytearray`, write the eight-byte records into it, then upload it once. For a
fixed partial selection, keep a `memoryview` slice made during initialization.
Do not construct `Video.sprite` records 256 times on every frame when an editor
already owns packed OAM. `Video.sprite` remains the convenient checked API for
individual edits. Call `fence()` before claiming queued memory writes completed.

```python
from kagura import regs as R
oam = bytearray(R.VRAM_OAM_SIZE)  # initialize records before entering the loop
scroll = bytearray((R.EXT_SCROLL_X_L, 0, R.EXT_SCROLL_X_H, 0))

# For each frame: update oam and scroll in place, then:
d.wait_status(R.STATUS_COMMIT_BUSY, 0)  # previous shadows were applied
d.write_memory(R.VRAM_OAM_BASE, oam)
d.ext_writes(scroll)
d.commit(wait=False)
# The next successful COMMIT_BUSY wait confirms this commit was applied.
```

`commit(wait=False)` alone does not prove a displayed frame. Keep processing,
STATUS polling/synchronization and telemetry read time separate when measuring.
The example assumes a single owner; do not overlap edits to a buffer with its
synchronous upload or publish an incomplete group of shadow writes.

For fixed-buffer drawing, existing `TileFramebuffer.fill_rect`, drawing methods,
dirty tiles and `flush` already provide reusable buffers and failure recovery.
The cherry-blossom HUD's font atlas, number rounding, field positions, shadows,
petal motion and sound scheduling remain in the demo. They are not SDK primitives.
No generic text-layout engine or additional OAM buffer class is introduced.

## Measurement

`examples/driver_benchmark.py` measures public API operations with GC enabled,
preallocated samples and OAM. Pass an idle connected device; the benchmark
overwrites OAM/scroll, publishes commits and checks errors. Warmup and explicit
GC occur before each measurement window. `net_heap` is the signed difference of
`gc.mem_alloc()`, **not total allocation**. Collections and explicit frees can
hide allocations; this benchmark does not claim total allocation zero.

On the standard MicroPython VM, larger call frames can allocate on the GC heap
and be explicitly freed on return. Removing argument tuples is useful but does
not remove those frames. Historical descriptions saying every SDK call
"allocates nothing" referred to net retained heap, and were too broad.
The separate diagnostic VM experiment that observed zero gross allocations
changed a VM stack threshold; that runtime change is not adopted here.

Actual SDK-only A/B (2026-10-31): RP2040 125 MHz, standard v1.26 firmware,
480p FULL+PSRAM FPGA (CAPS 0x5b), QSPI 5 MHz, default acceleration, 200 calls
per case. Each version was compiled with armv6m mpy-cross, mounted in RAM at
the same package path, and started after a soft reset. Firmware was not flashed.
Main and final were repeated; all five runs passed with no device errors.
RAM-loaded SDK timings should not be substituted for frozen-module timings.

| Mean latency (us) | main (#45) | tuple/view reduction | final scalar short path |
|---|---:|---:|---:|
| read_reg | 492–494 | 469 | 383–384 |
| write_reg | 769–770 | 591 | 477 |
| audio_read | 1403–1408 | 1125 | 914 |
| 3 EXT pairs (main: 3 ext_write calls) | 3057–3073 | 540 | 539–541 |
| OAM 2048 B | 2454–2461 | 2435 | 2436–2437 |
| commit(wait=True), including VBlank | 16569 | 16570 | about 16570 |

The final scalar route saves about 18% on reads and 19% on writes over the
tuple/view-only SDK, without a new API. OAM wire throughput and frame period
are essentially unchanged. This does not promise 60 Hz application processing.

`net_heap` for 200 calls on main was 12800/22400/41600/67200/16000/9600 B in
the table's row order; both optimized variants measured 0 B in every case.
These are **net differences**, not gross allocation counts or proof of no GC.
No GC disabling was used. They must not be confused with the demo's cold/warm
display rates or the historical diagnostic VM's zero gross allocation result.

## Regression coverage

The register-model suite runs actual Viper source against PIO/SIO/timer/DMA
models for SPI and QSPI. It covers scalar parity, argument errors, keyword
calls, closed/reentrant ownership, timeout and Ctrl-C recovery, ordered EXT
pairs, full and partial OAM buffer reuse, and existing fence/commit/flush
failure contracts. Host tests establish wire semantics, not RP2040 timing.

Final local checks: 226 host tests passed (driver 62 with actual upstream RP2
assembler, framebuffer 85, Japanese text/font regeneration 34, Link 15,
STAR RUNNER 26, tile fixture 2, transport benchmark 2). All 38 SDK/JA/example
modules compiled for armv6m; generated constants and CI filter self-tests passed.
Raw hardware A/B: [measurement log](measurements/micropython-sdk-2026-10-31.txt).

## Dependencies

Base: main at b8fc45d, after merged PRs #43, #44 and #45. This SDK PR has no
dependency on the cherry-blossom PR. The demo can stack above it and use the
same APIs as other applications. No changes to RTL, ABI or MicroPython core.
