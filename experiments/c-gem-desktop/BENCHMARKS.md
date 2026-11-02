# Benchmark report: C GEM-style desktop

2026-11-02, branch `experiment/c-gem-desktop`.
Every number is labelled:
- **measured (PC)**: on the development PC;
- **measured (RP2040)**: copied from existing repository records, KAGURA-UI only;
- **counted**: executed Thumb-1 instructions under `qemu-arm`;
- **estimate**: derived, with the assumptions stated.

**No C desktop code was run on an RP2040.** PC timings do not predict RP2040 timings.

## 1. Setup

| | |
|---|---|
| PC | 13th Gen Intel Core i7-1360P, Windows 11, WSL Ubuntu 26.04 |
| C build | gcc 15.2.0 `-O3 -DNDEBUG` (CMake Release), 1,001 samples per workload after 50 warm-up samples |
| KAGURA-UI | main `1dea600`, unchanged; CPython 3.14.4 and MicroPython v1.26.0 unix (the repository's pinned build) |
| Cortex-M0+ counts | arm-none-eabi-gcc 14.2.1 `-mcpu=cortex-m0plus -mthumb -O2`, newlib-nano, libgcc division; QEMU 10.2.1 user mode, one instruction per translation block |

Each C sample runs the operation (an event or API call), `kd_desktop_render`, and then the TILE4 export of every dirty tile into a 40-tile staging buffer and a RAM "VRAM" copy.
"render" is the operation plus composition; "export" is the packing and copy.
- Pixel, damage, tile and byte counts are deterministic.
- Times vary by about 20–30% between runs on this laptop (turbo states), so read them as indications.
- p99 and max include OS scheduling noise.

Commands (repository root, WSL):

```sh
build/c-gem/kd_bench --samples 1001 --json build/c-gem/bench.json
python3 -I experiments/c-gem-desktop/bench/kagura_ui_reference.py --backend sdk --samples 32
MICROPYPATH=software/micropython:software/micropython/examples \
  build/micropython-src/ports/unix/build-standard/micropython \
  experiments/c-gem-desktop/bench/kagura_ui_reference.py --backend framebuf --samples 101
QEMU=/path/to/qemu-arm bash experiments/c-gem-desktop/tools/arm_report.sh build/c-gem-arm
```

## 2. C desktop on the PC (measured)

The scene is the standard one: File Manager and Studio overlapping, with About added where noted.
"changed tiles" is what the export sent.

| workload | render p50 µs | p90 | p99 | max | export p50 µs | pixels | damage rects | damage px | damage tiles | changed tiles | runs | TILE4 bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| idle (no change) | 0.02 | 0.02 | 0.02 | 0.04 | 0.47 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| full redraw, 3 windows | 68.76 | 75.31 | 109.68 | 190.23 | 0.48 | 77,204 | 1 | 64,000 | 1,000 | 0 | 0 | 0 |
| full redraw, painter's | 150.97 | 164.10 | 256.22 | 2,008.40 | 0.48 | 166,309 | 1 | 64,000 | 1,000 | 0 | 0 | 0 |
| full export (all 1,000 tiles) | 0.02 | 0.03 | 0.03 | 0.04 | 2.92 | 0 | 0 | 0 | 0 | 1,000 | 25 | 32,000 |
| button press/release | 1.43 | 1.50 | 1.56 | 2.77 | 0.68 | 1,809 | 1 | 768 | 18 | 12 | 2 | 384 |
| menu open | 9.07 | 9.52 | 13.80 | 23.95 | 1.32 | 10,556 | 2 | 9,379 | 166 | 162 | 14 | 5,184 |
| menu close | 11.91 | 12.43 | 16.64 | 128.18 | 1.34 | 12,309 | 2 | 9,379 | 166 | 162 | 14 | 5,184 |
| window activation | 29.26 | 37.68 | 42.78 | 81.20 | 1.40 | 24,736 | 3 | 13,828 | 283 | 227 | 17 | 7,264 |
| window move 8 px, live | 121.68 | 130.04 | 209.18 | 400.89 | 1.87 | 90,195 | 2 | 47,244 | 448 | 434 | 23 | 13,888 |
| window move 8 px, outline | 5.64 | 6.06 | 10.58 | 66.07 | 1.14 | 1,991 | 8 | 1,252 | 154 | 154 | 32 | 4,928 |
| outline drop (window moves 8 px) | 128.31 | 157.64 | 241.57 | 3,090.39 | 2.02 | 90,195 | 2 | 47,244 | 448 | 434 | 23 | 13,888 |
| one-character label | 0.57 | 0.59 | 0.62 | 11.96 | 0.63 | 128 | 1 | 64 | 4 | 3 | 2 | 96 |
| one sprite pixel | 1.30 | 1.37 | 1.42 | 9.28 | 0.76 | 123 | 3 | 41 | 3 | 3 | 3 | 96 |
| full sprite import | 42.35 | 44.39 | 51.82 | 64.12 | 1.07 | 26,826 | 3 | 10,496 | 203 | 146 | 17 | 4,672 |
| overlap recompose, 160x120 over 3 windows | 19.39 | 19.94 | 27.16 | 214.18 | 0.47 | 24,915 | 1 | 19,200 | 315 | 0 | 0 | 0 |
| same, painter's | 85.52 | 89.06 | 95.89 | 134.61 | 0.48 | 86,896 | 1 | 19,200 | 315 | 0 | 0 | 0 |
| pointer move 4 px (software cursor) | 1.47 | 1.54 | 1.80 | 8.01 | 0.65 | 606 | 2 | 352 | 9 | 6 | 3 | 192 |

Observations:

- **Visible rectangle lists halve or better the work of the painter's algorithm.**
  - Full redraw: 77 k pixels processed against 166 k (2.2x fewer), 2.2x faster.
  - Overlapping recompose: 25 k pixels against 87 k (3.5x fewer), 4.4x faster.
  - Pixels processed exceed damage pixels only through overdraw inside window content (background fill, then content).
- **Redundant redraws send nothing.** A full redraw or recompose of an unchanged screen exports 0 tiles, because of the exact dirty map (ARCHITECTURE.md section 3).
  A real full-screen change sends 1,000 tiles in 25 runs (32,000 B).
- **Small interactive updates touch 3–12 tiles** (96–384 B).
- **Live window moves are the outlier:** they damage the old and new frames (47 k pixels, 434 tiles, 13.9 KB per 8 px step).
  Outline drag costs 154 tiles per step, and its 32 runs are thin edges. The outline is drawn into the framebuffer; a hardware-sprite outline or cursor would need an OAM allocation that does not exist today.

## 3. KAGURA-UI on the PC (measured)

The unchanged KAGURA-UI ran the `examples/ui_benchmark.py` layout and operations (the RP2040 records below use the same ones), plus the #67 sprite editor.
- **sdk:** the real SDK `TileFramebuffer` over the register model, which gives exact SDK tile and payload counts; raster in pure Python.
- **framebuf:** MicroPython's native `framebuf` as the raster, standing in for the Viper kernels; measures widget, layout and VM overhead.

| workload | CPython + SDK p50 µs | tiles | pattern bytes | MicroPython + framebuf p50 µs |
|---|---:|---:|---:|---:|
| full redraw, gallery (4 widgets) | 5,468 | 51 | 1,632 | 64 |
| button press (Enter, label update) | 432 | 7.8 | 250 | 62 |
| one-character label | 80 | 1 | 32 | 22 |
| panel move 4 px | 556 | 20 | 640 | 17 |
| full redraw, sprite editor | 14,867 | 491 | 15,712 | 12,452 |
| one sprite pixel | 99 | 3 | 96 | 32 |
| full sprite import | 7,062 | 278 | 8,896 | 470 |

## 4. Comparison

### 4.1 Same PC, same kind of operation (measured)

| operation | C desktop µs | KAGURA-UI, MicroPython + native framebuf µs | ratio | tiles: C / KAGURA-UI SDK |
|---|---:|---:|---:|---:|
| one sprite pixel | 1.30 | 32 | 25x | 3 / 3 |
| one-character label | 0.57 | 22 | 39x | 3 / 1 |
| full sprite import | 42.4 | 470 | 11x | 146 / 278 |
| full redraw (C: 3-window desktop; KAGURA-UI: sprite editor screen) | 68.8 | 12,452 | 181x | 0 / 491 |

Caveats:
- **The screens are not identical.** The C Studio grid is 96x96 (zoom 6); the KAGURA-UI grid is 128x128 (zoom 8) on a 320x240 screen.
  The C desktop full redraw composes three windows, icons and a menu bar, which is more content than the sprite editor screen.
- **The import difference partly reflects geometry and partly the exact dirty map.**
- **The label difference** comes from glyph cells straddling tiles in the C Studio label (x=108 is not tile aligned).

### 4.2 Cortex-M0+ (counted, estimate)

`tools/arm_report.sh` builds the same workloads (`bench/workloads.h`) for Cortex-M0+ (Thumb-1, no divide instruction) as a freestanding Linux ELF (`bench/arm_count.c`). It runs them under `qemu-arm` one instruction per translation block, and counts executed instructions for N samples with and without the operation.
Two complete runs gave identical counts.

**Estimate** of RP2040 time = instructions x CPI / 125 MHz, with CPI 1.2–1.6. Cortex-M0+ executes ALU operations in 1 cycle and loads, stores and taken branches in 2.
What the band leaves out:
- **Pessimistic.** newlib-nano's byte-wise `memcpy`/`memcmp` and libgcc's software division were counted; the Pico SDK would use the boot ROM memory routines and the hardware divider.
- **Optimistic.** It ignores XIP flash cache misses (hot code could be placed in SRAM) and bus contention from DMA.

| workload | instructions (counted) | RP2040 ms (estimate) | KAGURA-UI on RP2040 (measured) |
|---|---:|---:|---|
| one-character label | 37,506 | 0.36–0.48 | label: frame 21.5 ms (`ui_benchmark`, damage limit 1) |
| software cursor 4 px | 57,889 | 0.56–0.74 | (no pointer) |
| one sprite pixel | 68,538 | 0.66–0.88 | paint: frame 21.9 ms = CPU 19.5 + flush 2.4 (#66); 22.2 ms after #67 |
| button press/release | 69,927 | 0.67–0.90 | button: frame 39.0 ms (includes a label update) |
| window move, outline | 457,297 | 4.4–5.9 | (no windows) |
| full export, 1,000 tiles | 624,884 | 6.0–8.0 | (transport below) |
| overlap recompose 160x120 | 904,370 | 8.7–11.6 | |
| menu open / close | 921,223 / 937,196 | 8.8–12.0 | (no menus) |
| window activation | 1,187,394 | 11.4–15.2 | |
| full sprite import | 1,321,747 | 12.7–16.9 | 323 ms including `import_hex()` (#67) |
| full redraw, 3 windows | 2,829,399 | 27.2–36.2 | sprite editor screen: frame 213.5 ms (#67) |
| overlap recompose, painter's | 2,942,563 | 28.2–37.7 | |
| window move, live | 4,840,769 | 46.5–62.0 | (no windows) |
| full redraw, painter's | 5,173,575 | 49.7–66.2 | |

The KAGURA-UI column is the existing record (`docs/kagura-ui-damage.md`, `docs/kagura-studio-sprite-editor.md`): RP2040 at 125 MHz, MicroPython v1.26 with Viper, QSPI 5 MHz, 320x240.
The C column has no transport time. The flush stays the SDK's or a C equivalent: the paint flush is **measured** at 2.4 ms for 3 tiles, and the TILE4 wire time is at least 12.8 µs per tile at 4 x 5 MHz (**estimate**, wire only).

Where the instructions go (per-function difference of the qemu trace, **counted**):

| workload | top functions (instructions) |
|---|---|
| full redraw | `memcpy` 477 k, `kd_fb_mono` (glyphs) 415 k, `span` 411 k, `memcmp` 232 k, `clip_box` 209 k, `kd_tile4_pack_tile` 166 k, `__udivsi3` 134 k |
| window move, live | `span` 854 k, `kd_fb_pattern_rect` (checkerboard) 787 k, `kd_fb_blit_tile4` 746 k, `memcpy` 571 k, `clip_box` 246 k, `__udivsi3` 152 k |
| sprite import | `kd_fb_pattern_rect` 196 k, `kd_fb_blit_tile4` 187 k, `span` 127 k, `memcpy` 81 k |

About 30% of a full redraw is the exact-dirty snapshot and compare (`memcpy`, `memcmp` and packing 4-byte tile rows).
The rest is dominated by per-pixel paths:
- glyphs, the 8x8 pattern fill and the zoomed blit;
- the blit's per-pixel division (Cortex-M0+ has no divide instruction).

These are the obvious targets for an optimisation phase, which was not started.

Code size (**measured**, arm-none-eabi-size, objects):

| | Cortex-M0+ `-O2` | Cortex-M0+ `-Os` | Cortex-M33 `-O2` |
|---|---:|---:|---:|
| core (`src/`), including 1,536 B fonts | 22,610 B | 17,816 B | 21,238 B |
| demo apps (`apps/`) | 7,916 B | 6,686 B | 7,792 B |
| `.data` / `.bss` | 0 / 0 | 0 / 0 | 0 / 0 |

Largest stack frames, Cortex-M0+ `-O2` (**measured**, `-fstack-usage`):
- `kd_desktop_render` 896 B (damage copy, snapshot flags, inlined region compositor);
- `damage_from` 472 B;
- `menu_hook` 288 B;
- `kd_filemgr_open` 280 B;
- `compose_painter` 216 B.

Peak stack is about 2 KB (**estimate**, the deepest chains added up by hand).

## 5. Memory (measured)

| | x86-64 | 32-bit ARM |
|---|---:|---:|
| `kd_fb` | 32,148 B | 32,148 B |
| `kd_desktop` | 34,416 B | 34,160 B |
| `kd_shell` (all demo apps) | 35,272 B | 34,792 B |
| `kd_region` (stack, compositor) | 386 B | 386 B |
| `kd_event` | 20 B | 20 B |
| heap allocation in core and apps | none | none |

Code size, stack frames and the M0+ profile are in section 4.2. Steady-state memory equals peak memory: nothing is allocated after start-up, and the hosts allocate only image buffers for screenshots.
KAGURA-UI on RP2040 (**measured**, `docs/kagura-ui.md`):
- `TileFramebuffer` constructor: 40,544 B of GC heap, needing a contiguous 38,400 B block;
- gallery App/Theme/tree: 3,984 B;
- per step: allocates (0.4–0.6 KB per Tab dispatch on unix MicroPython).

The C desktop's RAM is static and does not grow at run time.
