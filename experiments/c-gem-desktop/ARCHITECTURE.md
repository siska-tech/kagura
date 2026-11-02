# Architecture of the C GEM-style desktop prototype

Status: experiment on branch `experiment/c-gem-desktop`, started from main `1dea600` (2026-11-02).
This document is the architecture and memory-budget proposal (workflow step 2), updated with what the implementation and measurements showed.
Measured values are marked **measured**; everything else is design or estimate.

## 1. What the repository already does

| Existing piece | Constraint it puts on a desktop |
|---|---|
| KAGURA-UI (`software/micropython/kagura/ui`, 1,325 lines of Python) | A widget tree and a renderer that call a backend's `fill_rect` and `glyph8`. It uses a damage list (default one bounding rect) and recomposes the tree from the back for each damage rect. It is keyboard only. |
| SDK `TileFramebuffer` (`kagura/framebuffer.py`, Viper kernels) | 320x240 tile-native buffer of 38,400 B and a 1,200-byte dirty map, allocated in the MicroPython GC heap: **measured** constructor heap growth of 40,544 B on RP2040. It owns all 1,200 patterns, the BG map, scroll and palette bank 0. |
| C `tile_fb.c` / `tile_fb_io.c` (Pico firmware) | A C port of the same plane and of `flush(max_gap)`: dirty runs, the 1023/1024 bank split and FENCE confirmation. |
| ABI 0.6 video | 1,200 patterns (0..1023 at 0x0000, 1024..1199 at 0xB000). BG map is 64x32 cells; SCROLL_Y works modulo 256. Hardware colour 0 is transparent and shows BACKDROP; the SDK sets BACKDROP = palette*16 + 0 so colour 0 still looks opaque. |
| Ownership | There is no registry of patterns, map or OAM. KAGURA-UI's `App(exclusive=True)` is a cooperative declaration that nobody else draws. |
| Transport | No atomic full-frame swap: FENCE confirms completion, COMMIT is not a page flip. Flush cost on RP2040 under MicroPython (**measured**, `docs/framebuffer-results.md`): 13.7 ms for 1 tile, 21.3 ms for 100 tiles, 113 ms for all 1,200. With the newer FIFO/DMA paths, a one-pixel sprite edit flushes in 2.4 ms (**measured**, `docs/kagura-studio-sprite-editor.md`). |

The 200 patterns above the 320x200 plane are **not** treated as free: nothing in the SDK hands them out, and a desktop that later wants a hardware cursor needs an allocation API first (section 6).

## 2. Layers

```
 apps/ (File Manager, Studio, About, viewer)   -- use only kd_app.h
 ---------------------------------------------------------------
 D  kd_app.h     windows, kd_draw context, POD events, labels
 C  kd_desktop   z-order, compositor, damage, focus, menus, drag
 B  kd_gfx       frames, title bars, menus, buttons, icons, cursor, fonts
 A  kd_fb        320x200 4bpp plane, clip, primitives, exact dirty tiles
    kd_region    damage list, rectangle sets
    kd_tile4     TILE4 export, run flush, 320x240 placement
 ---------------------------------------------------------------
 host/  SDL2 adapter, headless dumps        (no host code below this line)
```

### A. Pixel and framebuffer operations

- **Working buffer.** Linear packed 4bpp, 160 bytes per row, even x in the high nibble: 32,000 B.
  A row of 8 pixels starting at a multiple of 8 is byte-for-byte one 4-byte row of a TILE4 pattern.
  Export is therefore a gather of eight 4-byte rows per tile, with no per-pixel conversion and no second full-size buffer.
- **Primitives.** Pixel, span fill (whole bytes in the middle, nibbles at the ends), rect, Bresenham line, an 8x8 pattern fill anchored to the screen, 1bpp glyph/bitmap blit, and a TILE4 blit with integer zoom.
  Every primitive clips to `fb->clip`, which is kept inside the screen, using 64-bit ends, so any `int` coordinate is safe.
- **Transparency** is only the `key` argument of the blits. Colour 0 is an ordinary opaque desktop colour (the green desk).
- **Dirty tiles.** A 125-byte bitmap with one bit per 8x8 tile, set when a written byte actually changes.
  Section 3 explains how the compositor keeps it exact despite overdraw.
