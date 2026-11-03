# Phase 4 on the board: firmware ff59e7e and 1eb6544

RP2040 with KAGURA-9 (FPGA ABI 0.6), HDMI captured with a UGREEN 15390.

The firmware was flashed on 2026-11-03 with `tools/rp2040-firmware.py flash`, with the user's approval:
- Before flashing, the tool checked that the flash held exactly the previous image, 1c9c234.
- Afterwards, the filesystem hash was unchanged (`FS_UNCHANGED yes`) and the new image read back byte for byte (`FIRMWARE_READBACK match`).
- Free heap after boot was 144,000 B (153,504 B on 1c9c234). The extra 8 KB is the editor's document.

Every test ran from the raw REPL. Documents went to `ram_docs()`, a littlefs in RAM, so nothing was written to flash.

## Regression (`tools/kagura-desktop-device.py`, log `phase4-regression-ff59e7e.txt`)

- **Scenes:** all 11 `desktop_ja` scene CRCs equal the host's.
- **Transfer:** the VRAM read back from the FPGA equals the host's TILE4 image, and `ERROR_CODE` is 0.
- **Soak:** 2 minutes of mixed updates, 9,973 updates and 49 checks of "a full recomposition changes nothing", 0 failures.
- **Lifecycle:** the console came back after the desktop closed, and the board survived a soft and a hard reset.

## Editor timing (`tools/kagura-editor-board.py bench`, log `phase4-editor-ff59e7e.txt`)

The times are per key, end to end on the RP2040: key, application, compose, send over the link.

| key | p50 | p95 | compose / send (p50) |
|---|---|---|---|
| type ASCII at a line end | 15.7 ms | 33.2 ms | 5.0 / 6.4 ms |
| type Japanese | 16.8 ms | 33.8 ms | 6.0 / 6.4 ms |
| caret left | 15.8 ms | 16.5 ms | 6.3 / 6.4 ms |
| caret up/down | 19.1 ms | 20.2 ms | 7.3 / 8.4 ms |
| Enter (lines below move) | 42.7 ms | 69.5 ms | 24.0 / 15.6 ms |
| Backspace joining lines | 38.6 ms | 61.9 ms | 24.7 / 16.3 ms |
| PgDn / PgUp | 44.1 ms | 45.5 ms | 30.8 / 9.2 ms |
| idle frame | 1.1 ms | 1.3 ms | 0.1 / 0.4 ms |

- The p95 times include a GC collection, about 12 ms.
- The application layer (status line, events) allocates 480–680 B per key in Python. The native editor allocates nothing.

## Live typing (`tools/kagura-editor-board.py live`, frames in `phase4-live-editor-ff59e7e.png`)

The real `desktop_editor` keyboard loop ran on the board. It took terminal bytes from the board's stdin over USB CDC, at 8 characters per second, sent by a script rather than typed on a physical keyboard. In order:
1. Japanese and ASCII text was typed, with the status line updating as it went.
2. A selection was replaced.
3. Ctrl+S, Save As, saved `kagura.txt` (182 B).
4. Ctrl+N cleared the document, and Ctrl+O reopened `kagura.txt` unchanged.
5. F10 > 終了 quit, and the console came back.

## Firmware 1eb6544: faster keystrokes

The timing above showed most of a keystroke going into compose. Commit 1eb6544 on PR D made three changes, none of which alters a pixel (the `desktop_ja` and showcase CRCs are unchanged):
- glyphs outside the clip skip the font lookup;
- line counting uses `memchr`;
- a caret moving along one row invalidates only its columns, not the whole row.

Separately, the editor's status line now redraws only the digits that changed.

The build was flashed on 2026-11-03, with the user's approval, over ff59e7e. Before flashing, the tool checked that the flash held exactly ff59e7e. Afterwards the filesystem was unchanged, the new image read back byte for byte, and 144,000 B of heap was free.

Editor timing (log `phase4-editor-1eb6544.txt`):

| key | p50 before → after | compose (p50) before → after |
|---|---|---|
| type ASCII at a line end | 15.7 → **11.9 ms** | 5.0 → 1.9 ms |
| type Japanese | 16.8 → **12.1 ms** | 6.0 → 2.0 ms |
| caret left | 15.8 → **10.5 ms** | 6.3 → 1.6 ms |
| caret up/down | 19.1 → 17.7 ms | 7.3 → 6.6 ms |
| Enter / Backspace joining lines | 42.7 / 38.6 → 41.1 / 37.3 ms | about 23 ms |
| PgDn / PgUp | 44.1 → 42.0 ms | 29.5 ms |
| insert at the start of an 8 KB document | 13.9 ms | 4.0 ms |

