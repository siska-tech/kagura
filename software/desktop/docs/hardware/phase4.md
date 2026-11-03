# Phase 4 on the board: firmware ff59e7e

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

## After this run

Commit ef?? (PR D) made three changes, found by the timing above, that need the next build on the board:
- glyphs outside the clip skip the font lookup;
- line counting uses `memchr`;
- a caret moving along one row invalidates only its columns, not the whole row.

On the host the frames are unchanged (the `desktop_ja` CRCs are identical), and the composed area per key is smaller.

## Not verified yet

- **A physical keyboard:** none is attached, and the XIAO RP2040 HID bridge is planned.
- **The UART RX path:** the GP1 wiring is unconfirmed.
- **Writes to the board's own filesystem:** not authorized.
