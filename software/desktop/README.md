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
| `text/` | `kj_text`: strict UTF-8 decoding, KJ8F glyph lookup and measurement (from PR #71, without Wren); `kj_misaki8`: the repository's Misaki font, embedded unchanged in read-only memory; `kd_edit`: the bounded UTF-8 editing core | C11 |
| `retained/` | `kdm`: retained display lists for script-driven windows, fixed pools, event ring, menus | core |
| `binding/` | `kagura_desktop`, the MicroPython user C module (handles, errors, sinks) | kdm, MicroPython |
| `tests/` | C tests (text, editing core with 4 mutants, kdm with 10 mutants) and MicroPython tests (binding, hardware session) | |
| `tools/` | `test.sh`, `build_unix.sh`, `build_firmware.sh` | |

The hardware session is `software/micropython/kagura/desktop.py`, frozen into the firmware. It uses the console's SDK device, so the board has one hardware owner and one transport.

The core and the text engine do not depend on MicroPython. Standalone C programs use them directly, as the experiments do: `experiments/c-gem-desktop/pico` runs them from SRAM over the C transport in `software/pico`.

## Text

- With `KD_UTF8=1` (set by the firmware and the host build), all core text is UTF-8: titles, menus, buttons, icon labels, labels and records.
- Each non-ASCII character is one 8x8 Misaki glyph, whatever the font. ASCII keeps the core's fonts: 8x8 system, or 4x8 small.
- Invalid bytes draw the replacement glyph, and characters missing from the font draw the font's fallback glyph.
- Window titles hold 47 bytes (15 Japanese characters plus room) and are cut on character boundaries. Record text holds 63 bytes.

## Editing

`text/kd_edit.h` is the editing core for text fields and the editor (Phase 4). It does not depend on the desktop, fonts or MicroPython.

- **Bounded storage, owned by the caller.** The text is one flat run of bytes, plus a NUL, in a buffer of fixed capacity. In the firmware that buffer is static C memory, never a GC object. Nothing is allocated.
- **Always valid.** Every input is validated as a whole before anything changes. It must be strict UTF-8 with no NUL. CRLF and a lone CR are stored as LF, and single-line buffers refuse line breaks. A call that fails (`EUTF8`, `ELINE`, `EFULL`, `EINVAL`) changes nothing.
- **Three kinds of position.** Positions are byte offsets on scalar boundaries. Codepoint offsets come from `kd_edit_count`. Visual x comes from a caller-supplied advance function: ASCII is 8 or 4 px wide and Japanese is 8 px, so a character is not assumed to be one cell. Lines are logical, separated by LF, with no wrapping.
- **Damage.** `kd_edit_take_damage` returns the lowest offset changed, so a view repaints from there and not the whole window.

Flat buffer or gap buffer, from `kd_edit_bench` on the host (ns per edit):

| document | typing at the start: flat / gap | after a random jump: flat / gap |
|---|---|---|
| 1 KB | 18 / 0.6 | 18 / 12 |
| 8 KB | 102 / 0.6 | 59 / 23 |
| 16 KB | 187 / 0.6 | 98 / 35 |

The flat buffer's worst case is one `memmove` of the document per keystroke. It grows linearly and stays far below the cost of a tile transfer, which is about 1.1 ms per run. A gap buffer would need every view to draw two spans, or close the gap first. The RP2040 figure for this worst case is still to be measured on the board (PR C).

## Fields and keyboard

```python
w = desk.create_window('名前を付けて保存', 60, 60, 200, 72)
name = w.field(6, 18, 186, 'メモ.TXT')              # single-line field, focused first
ok = w.button(36, 38, 56, 16, '保存', kd.BTN_DEFAULT, True)   # True: focusable
desk.key(kd.KEY_CHAR, 'a')        # keys as before
desk.text('日本語')               # UTF-8 text, as an input method commits it
while (ev := desk.poll()) is not None:
    if ev[0] == kd.ACTIVATE and ev[2] == ok:        # Enter in the field, or Enter/Space on 保存
        save(w.get_text(name))
    elif ev[0] == kd.CHANGE:                        # a key edited field ev[2]
        ...
```

- **Fields** are retained records like the others. Each one draws itself, with its caret and selection, inside the window's draw. A keystroke invalidates only what changed: the text from the first changed character to the field's edge, and the old and new caret or selection. If the text scrolls, the inside of the field is invalidated. The caret is visible only in the focused field of the active window. It does not blink yet.
- **Limits.** A field holds 63 bytes of UTF-8 (`kd.FIELD_BYTES`), and up to 8 fields exist at once. Long text scrolls horizontally. `w.selection(id)` and `w.select(id, a, b)` count characters, as Python's `str` does.
- **Keys go to the desktop first:** an open menu, F10, F6 or Ctrl+Tab, Ctrl+W, and Ctrl+arrows on movable windows.
- **Then to the active window**, in this order:
  1. Tab and Shift+Tab move between the window's fields and focusable buttons.
  2. A focused field edits: printable ASCII, Backspace, Delete, Left, Right, Home and End (Shift selects), Ctrl+A, Ctrl+Insert (copy), Shift+Insert (paste) and Shift+Delete (cut).
  3. Enter or Space on a focused button queues `ACTIVATE`. Enter elsewhere activates a focusable default button.
  4. Everything else (Escape, Up, Down and the other keys) is queued for the application as before.

  A window without focusable controls therefore behaves exactly as before.
- **Ctrl+C stays MicroPython's KeyboardInterrupt.** It is never a clipboard key. `Window.edit(id, kd.EDIT_COPY | EDIT_CUT | EDIT_PASTE | EDIT_SELECT_ALL)` gives menus the same commands. The clipboard, 255 bytes, is shared by all fields (`desk.clipboard()`, `desk.set_clipboard(s)`).
- **No allocation while typing.** `key`, `text`, `poll_into` and `present` allocate nothing, so typing runs under `heap_lock()`.

`software/micropython/examples/desktop_keys.py` is a keyboard-only tour covering menus, window switching, fields, Japanese text, copy and paste, scrolling and a dialog. It is deterministic and writes no files. On the board it is paced for watching (`key_ms`, `step_ms`). The window says whether the input is scripted (スクリプト) or comes from a keyboard (キーボード).

The font data (`software/micropython/fonts/misaki8.kfnt`, 71,718 B, 7,171 glyphs) is © Num Kadoma and licensed separately; see `text/NOTICE.md` and `software/micropython/fonts/README.md`.

## The text editor

`w.editor(x, y, w, h, text='')` adds the multiline editor. There is one per desktop. It is a retained record like a field, and its document lives in static C memory.

- **Capacity:** 8,191 bytes of UTF-8 (`kd.DOC_BYTES`), about 2,700 Japanese or 8,000 ASCII characters.
  - Free heap after boot was 153,504 B; the document takes 8 KB of it.
  - On the RP2040, a worst-case `memmove` of 8 KB takes 463 µs, under half the cost of one tile-transfer run.
  - A full document refuses further input; nothing is cut.
- **Lines are not wrapped.** Long lines scroll sideways. The view keeps the caret in sight: a quarter view ahead past the right edge, half a view of context when going back left. Vertically it shows no empty rows below the last line.
- **Keys:** Enter breaks the line. Up and Down keep the visual column (ASCII and Japanese differ in width). PgUp/PgDn move one view. Ctrl+Home/End go to the start or end of the document. Shift selects with all of them. Backspace at a line start joins the lines.
- **Repainting.** After a keystroke the editor repaints only part of the view:
  - an edit on one line: from the change to the right edge;
  - a line break added or removed: that line and the lines below;
  - a caret move or selection: the affected rows;
  - a scroll: the whole view.
- **Python calls:** `w.caret(id)` gives (line, column) in characters. `w.version(id)` changes with every edit, so it tells whether the document was modified since the last save. `w.length(id)` gives the size in bytes.

`software/micropython/examples/desktop_editor.py` (神楽メモ帳) is the application built on it:

- **Commands:** 新規, 開く…, 保存, 名前を付けて保存… and 終了 in the menus, with Ctrl+N, Ctrl+O and Ctrl+S as shortcuts. The 編集 menu has cut, copy, paste and select all. The title and status line show the name, line, column, size and whether the document is modified (変更あり).
- **Unsaved changes:** new, open and quit ask 保存 / 破棄 / 取消 first. Saving under an existing name asks before overwriting.
- **Files are plain names in one folder** (default `/docs`), never paths. `/`, `..`, leading dots, `.tmp` names and control characters are refused, so boot scripts, fonts and other system files can't be reached.
  - Loading refuses non-UTF-8 files, files containing NUL, and files too large for the document.
  - LF or CRLF line endings and a UTF-8 BOM are kept as the file had them.
- **Saving:**
  1. Check that the free space covers the file plus a 4 KB margin.
  2. Write `NAME.tmp` and close it.
  3. Check its size.
  4. Rename it over `NAME`.

  On littlefs (the board's filesystem) the rename replaces the target, as checked on the RP2040 below. An interrupted save therefore leaves either the old file or the new one; no further power-loss safety is claimed beyond littlefs' own. On a filesystem that refuses to rename over a file, the old file is removed first, so that save is not atomic. A failed save keeps the document in memory and says why.
- **`ram_docs()`** puts the documents on a littlefs in RAM. Demos and tests on the board then never write to flash.

Measured on the RP2040 from RAM, with firmware 1c9c234 and the file layer on a RAM littlefs (`tools/kagura-editor-device.py`, log in `docs/hardware/editor-files-ram-1c9c234.txt`):
- CRLF and BOM round trips are exact.
- littlefs `rename` replaces an existing file.
- A save larger than the free space is refused, the old file is kept and no `.tmp` is left.
- Unsafe names are refused.
- An 8,160-byte Japanese document saves in 55 ms and loads in 38 ms.

The editor's per-keystroke timing on the board needs firmware with the editor.

## Showcase for video

`software/micropython/examples/desktop_showcase.py` is a paced tour made to be filmed from the HDMI output. It runs about 2 minutes; `main(pace=1.5)` is slower.

- **Layout:**
  - One subject at a time, with no cascade of overlapping windows.
  - A cream caption band at the bottom says what is happening.
  - Each chapter opens with a title card.
  - Only the 8×8 font is used, black on white or cream.
- **Chapters:** menus by keyboard; Japanese editing (typing, selecting and replacing, scrolling); saving and reopening through the dialogs; two windows side by side switched with F6; an end card.
- **Scripted input is labelled as such:** 入力:スクリプト. For real typing, film `desktop_editor.main()`, which says キーボード.
- **No flash writes:** documents go to `ram_docs()`.
- **Same frames on host and board:** each scene prints a CRC, and the host run (`tools/test.sh`) must match the board. Pacing changes only the timing.

## Keyboard input

`software/micropython/kagura/keyinput.py` connects a keyboard to the desktop in two parts. Either part can be replaced.

- **`TerminalKeys`** decodes VT/xterm terminal bytes into the desktop's normalized calls: `key(KEY_*, ch, MOD_*)` for keys and `text(buffer)` for UTF-8. It handles printable ASCII, UTF-8, Enter (CRLF counted once), Tab, Backspace, Ctrl+letters, arrows, Home/End, Insert/Delete, F6 and F10, with Shift, Ctrl and Alt from xterm modifier parameters. A lone Escape is reported after 50 ms. Other sequences are consumed and counted. `feed()` allocates nothing. A future USB HID-to-UART bridge (a XIAO RP2040 is planned) needs only to send the same sequences, or to come with its own decoder that makes the same two calls.
- **`StdinSource`** reads stdin without blocking, at most 64 bytes per `pump()`. On the board, stdin is the console's stream: UART RX through dupterm, plus USB CDC. The console stays the only reader of the UART, and nothing else consumes those bytes.
- **Keys are handled in order.** `pump(keys, each=True)` returns after every decoded key. The application handles its events before the next key is routed: when Ctrl+S opens a dialog, the name typed right after it goes into the dialog, however fast the bytes arrive. The demos and the editor present one frame per batch, not per key.
- **Key repeat.** Terminals send key presses only, never releases. Auto-repeat arrives as repeated bytes, so the decoder has no repeat timer.
- **Ctrl+C is untouched.** It raises KeyboardInterrupt before any of this code sees it, and `kbd_intr` is never changed. An application's `finally: desk.close()` brings the console back.
- **Clipboard keys.** Ctrl+Insert, Shift+Insert and Shift+Delete arrive as `ESC [2;5~`, `ESC [2;2~` and `ESC [3;2~`. Many terminal programs keep Shift+Insert for their own paste and send the pasted text instead, which then arrives as typing. The 編集 menu offers the same commands either way.

`examples/desktop_keys.py` with `main(script=False)` is the keyboard session, labelled キーボード.

Measured on the RP2040 from RAM, with firmware 1c9c234 and no flashing (`tools/kagura-keyboard-device.py`, log in `docs/hardware/keyboard-ram-1c9c234.txt`):

| check | result |
|---|---|
| terminal sequences over USB CDC, split across packets mid-UTF-8 and mid-CSI | 18 of 18 events exact |
| 2,000 bytes sent at once | 2,000 received, about 2.1 kB/s |
| decoder | 123 µs per byte; `feed()` passes under `heap_lock` |
| idle `pump()` (nothing to read) | 250 µs |
| `memmove` up by one byte, net of 54 µs call cost: 1 / 4 / 8 / 16 KB | 58 / 232 / 463 / 925 µs |
| Ctrl+C during the input loop | KeyboardInterrupt, `finally` ran, REPL answers, console attached |

A keystroke is at most about 6 bytes (an escape sequence), so decoding costs under 1 ms. That is well inside a frame, since a tile-transfer run costs about 1.1 ms.

These checks cover USB CDC only. The UART RX path and a physical keyboard have not been tested yet.

## Line graphs in sprites

`desk.trace(sprites, cols, values, fg, bg=0)` draws a line graph in C across a grid of sprites (`kdm_sprite_trace`).

- **Canvas:** the sprites form one canvas, row-major, `cols` per row, at most 8 sprites: 4×2 is 64×32 pixels.
- **Values:** `values` is a buffer of signed bytes (−127..127), spread over the width, 0 at the middle. Consecutive points are joined by vertical segments in `fg` on `bg`.
- **Redraw:** each sprite is loaded as `Sprite.load` does, so only the changed pixels are redrawn. If nothing changed, nothing is.
- **Cost:** it allocates nothing, and one call replaces what would take dozens of fill records.
- **Errors:** they change nothing.

神楽トラッカー's scope uses it: `kagura_audio.render()` fills the values.

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