- For a typed character, the link transfer is now the largest part: 6.3 ms of 12.
- Line breaks and pages redraw most of the view, at about 1.8 ms per text row.

**Showcase** (`desktop_showcase`, 1 min 47 s, HDMI recorded; frames in `phase4-showcase-1eb6544.png`, CRCs in `phase4-showcase-1eb6544.txt`):
- All 20 scene CRCs equal the host run's, on both ff59e7e and 1eb6544.
- The console came back at the end.

**Regression on 1eb6544** (`tools/kagura-desktop-device.py`, log `phase4-regression-1eb6544.txt`):
- All 11 `desktop_ja` scene CRCs and VRAM readbacks are identical to the reference, with `ERROR_CODE` 0.
- The soak ran 9,993 updates with 49 checks, 0 failures.
- The console came back, and the board survived a soft and a hard reset.
- The free-heap floor (93.5 KB) is lower than on ff59e7e only because this run started right after the showcase, without a soft reset.

## Not verified yet

- **A physical keyboard:** none is attached, and the XIAO RP2040 HID bridge is planned.
- **The UART RX path:** the GP1 wiring is unconfirmed.
- **Writes to the board's own filesystem:** not authorized.

## Reproducing

Windows host for the board tools: uv's CPython with `PYTHONPATH=build\transport-analysis\python-deps` (mpremote, pyserial). The host tests run in WSL. No tool prints the USB serial.

```sh
# host: every test, then the firmware (WSL, repository root)
bash software/desktop/tools/test.sh
bash software/desktop/tools/build_firmware.sh KAGURA_PICO build-KAGURA_PICO-phase4
# board: read-only check, then a checked flash (only with approval)
python tools/rp2040-firmware.py check
python tools/rp2040-firmware.py uf2-info <firmware.uf2>
python tools/rp2040-firmware.py flash --uf2 <firmware.uf2> --current-uf2 <the UF2 now on the board> --approved
# board: acceptance, all from RAM (no flash or filesystem writes)
python tools/kagura-desktop-device.py --out DIR --ffmpeg <ffmpeg.exe> --soak 120
python tools/kagura-keyboard-device.py --out FILE
python tools/kagura-editor-device.py
python tools/kagura-editor-board.py bench --reset --out FILE
python tools/kagura-editor-board.py live --reset --video editor.mp4 --ffmpeg <ffmpeg.exe>
python tools/kagura-editor-board.py showcase --reset --video showcase.mp4 --ffmpeg <ffmpeg.exe> [--pace 1.5]
```

- `--reset` soft-resets the board first, for a clean heap and console.
- Showcase CRCs are compared with `micropython examples/desktop_showcase.py --host DIR` (run by `tools/test.sh`).

## Phase 4 acceptance criteria

| # | criterion | status |
|---|---|---|
| 1 | desktop operable with a physical keyboard, without pointer events | **partial.** The keyboard path (decoder, stdin, focus, menus) is verified on the board, but with terminal bytes sent by a script over USB CDC. No physical keyboard is attached, and the XIAO HID bridge is planned. |
| 2 | a focused text field accepts, edits and displays text | done: host tests, and the board in the showcase and live session |
| 3 | Japanese UTF-8 survives editing, storage and reload | done. Byte-exact round trips on the host and on a RAM littlefs on the board; reopened frames equal the saved ones. |
| 4 | a document can be opened, edited, saved and reopened | done on the board, on a RAM littlefs. Saving to the board's own flash filesystem is not authorized yet. |
| 5 | window and menu navigation entirely by keyboard | done: F10, arrows, Enter, Esc, F6, Tab, Ctrl+W |
| 6 | the native editing core is independent of MicroPython | done: `text/kd_edit` is C11 with no dependencies |
| 7 | no second hardware transport or framebuffer | done: one static framebuffer, and the console's SDK device |
| 8 | no accumulating resource leak | done: field and editor slot reuse, repeated sessions, soaks with a stable heap |
| 9 | desktop rendering and console recovery regressions pass | done on ff59e7e and 1eb6544 |
| 10 | every physical claim is backed by hardware evidence | the logs and frames in this folder |

Phase 4 is therefore **partially complete**: criterion 1 waits for a physical keyboard, and the UART RX path waits for the GP1 wiring to be confirmed.
