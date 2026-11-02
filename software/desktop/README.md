# KAGURA native desktop

A GEM-style desktop in C for KAGURA-9, with Japanese text, built into the KAGURA MicroPython firmware so that Python applications can use it.
It grew out of `experiments/c-gem-desktop` (#68: design, tests, RP2040 and HDMI acceptance) and its MicroPython binding (#75, stage 3A).

```python
from kagura.desktop import Desktop
import kagura_desktop as kd

desk = Desktop(menus=(('ファイル', ('開く', '-', '終了')), ('設定', ('画面',))))
win = desk.create_window('神楽デスクトップ', 20, 30, 200, 100)
label = win.text(8, 8, 'こんにちは', 1)          # retained record, returns an id
desk.present()                                   # compose, send changed tiles
while (ev := desk.poll()) is not None:
    if ev[0] == kd.MENU:
        win.set_text(label, 'メニュー %d-%d' % (ev[4], ev[5]))
desk.present()
desk.close()                                     # the HDMI console comes back
```

A complete application is `software/micropython/examples/desktop_ja.py`. It has menus, a welcome window, file icons, a dialog and a sprite studio, plus a scripted tour.

## Layout

| Directory | Contents | Depends on |
|---|---|---|
| `core/` | Framebuffer (320x200 4bpp, exact dirty tiles), raster, GEM renderer, window manager, compositor, menus, events, TILE4 export | C11, `<string.h>` |
| `text/` | `kj_text`: strict UTF-8 decoding, KJ8F glyph lookup and measurement (from PR #71, without Wren); `kj_misaki8`: the repository's Misaki font, embedded unchanged in read-only memory | C11 |
| `retained/` | `kdm`: retained display lists for script-driven windows, fixed pools, event ring, menus | core |
| `binding/` | `kagura_desktop`, the MicroPython user C module (handles, errors, sinks) | kdm, MicroPython |
| `tests/` | C tests (text, kdm with 7 mutants) and MicroPython tests (binding, hardware session) | |
| `tools/` | `test.sh`, `build_unix.sh`, `build_firmware.sh` | |

The hardware session is `software/micropython/kagura/desktop.py`, frozen into the firmware. It uses the console's SDK device, so the board has one hardware owner and one transport.

The core and the text engine do not depend on MicroPython. Standalone C programs use them directly, as the experiments do: `experiments/c-gem-desktop/pico` runs them from SRAM over the C transport in `software/pico`.

## Text

- With `KD_UTF8=1` (set by the firmware and the host build), all core text is UTF-8: titles, menus, buttons, icon labels, labels and records.
- Each non-ASCII character is one 8x8 Misaki glyph, whatever the font. ASCII keeps the core's fonts: 8x8 system, or 4x8 small.
- Invalid bytes draw the replacement glyph, and characters missing from the font draw the font's fallback glyph.
- Window titles hold 47 bytes (15 Japanese characters plus room) and are cut on character boundaries. Record text holds 63 bytes.

The font data (`software/micropython/fonts/misaki8.kfnt`, 71,718 B, 7,171 glyphs) is © Num Kadoma and licensed separately; see `text/NOTICE.md` and `software/micropython/fonts/README.md`.

## Ownership and memory

- **One static C state owns everything.** The framebuffer, windows and all pools live outside the GC heap, about 46 KB on the RP2040.
- **Handles, not pointers.** Python objects hold handles: closed windows, freed sprites and replaced desktops raise `ValueError`. C holds no Python objects.
- **Atomic failures.** A full pool raises `MemoryError` with nothing changed.
- **No allocation in the frame loop:** input, `poll_into`, record updates and `present` run with the heap locked.

Design and measurements are in `experiments/c-gem-desktop/micropython/DESIGN.md` and `REPORT.md`.

## Build and test (WSL/Linux, from the repository root)

```sh
bash software/desktop/tools/test.sh            # host C tests, unix MicroPython tests, demo without hardware
bash software/desktop/tools/build_firmware.sh  # KAGURA_PICO firmware (UF2) with the module
```

The KAGURA_PICO and KAGURA_PICO_W boards include the module unless `USER_C_MODULES` is given.

For flashing with checks and rollback, use `tools/rp2040-firmware.py`. `tools/kagura-desktop-device.py` runs the hardware acceptance: host-equal CRCs, VRAM readback, HDMI stills, RP2040 measurements and resets.
