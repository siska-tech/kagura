# Stage 3A: MicroPython binding of the C desktop (design)

Branch `experiment/c-gem-micropython`, based on draft PR #68.
This is an integration feasibility experiment. The C core in `../src` is used unchanged, and KAGURA-UI is not ported.
The binding is a MicroPython **user C module**, `kagura_desktop`, built into the MicroPython v1.26.0 unix port (`USER_C_MODULES`, Make).
The same sources build into the rp2 port with `micropython.cmake`, which was used here only to measure the firmware's size.

## 1. What the core already fixes

These follow from reading `kd_app.h`, `kd_desktop.h/.c`, `kd_fb.h` and `kd_tile4.h`:

- **One owner of everything.** `kd_desktop` (34,160 B on 32-bit ARM) contains:
  - the 32,000 B framebuffer;
  - the dirty-tile map;
  - 8 window slots;
  - the z-order, damage list, menus and the drag state;
  - the 1,280 B snapshot.

  The core allocates nothing.
- **Windows are fixed slots.** `kd_window_open` takes the lowest free slot of 8. `kd_window_close` removes the window, damages what it uncovered, then calls `cls->closed`.
- **Drawing is pull, not push.** The compositor calls `cls->draw(w, kd_draw*)` for any visible sub-rectangle of the work area at any time: on exposure, raise, move or menu close. Content must be opaque and a pure function of state.
  A Python window therefore cannot simply "draw into its window" once. Either its content is retained in C, or Python is called back from inside the compositor.
- **Events are POD.** `kd_event` is 20 bytes. Pointer events reach a window only inside its work area, and the window then captures the pointer until release. Keys go to the top window. Menus and the close box are handled by the window manager.
- **Composition never re-enters application code that renders.** Callbacks may invalidate, but must not render.

## 2. Decision: retained display lists in C, events by polling

1. **No Python calls from C during composition.** A Python window's content is a list of records in C, the **display list**. The window's `draw` callback replays the list clipped to the damaged area.
   - Exposure, raise, move and menu close never enter the VM. They run in exactly the native C time measured in stages 1 and 2.
   - Python calls into C only when content actually changes.
2. **Events are queued, not called back.** The window class's `event` callback copies the event into a fixed C ring. Python drains the ring with `desktop.poll()` from its own loop. Window-manager-level outcomes become events too: focus, blur, a window closed by the user, a menu choice.
3. **Changes invalidate only what changed.** Adding, changing or removing a record invalidates that record's bounding rectangle (old and new). The core's region code then subtracts occluding windows, and `compose_exact` keeps the dirty-tile map exact. Redrawing a whole window's list therefore exports only tiles whose bytes changed.

Rejected alternatives:

| Alternative | Why not |
|---|---|
| Python `draw` callback per damaged rect | The VM is entered from inside the compositor, once per visible damaged rect and layer. GC can run in the middle of composition. Exceptions would cross core frames. Python time is spent on every exposure, even for unchanged content. |
| Per-window backing bitmap (Python or C) | `w*h/2` bytes per window, for example 12 KB for 200x120, which the RP2040 cannot afford for several windows. It copies window contents, which the brief rules out. |
| A Python-side framebuffer | Ruled out by the brief. It would duplicate the 32,000 B plane in the GC heap. |

## 3. Ownership and memory

| Object | Owner | Where | Lifetime |
|---|---|---|---|
| `kd_desktop` (framebuffer, windows, damage, menus) | the module | one static `kdm` state in `.bss`, outside the GC heap | the whole program; reused by every `Desktop` |
| Display records, text bytes, sprites, event ring, menu strings, TILE4 staging | the module | the same static `kdm` state, fixed-size pools | records belong to one window; sprites to the desktop |
| `Desktop`, `Window` and `Sprite` objects | Python | GC heap, 16–80 B each | ordinary Python references |

Rules:

- **The framebuffer has exactly one owner:** the static `kdm` state.
  - There is no Python-side framebuffer, no per-window bitmap and no second plane.
  - `present()` hands TILE4 runs from a 1,280 B static staging buffer to the sink.
  - `snapshot(buf)` copies the plane into a caller's buffer for tests only.
- **No C pointer into the GC heap, and no Python pointer into C.**
  - The static state holds no `mp_obj_t`. It is not a GC root and needs none.
  - Python objects hold indices and serial numbers, never C pointers:
    - `Window` holds `(desktop, slot, serial)`;
    - `Sprite` holds `(desktop, slot, serial)`;
    - an item is an integer `index | serial << 9`.
  - Every method validates its handle first:
    - the desktop generation must be current;
    - the slot must be open;
    - the serial must be equal.

    A stale handle raises `ValueError` and touches nothing. Python references therefore cannot outlive native windows in a harmful way: they outlive them as dead handles.
- **Strings and pixel data are copied in, never referenced.** Text is copied into a 2 KB text arena. Sprite pixels are copied into the sprite pool. A Python `str` or `bytes` can be collected or replaced at any time.
- **One desktop at a time.** The state is static, so `Desktop()` re-initialises it and increments the generation. Any earlier `Desktop` and all its windows and sprites become dead handles.
  This also covers MicroPython soft reset: the static state outlives the VM, and the next `Desktop()` takes it over.
- **GC.**
  - The `Desktop` object keeps a Python list of its `Window` handles by slot, so `poll()` can return the same object without allocating.
  - Everything else is plain Python references.
  - Native state is never scanned by the GC. That avoids scanning 32 KB of pixels for false pointers (`0x20..` pixel bytes look like RP2040 heap addresses).
  - Window lifetime is explicit. A window closes on `close()`, the close box, `Ctrl+W` or `desktop.close()`, never on garbage collection. MicroPython finalisers are optional and run at arbitrary times.