- No allocation, no floats, no globals. Colours above 15 are masked.

### B. GEM-style renderer

- A fixed 16-colour palette in RGB444 (the KAGURA palette format): green desk, black on white chrome, saturated accents.
- **Menu bar:** 11 rows; titles are inverted while open. Dropdowns are white boxes with a one-pixel shadow and dotted separators; disabled items are grey; checked items carry a tick.
- **Windows:** a 1-pixel black frame and a 10-row title bar. The close box is at the top left. An active window shows GEM's horizontal lines in its title bar; inactive titles are plain with grey text. The work area starts 12 rows below the frame top.
- **Buttons:** a default button gets a double border, a pressed button is inverted, and focus is a dotted inset.
- **Icons:** 16x16 string-art bitmaps with ink, paper and transparent pixels; a selected icon is inverted, and its label sits in a white box in the small font.
- **Fonts** come from the repository's Misaki asset by a pinned generator (`tools/gen_font.py`): 8x8 from the full-width Latin forms (system font) and 4x8 from the half-width forms (small font). No new runtime dependency; 1,536 B of rodata.
- **Software cursor:** an 11x16 arrow drawn as an overlay.

### C. Window and event management

- Up to 8 windows. `z[]` lists window slots from the bottom up; the last one is active and has keyboard focus.
- **Compositor.** Each damage rect is processed from the top layer down: the open dropdown, then the menu bar, then the windows from the top.
  A layer draws only into the part of the damage rect that no layer above it has covered (a GEM-style visible rectangle list, `kd_region`, at most 48 rects). That part is then subtracted.
  The desktop fills whatever remains, and overlays (drag outline, cursor) go on top.
  Every layer, window contents included, must be opaque over its whole rect; the tests found and fixed one violation, a see-through dropdown shadow corner.
  If the rectangle list overflows, that damage rect falls back to the painter's algorithm, which gives the same pixels with more overdraw. `painter=true` forces this as a baseline.
- **Damage list.** At most 16 rects. A new rect merges with an existing one when they overlap or share an edge and the bounding box wastes no area; a full list merges into the rect whose bounding box grows least. The union always covers everything added.
- **Targeted invalidation.** `kd_window_invalidate` subtracts every layer above the window before damaging, so changes in occluded parts cost nothing.
  Raising a window damages only the parts that windows above used to cover, plus both title bars. Moving or closing a window damages the old and new frames minus the windows above.
- **Events** are 20-byte POD values: pointer move/down/up, key, focus, blur.
  The first click on a background window only raises it, as in GEM. Title drag moves the window either live or as a dotted outline. The close box acts on release inside it. Double click is two downs within 400 ms and 4 px.
  Keys go to the active window. While a menu is open it captures everything.
  Keyboard operation covers everything: F10 menus, F6/Ctrl+Tab cycle, Ctrl+W close, Ctrl+arrows move, arrows and Enter for icons.
- Application callbacks may invalidate, open or close windows. Their damage goes into the next render, and they never render themselves.

### D. Applications and the integration boundary

`kd_app.h` is the only header the demo apps include; it is the boundary a MicroPython binding would wrap.
A window is `{class, user pointer, frame, title, flags}`. The class has `draw`, `event` and `closed` callbacks.

- `draw(window, kd_draw*)` must paint the clip rect of its work area opaquely, as a pure function of application state. It may be asked for any sub-rectangle at any time because of exposure.
  `kd_draw` uses work-area coordinates (fill, rect, lines, pattern, text, art, icon, button, sprite blit, fixed-width label).
- `event(window, kd_event*)` receives work-area coordinates and returns whether it consumed the event.
- `kd_window_invalidate(local rect)`, `kd_label_set` (invalidates only the glyph cells that changed), title changes, open and close.

The two demos use nothing else:
- **File Manager:** a fixed in-memory tree with icons, selection, folder navigation and an info line. Text files open a placeholder viewer, sprite files load into the Studio, and `.PRG` files open the Studio or About.
- **KAGURA Studio:** a 16x16 4bpp sprite in TILE4 order, byte-compatible with KAGURA-UI `Sprite4` (checked against it). It shows a zoomed grid over a checkerboard using the keyed blit, 1:1 and 2:1 previews, 16 swatches, position and colour labels, one undo level, and hex import/export in the KAGURA-UI format.
  Like #67, it invalidates up to 16 changed pixels one by one and anything larger as whole areas.

