# Architecture evaluation: a native C core for KAGURA Desktop?

Decision report for the experiment on branch `experiment/c-gem-desktop` (2026-11-02).
Evidence is labelled:
- **measured (PC)**: this experiment, on a PC;
- **measured (RP2040)**: existing repository records of KAGURA-UI;
- **counted**: Cortex-M0+ instructions under `qemu-arm`;
- **estimate**: derived.

No C desktop code ran on an RP2040 or RP2350, and nothing here is a hardware measurement of the C desktop.
Details are in [BENCHMARKS.md](BENCHMARKS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Summary

The prototype works: a 320x200 GEM-style desktop with:
- overlapping windows, menus, live and outline drag, keyboard and mouse;
- a File Manager mock and a TILE4 sprite Studio;
- a TILE4 export that the repository's own C and Python readers decode identically;
- 25 tests plus 13 mutants that the tests kill.

On the evidence, the rendering, composition, damage and TILE4 export core is a good candidate for native C. Rewriting KAGURA-UI is not justified yet.
**Recommendation: a hybrid.** Validate the C core on RP2040 hardware first. If the estimates hold, add it as a native module under MicroPython, with Python remaining the application layer.
The current KAGURA-UI stays as it is until then.

## Answers

### Which parts of KAGURA-UI are good candidates for native C?

Those whose cost grows with pixels or with the number of damage rects and layers:

- **Raster primitives and glyph drawing.**
  - KAGURA-UI already has Viper kernels, but each SDK call has a fixed cost: **measured (RP2040)** `fill_rect` 1.16 ms for 96x16 and 1.41 ms for 304x32; a 1x1 damage rect costs 5.7 ms to recompose.
  - In C a whole small update is **counted** at 38–70 k instructions (**estimate** 0.4–0.9 ms on RP2040, including export packing).
- **Composition and damage.** KAGURA-UI recomposes the widget tree in Python for each damage rect, which is why it defaults to a single bounding rect (`damage_limit=1`). Per-rect fixed costs of about 2.4 ms made several rects slower (**measured (RP2040)**).
  The C compositor's visible rectangle lists cost tens of microseconds on the PC and cut pixel work by 2.2–3.5x against the painter's algorithm (**measured (PC)**).
- **Exposure handling for overlapping windows.** It must not enter the VM. In C, raising, moving, menu close and exposure never call application code that runs Python.
- **Dirty-tile tracking and TILE4 packing.** Both are already native in `tile_fb.c`; the C desktop adds an exact dirty map despite overdraw.

### Which parts should remain in MicroPython?

Application logic and content:
- what windows exist and what they show;
- event handling and callbacks;
- file and device access;
- layout of application content;
- the sprite editor's undo, import and export policies.

Also the widget toolkit's high-level API (labels, buttons, lists as Python objects), but backed by retained native records rather than per-frame Python drawing.
Keep Python where iteration speed matters more than microseconds. Keep KAGURA-UI itself for full-screen applications that do not need windows.

### How much memory would a 320x200 GUI require on RP2040 and RP2350?

**Measured** sizes on 32-bit ARM:

| | RAM | Flash |
|---|---:|---:|
| framebuffer | 32,000 B | |
| whole desktop state (8 windows, damage, menus, exact-dirty snapshot) | 34,160 B | |
| demo app state | 632 B | |
| TILE4 staging (one tile row) | 1,280 B | |
| peak stack, **estimate** from per-function frames (largest 896 B) | about 2 KB | |
| core code, Cortex-M0+ `-O2` (fonts included) | | 22.6 KB |
| core code, Cortex-M0+ `-Os` | | 17.8 KB |
| demo apps | | 7.9 KB |

That is about 38 KB of RAM on either chip: about 14% of RP2040's 264 KB and about 7% of RP2350's 520 KB.
It is static, outside the GC heap, and needs no contiguous heap block at run time.
KAGURA-UI today needs about 40.5 KB of GC heap for its 320x240 framebuffer (**measured (RP2040)**) plus its widget tree.
A MicroPython binding would add a display-list pool and event rings, for example 4–8 KB (**estimate**), and its own module code.

### What additional buffers are needed for overlapping windows?

None, in this design: the compositor recomposes exposed areas from application state (tested to give the same pixels as a full redraw after every step of random sequences).
- Optional buffers, not used: a backing store per window (w*h/2, for example 12 KB for 200x120) and a menu save-under (about 4.5 KB).
- The only extra working memory is the 1,280 B snapshot that keeps the dirty map exact, and a 386 B rectangle list on the stack.
- Backing stores would make Python-drawn windows cheaper to expose, but at a RAM price the RP2040 cannot pay for many windows. Retained display lists are the better trade.

### Can a single framebuffer serve all applications?

Yes. Every application draws through `kd_draw`, which the compositor clips to the visible part of its window, so applications cannot overwrite each other or the chrome.
One 32,000 B plane and one 1,000-pattern export serve every window.
The condition is that the desktop is the single owner of patterns 0..1000, the BG map, scroll and BACKDROP, which is the same exclusivity KAGURA-UI's `App(exclusive=True)` already declares.
Console, `TextLayer` and independent sprites cannot share the screen with it without an allocation API that does not exist today.

### How should mouse and keyboard events cross the C/MicroPython boundary?

- As 20-byte POD `kd_event` values (no pointers) in a fixed ring per window, filled by C and drained by Python from its main loop (`desk.step()`, then `win.events()`).
- Never as callbacks into the VM from input, IRQ or compositor context.
- Overflow drops the newest event and counts it, as KAGURA-UI's `EventQueue` does.
- Pointer coordinates arrive already translated to work-area coordinates. Focus, blur and menu choices are events too.
- Two gaps on the hardware side: KAGURA has no mouse input today, so pointer events need a HID or serial mouse source; and key releases are not reported by the UART path, which the desktop does not need.

### Is a native window manager practical without unacceptable firmware complexity?

Yes, at this size:
- the core is about 2,400 lines of C with no allocation, globals, floating point or recursion, 18–23 KB of code;
- the compositor is the most complex part and the best tested: invariant checks over random sequences, painter cross-check, mutants;
- for scale, KAGURA-UI is 1,325 lines of Python.

The real complexity is in integration, not the window manager: a MicroPython user C module, a resource lease, a transport path, input sources.
Two warnings from the counts (**estimate**, Cortex-M0+ at 125 MHz):
- **Live window dragging** would take about 46–62 ms per step at today's code quality. Outline drag (about 4.4–5.9 ms) is the practical default.
- **Full redraws** at about 27–36 ms are fine for a desktop but not for animation.

### What changes, if any, would be needed to the KAGURA SDK?

No RTL or ABI changes. In the SDK:
1. A resource ownership/lease API for patterns, BG map, scroll and BACKDROP, so the desktop's 1,001 patterns and any future hardware cursor (OAM plus 4 patterns) can be allocated instead of assumed.
2. A transport entry for TILE4 runs callable from C: the existing `kh_vram_write` + FENCE path in `tile_fb_io.c`, or `Video.tiles` from Python with the dirty runs passed in.
3. A firmware build that includes the C core as a MicroPython user C module, with frozen-manifest and board changes.
   A later phase, after hardware validation; nothing in this experiment changes them.
4. An input adapter for a pointer device. The keyboard path can reuse KAGURA-UI's `TerminalInput`/`StdinInput` decoding.
5. A choice of 320x200 centred in 320x240 (SCROLL_Y = 236, border shows BACKDROP = palette entry 0), or keeping 320x240.
   The core's 200-line height is a constant; 320x240 would need 1,200 patterns and leave none for anything else.

### Should the project adopt this approach, use a hybrid architecture, or continue with the current Python UI?

**Hybrid, gated on hardware evidence.** Do not rewrite KAGURA-UI now.

What supports moving the core to C:

| Evidence | Kind |
|---|---|
| C composition is 11–39x faster than KAGURA-UI's on the same PC for comparable small operations, with native raster on both sides | measured (PC) |
| Composition plus export of a small update: 38–70 k Thumb-1 instructions; full redraw 2.8 M; sprite import 1.3 M | counted |
| On RP2040, roughly 0.4–0.9 ms for small updates and 27–36 ms for a full redraw. KAGURA-UI for comparable operations: 19.5 ms of CPU for a sprite pixel, a 213.5 ms frame for a full sprite-editor redraw, 323 ms for a full import (#67) | estimate vs measured (RP2040) |
| No GC heap use and no run-time allocation | measured |
| Overlapping windows without extra buffers | measured |

What argues for caution:
- None of the RP2040 numbers for C are measured, and the CPI band and flash-cache behaviour are assumptions.
- Transport is unchanged: a C desktop still pays the SDK flush per frame (**measured (RP2040)** 2.4 ms for a one-pixel edit under MicroPython), roughly in proportion to tiles.
- Integration work (user C module, lease API, pointer input) is larger than the core itself.
- KAGURA-UI is shipped, tested on hardware and good enough for single-screen tools.

Suggested next steps, each with an exit criterion:
1. **RAM-only RP2040 CPU benchmark.** Build `bench/workloads.h` for RP2040 without FPGA I/O, load it to SRAM through BOOTSEL (no flash write) and time the workloads.
   Proceed if small updates are below about 2 ms and a full redraw below 50 ms.
2. **Measure the transport.** Use a C flush of TILE4 runs through `tile_fb_io.c`-style code on the real FPGA, with the same workloads.
3. **Native module.** Wrap `kd_app.h` as a MicroPython user C module with retained display lists and event rings. Port one KAGURA-UI demo (the sprite editor) and compare it end to end against #67's numbers.
4. Only then decide whether KAGURA-UI's widgets move onto the native core or stay as a separate full-screen toolkit.