- **When a pool is full:**
  - adding a record, a window or a sprite, or text beyond the arena, raises `MemoryError` naming the pool;
  - the native state is left exactly as before. Every method checks capacity and all arguments before it changes anything;
  - Python handle objects are allocated *before* the native slot. A failed Python allocation therefore leaves the native state unchanged too.
- **Event overflow.**
  - When the ring is full, the newest event is dropped and `stats()['dropped']` counts it, as in KAGURA-UI's `EventQueue`.
  - `poll()` builds its result tuple before removing the event, so a `MemoryError` there loses nothing.
- **Exceptions never cross the core.**
  - The core never calls Python.
  - The only Python call made while C is running is the optional `present()` sink. It runs after composition, under `nlr_push`: an exception stops the flush, which leaves unsent runs dirty, and is re-raised once the core has returned.
- **Visible static budget.** All pool sizes are compile-time constants in `kdm.h`. `kd.sizes()` reports them, and the report gives both the host and the embedded numbers.

Default pool sizes, chosen so that the 256-rectangle benchmark fits beside other windows:

| Pool | Size |
|---|---|
| display records | 320 x 18 B |
| text arena | 2,048 B |
| sprites | 8 x 130 B |
| event ring | 32 entries |
| menus | 4 menus x 8 items, 256 B of strings |

## 4. Python API

```python
import kagura_desktop as kd

desk = kd.Desktop(320, 200, menus=(("Desk", ("About", "-", "Quit")),))
win = desk.create_window("Hello", 20, 30, 180, 100)   # frame rect, as the core
win.fill_rect(8, 8, 80, 24, 3)        # -> item id
t = win.text(12, 14, "Hello", 15)     # fg 15, transparent background
desk.present()                        # render damage, export dirty TILE4 runs

win.set_text(t, "Bye")                # invalidates the old and new text boxes
while (ev := desk.poll()) is not None:
    kind, w, x, y, key, ch, mods, clicks = ev
```

- **`Desktop`:**
  - `create_window(title, x, y, w, h, bg=2, closable=True, movable=True)`;
  - `sprite(data=None)`;
  - `pointer(kind, x, y, t=None)`, `key(key, ch=0, mods=0, t=None)`;
  - `poll()`, `poll_into(list8)`;
  - `render()`, `present(sink=None)`;
  - `top()`, `windows()`, `stats()`;
  - `crc()`, `snapshot(buf)`, `tile4(buf)`;
  - `set_outline_drag(b)`, `set_cursor(b)`;
  - `close()`.
- **`Window`:**
  - drawing: `fill_rect`, `fill_rects(buf, c)` (batched), `rect`, `hline`, `vline`, `text(x, y, s, fg=1, bg=-1, small=0)`, `button(x, y, w, h, label, flags=0)`, `sprite(x, y, spr, zoom=1, key=-1)`, `icon(x, y, name, label, selected=0)`;
  - records: `set_text(id, s)`, `set_color(id, c)`, `set_flags(id, f)`, `move_item(id, x, y)`, `remove(id)`, `clear(bg=None)`;
  - window: `activate()`, `close()`, `move(x, y)`, `set_title(s)`;
  - queries: `is_open()`, `is_active()`, `work()`, `id`.
- **`Sprite`:**
  - pixels: `set(x, y, c)`, `set_pixels(buf)` (batched `x, y, c` triples), `get(x, y)`, `fill(c)`;
  - data: `load(hex_or_bytes)`, `hex()`, `data()`;
  - `free()`.

  Changing a pixel invalidates only that pixel's zoomed block in every record that shows the sprite.
- **Events** are 8-tuples `(kind, window, x, y, key, ch, mods, clicks)`:
  - coordinates are relative to the work area;
  - `ch` is an int;
  - `CLOSE` and `MENU` (with `key`=menu and `ch`=item) come from the window manager.

  `poll_into(lst)` fills a pre-allocated list, so polling allocates nothing.
- **Times:**
  - pointer and key events take an explicit millisecond time, so scripted input and double-click detection are deterministic;
  - when it is omitted, `ticks_ms()` is used.
- **`present(sink)`:**
  - sink `None`: only render and mark tiles exported (host);
  - a buffer of at least 32,000 B: a TILE4 mirror. Runs are copied in at pattern offsets;
  - a callable `sink(first_tile, memoryview)`: a Python transport such as `Video.tiles`. The memoryview is valid only during the call.

  On RP2040 the third form is the zero-new-code route to the KAGURA SDK. A native transport sink is a stage 3B question.

## 5. Code layout

```
micropython/
  kagura_desktop/        user C module (micropython.mk, micropython.cmake)
    kdm.h, kdm.c         retained layer: pools, display lists, event ring, menus; no MicroPython
    modkagura_desktop.c  MicroPython glue only: argument parsing, handles, errors
  tests/                 C unit tests of kdm, native C reference of the demo, MicroPython tests
  demo/                  deterministic demo script (CRC per step) and an interactive terminal version
  bench/                 the same workloads in C (kdm), MicroPython (binding) and KAGURA-UI
  tools/                 build and run scripts (WSL), rp2 size build
```

`kdm.c` is plain C. The tests and the pure-C benchmark use it without MicroPython, so the cost of the VM layer can be measured on its own.
The native reference for the demo is written directly against `kd_app.h`, without `kdm`, so that CRC equality checks the retained layer as well as the binding.