## 3. Exact dirty tiles despite overdraw

Window content overdraws inside itself: the Studio fills white, then the checkerboard, then the sprite.
A byte can therefore change and change back within one render, and the raster marks every such tile dirty.
The first headless run showed the cost: the Studio import step reported 401 changed tiles where only 149 differed.

`compose_exact` therefore snapshots the tiles a compose pass will touch (at most 40 tiles, 1,280 B). After the pass it sets dirty = (dirty before) || (bytes differ).
Damage larger than 40 tiles is composed in bands of tile rows.
After any render the dirty map lists exactly the tiles whose bytes changed (tested), and a redundant full redraw exports nothing.
This cost about 30% of the full-redraw instructions on Cortex-M0+, mostly newlib-nano's byte-wise `memcpy`/`memcmp`. Word-sized copies would remove most of it; this optimisation was not done.

## 4. TILE4 export and the 320x240 output

- Tile `t = (y/8)*40 + x/8` becomes pattern `t` (0..999). Within a pattern, byte `(y%8)*4 + (x%8)/2` holds two pixels, even x in the high nibble. That is 1,000 patterns and 32,000 B; the full export is **measured** at 2.9 µs on the PC and 4.3 ms on an RP2040 at 125 MHz (BENCHMARKS.md section 6).
- `kd_tile4_flush(fb, max_gap, staging, n, sink)` packs dirty runs into a caller-provided staging buffer (one tile row of 1,280 B in the hosts) and hands them to the sink in ascending order.
  Clean gaps of up to `max_gap` tiles join runs. A run becomes clean only after the sink accepts it, and a failure stops the flush, as `tfb_flush` does.
  A KAGURA sink would call the existing pattern write path, either `Video.tiles` or the C `kh_vram_write` with the 1023/1024 split, followed by FENCE.
- Placement in the 320x240 mode, implemented in `kd_kagura_map_pattern`/`kd_kagura_scroll_y` and tested by rebuilding output lines from map, scroll and patterns:
  - **TOP:** map rows 0..24 point at patterns 0..999; rows 25..31 point at one blank pattern; SCROLL_Y = 0. The desktop occupies lines 0..199 and lines 200..239 are border.
  - **CENTER** (recommended for HDMI framing): the same map with SCROLL_Y = 236. Output line L shows map line (L+236) mod 256, so the desktop occupies lines 20..219, with 20 border lines above and 20 below.
- The blank pattern is 1000, all colour 0, so it shows BACKDROP. BACKDROP is set to palette entry 0 as the SDK already does, so the border shows the desk colour. A different border colour needs a palette entry distinct from GUI colour 0, because hardware colour 0 always shows BACKDROP.
- Patterns 1001..1199 are not written. Map and scroll are written once at start, so only patterns change at run time.
- There is no atomic swap, so a frame whose dirty runs span several transfers can show briefly mixed tiles, as KAGURA-UI frames can today. The desktop has no tearing-sensitive animation apart from window dragging, and outline drag keeps that small.

## 5. Memory budget

**Measured** sizes (arm-none-eabi-gcc 14.2, `sizeof` on 32-bit ARM, `-fstack-usage`):

| Item | RP2040 / RP2350 |
|---|---:|
| Framebuffer, 320x200 4bpp | 32,000 B |
| Dirty bitmap | 125 B |
| Whole `kd_fb` (plus clip and stats) | 32,148 B |
| `kd_desktop` (fb, 8 windows, damage, menus, icons, drag, 1,280 B snapshot) | 34,160 B |
| `kd_shell` with all demo app state | 34,792 B |
| TILE4 staging (host choice: one tile row) | 1,280 B |
| Largest stack frames | `kd_desktop_render` 896 B, `damage_from` 472 B |
| Code, core, Cortex-M0+ `-O2` / `-Os` (fonts included) | 22.6 KB / 17.8 KB |
| Code, core, Cortex-M33 `-O2` | 21.2 KB |
| Code, demo apps, Cortex-M0+ `-O2` | 7.9 KB |

**Measured** on RP2040: peak stack 1,884 B, against an estimate of about 2.3 KB from the deepest frame chains (menu hook → file open → sprite import → invalidate → region subtract).
The total is about 36–38 KB of RAM, all static and outside the MicroPython GC heap. For comparison:
- KAGURA-UI needs one contiguous 38,400 B heap block plus 1,200 B (**measured** 40,544 B constructor growth) and the widget tree (**measured** 3,984 B for the gallery).
- RP2040 has 264 KB of SRAM and RP2350 520 KB. The C desktop's RAM is static, so it is reserved at link time; it cannot fail later for lack of a contiguous heap block.

Overlapping windows need **no extra buffers**: exposed areas are recomposed from application state.
Options that would cost memory, all deliberately not used:
- a backing store per window, w*h/2 bytes (12 KB for a 200x120 window);
- a save-under buffer for menus (about 4.5 KB for the largest dropdown);
- a second framebuffer for page flipping (32 KB, and the hardware has no swap anyway).

## 6. Proposed MicroPython integration (not implemented)

The boundary is `kd_app.h`; a user C module (`kagura_desktop`) would wrap it.
The recommended shape avoids calling Python from inside the compositor.

1. **Retained drawing per window.** A Python window owns a small display list in C: a fixed pool of records (fill, rect, text, icon, button, sprite, label), each with an id.
   The window's C `draw` callback replays the list, clipped by the compositor, so exposure, raise, move and menu close never enter the VM.
   Python changes content with `win.set(id, ...)` or `win.text(id, '...')`, which invalidates only that record's rect; labels already work this way (`kd_label_set`).
   Pure-Python drawing callbacks remain possible for custom content. They cost one VM call per damaged visible rect, and the compositor must not run them from an interrupt.
2. **Events.** C appends `kd_event` values (20 B, no pointers) to a fixed ring per window, for example 32 slots, 640 B.
   Python polls `desktop.poll()` or `win.events()` from its main loop, the same model as KAGURA-UI's `EventQueue`. There are no callbacks into Python from input or IRQ context.
   Overflow drops the newest event and counts it, as KAGURA-UI does.
3. **Frame loop.** `desktop.step()` feeds input, renders the damage, exports dirty runs and FENCEs, under the same single-owner rule as `App.step()`. `desktop.run()` loops until quit.
4. **Ownership.** The framebuffer and state live in a static C object outside the GC heap. Starting the desktop takes the same exclusive lease as `App(exclusive=True)` (pause the console, own patterns 0..1000, the map, scroll and BACKDROP), and closing it restores the console.

Sketch:

```python
import kagura_desktop as kd
desk = kd.Desktop(device, console=kagura_console)
w = desk.window('Clock', 40, 30, 120, 60)
t = w.label(4, 4, 12, '00:00:00')
w.button(4, 20, 48, 14, 'Close', id=1)
while desk.step():
    for ev in w.events():
        if ev.kind == kd.CLICK and ev.id == 1:
            w.close()
    t.set(time_text())
```

## 7. Testing approach

- An independent per-pixel reference model for all primitives and clipping, and formula-only TILE4 readers.
- The repository's own `tile_fb.c` as a second TILE4 implementation; the SDK test decoder and KAGURA-UI `Sprite4` from Python.
- The central invariant, checked after every step of random operation sequences: incremental frame == full region-composed redraw == full painter's-algorithm redraw.
  It found two real bugs during development: a cursor moved by pointer down/up without being damaged, and the see-through dropdown corner.
- 13 fault-injected mutants, each of which the suite must catch.
- Headless screenshots and dumps, plus an SDL smoke test that reads the presented frame back from the renderer.

## 8. Known limitations

- No window resizing, scroll bars or text input fields. There is one File Manager instance and two viewer slots.
- KAGURA has no mouse input path today (KAGURA-UI is keyboard only). The desktop is fully keyboard operable, but pointer input on hardware needs a HID or serial mouse source.
- Live window dragging is expensive on Cortex-M0+ (measured 47.3 ms per 8 px step on RP2040, BENCHMARKS.md section 6); outline drag is the practical mode there.
- Clear optimisation targets were identified and left alone:
  - word-sized copies for snapshot and pack;
  - per-pixel pattern and glyph paths;
  - software division in the zoomed blit (Cortex-M0+ has no divide instruction; the Pico SDK's hardware divider would help);
  - a copy-rect move.
