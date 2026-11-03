# SKK Japanese input (Phase 5)

神楽メモ帳 accepts Japanese through an SKK-style input method. It works with every keyboard path the desktop has: terminal bytes over USB CDC or UART, decoded by `kagura.keyinput`. A future USB HID bridge only needs to produce the same key calls.

```python
from kagura import skk
app = desktop_editor.Editor(desk, docs, ime=skk.SkkEngine(skk.test_dictionary(), style=skk.MODERN))
desktop_editor.keyboard(app)        # SkkInput sits between the decoder and the desktop
```

## Architecture

| part | where | role |
|---|---|---|
| `SkkEngine` | `kagura/skk.py` (MicroPython, frozen) | the state machine (normal, ▽ reading, ▼ conversion), romaji, okurigana, candidates; independent of the desktop |
| `SkkDict` / `SortedFileDict` | `kagura/skk.py` | the dictionary in memory, or binary-searched in a sorted file |
| `SkkInput` | `kagura/skk.py` | the sink of `TerminalKeys`; passes on every key the IME does not use |
| preedit | native, `kdm_set_preedit` | drawn at the caret of the focused field or editor; never part of the document |
| candidate popup | native, `kdm_set_candidates` | up to 5 candidates in a floating popup under the preedit, the selection inverted, a page number or message at its foot |
| mode indicator | native, `kdm_set_status` | at the right end of the menu bar: `A 直接`, `あ かな`, `ア カナ`, `▽ 読み`, `▼ 変換` |

- **Committed text** goes in through `Desktop.text`, exactly as typed UTF-8 would.
- **The preedit** belongs to the native control. `Window.set_preedit(id, text, start, end)` draws it at the caret: the text after the caret moves right, the conversion is shown inverted, the preedit is underlined, and the caret follows it. Scrolling and clipping account for its width. The document's text, version and undo are untouched, so a cancelled conversion leaves no trace (tests compare frames before and after). A change invalidates only from the caret to the end of its row.
- **The candidates** come from `engine.popup()` and go to `Window.set_candidates(id, items, selected, footer)`. MicroPython keeps the SKK logic; the native layer only presents. The status line of 神楽メモ帳 is a thin bar (13 px) with only the document's line, column and size; a modified document shows as `*` in the title.
- **The indicator** comes from `engine.indicator()` and goes to `Desktop.set_status(text)`, after every key. It is drawn by the menu bar's own renderer in the Japanese font, right-aligned, never over the menu titles (a text too long is clipped, never overlapping); a change redraws only its box.
- **Where the IME acts:** only while an editable control has the focus (`Desktop.input_target()`). With a menu open or a button focused, keys go to the desktop as before. Dialog fields get SKK too.

## Display policy

`SkkEngine(dictionary, style=...)`:

| style | first Space | list | step | choose |
|---|---|---|---|---|
| `'modern'` (神楽メモ帳's) | ▼ first candidate, popup open | 5 a page, from the first candidate | Space / Down: next; `x` / Up: previous | `1`-`5`, or Enter on the highlighted one |
| `'classic'` | ▼ first candidate inline, no popup | from the second Space, 5 a page | as modern | as modern |
| `'skk'` (default, unchanged) | ▼ inline | from the 5th, 7 a page, Space by pages | Space / `x` | `a s d f j k l` (no popup; messages only) |

The dictionary, romaji, okurigana, modes, Enter, Escape, Backspace and the other keys behave the same in every style. In the popup styles, Up and Down move in the list while converting; otherwise they commit the preedit and move the caret, as before. Space on the last candidate leaves it and shows 最後の候補 in the footer.

## Candidate popup

- **Z-order:** a transient layer above every window, a modal dialog included (a dialog's own field gets the popup above the dialog), and below the menu bar and its open menus. It is shown only while its record has the focus in the active window: opening a dialog or activating another window hides it, and coming back shows it again. A menu opened during a conversion covers it, and closing the menu restores the frame exactly.
- **Anchor:** the left of its text lies under the preedit's first character, which is where the conversion starts. The x comes from the editor's own layout (`kd_edit_x` with 8 px full-width glyphs and the font's ASCII width, minus the horizontal scroll), the y from the caret's visible row (`view_row`, after vertical scrolling). Placement is recomputed at every render, so the popup follows typing, scrolling and window moves.
- **Placement:** below the caret's row; if it does not fit above the bottom of the screen, above the row. Horizontally it stays inside the window's work area (the screen when it is wider), never over the menu bar. It never covers the caret's row.
- **Line wrapping:** the editor does not wrap lines (a long line scrolls horizontally), so the preedit and the popup always sit on one visual row.
- **Size:** at most 5 rows of 10 px, as wide as the widest candidate (a candidate longer than 47 bytes is cut at a character boundary) or the footer, at least 32 px.
- **Redraw:** opening, moving or closing it recomposes its old and new rectangles, so the pixels below come back exactly. A new selection redraws only the two rows that changed, and a new footer only the footer. Nothing else is recomposed, so the view is never fully recomposed.

## Supported

| key | effect |
|---|---|
| Ctrl+J | ASCII → かな mode; in かな mode, commits the preedit. A terminal sends a lone LF for it; Enter is CR. |
| `l` | かな → ASCII mode (in ▽: commit the reading first) |
| `q` | ひらがな ↔ カタカナ mode; in ▽, commits the reading in the other kana |
| romaji | a, ka, kya, shi/si, chi/ti, tsu/tu, fu/hu, ja/jya, cha, dya, fa, vu, wo, … ; `nn`, `n'`, and `n` before a consonant → ん; a doubled consonant → っ; `x` small kana (`xtu`, `xya`); `- , . [ ]` → `ー 、 。 「 」`; `z/ z- z. z,` → `・ 〜 … ‥` |
| uppercase | starts ▽ (`Kanji` → ▽かんじ). An uppercase letter after a complete reading starts the okurigana: `KaKu` → key `かk` → 書く; `OkoTta` → 怒った |
| Space | ▽ → ▼ first candidate; again: next candidate (see the display policy for the list) |
| `x` | previous candidate (or page, `skk` style); from the first candidate, back to ▽ |
| Up / Down | popup styles, in ▼: previous / next candidate |
| `1`-`5` | popup styles, list shown: that candidate of the page |
| Enter | commits the candidate (▼, the highlighted one) or the reading (▽), without a new line; with nothing pending, a new line |
| Escape, Ctrl+G | ▼ → ▽ (okurigana back into the reading); ▽ → preedit discarded; pending romaji dropped; otherwise the application gets Escape |
| Backspace | pending romaji, then the okurigana, then the reading, then ▽ itself; in ▼, back to ▽ |
| typing on in ▼ | commits the candidate, then the key |
| other keys (arrows, Tab, F10, Ctrl+S, …) | commit the preedit, then act as usual |
| UTF-8 text from the terminal | commits the preedit, then goes in as typed |

## Not supported (yet)

- **Dictionary registration:** a reading without candidates stays in ▽, with 候補なし in the popup's footer.
- **Learning:** candidates keep the dictionary's order.
- **Annotations** are stripped, not shown.
- **Also missing:** abbrev mode (`/`), zenkaku ASCII (`L`), numeric conversion (`#`), completion, and the kana-input table.
- **Real SKK-JISYO files:** they are EUC-JP, with separate okuri-ari and okuri-nasi sections. `SortedFileDict` reads UTF-8 sorted by reading, so a converter is needed.
- **The dictionary** is the compact deterministic one (`skk.TEST_DICTIONARY`, about 30 readings). `SortedFileDict` takes a larger file without loading it into the heap, but none ships yet.

## Verification

**Host** (`tools/test.sh`):
- `tests/test_skk.py`: romaji, modes, conversion, candidates and pages, okurigana, cancel and Backspace, other keys, UTF-8 and katakana, dictionaries in memory and in a file, a long typing run; the modern and classic styles (pages, Up and Down, numbers, Enter, 最後の候補, 候補なし) and the unchanged `skk` style; the five indicator labels.
- `tests/test_editor.py`: the demonstration (22 scenes: the five indicator states, the popup's pages, the four corners, a moved window; the frame after the corners equals the one before), its determinism, and SKK in the Save As dialog alongside menus.
- `tests/test_binding.py`: `set_candidates` and `set_status`, their errors, no allocation while selecting, and no trace once cleared.
- kdm: the preedit (text untouched, caret, highlight, exact restore, scrolling, moving between records, closing), input targets, 3,000 random steps against full recomposition, and a mutant. The popup: the four corners (flipped above at the bottom, clamped at both sides), anchoring through full-width text, scrolling, window moves, a lower window, a dialog and menus, exact restore, a selection change recomposing exactly two rows (mutant 12 redraws all and fails), the indicator's box (five states, never over the menus, clipped when too long), and 3,000 random steps with popup, status, menus and moves against full recomposition.
- The showcase (20 scenes) and `desktop_ja` (11 scenes) frames are unchanged.

**Board** (firmware 75134de; logs `hardware/phase5-*.txt`, frames `hardware/phase5-skk-hdmi.png`):

| check | result |
|---|---|
| scripted demonstration (`kagura-editor-board.py skk`) | 12/12 scene CRCs equal to the host; VRAM read back equals the host's TILE4 image in every scene; `ERROR_CODE` 0; the final text is exact |
| live typing over USB CDC (`skk-live`) | the same keys typed at 8 per second into the real keyboard loop: exact final text; quit through F10 > 終了 > 破棄; console back |
| soak (`skk-soak`, 5 minutes) | 17,901 keys, 30 checks (full recomposition changes nothing, `ERROR_CODE` 0, IME idle), 0 failures; heap floor 110,928 B, steady |
| per key, end to end (decoder, SKK, preedit, editor, present) | p50 under 15 ms, p95 under 17.5 ms, worst 69 ms (a GC collection) |
| flash, RAM | firmware +14.0 KB (SKK frozen, native preedit); static RAM +100 B; free heap after boot 140,992 B |
| regression (`kagura-desktop-device.py`, log `hardware/phase5-regression-75134de.txt`) | `desktop_ja` 11/11 scene and VRAM CRCs, `ERROR_CODE` 0, soak of 10,497 updates with 0 failures, console back, soft and hard reset |

**Board, candidate popup and indicator** (firmware ca4be0e; logs `hardware/popup-*.txt`, HDMI frames `hardware/popup-hdmi.png`):

| check | result |
|---|---|
| flash (`tools/rp2040-firmware.py`, over 75134de) | filesystem unchanged, firmware read back equal |
| scripted demonstration (22 scenes) | 22/22 scene CRCs equal to the host, and VRAM read back equal to the host's TILE4 image in every scene; `ERROR_CODE` 0; exact text. The HDMI output shows the five indicator states, the popup's pages, 候補なし, the four corners and a moved window. |
| live typing over USB CDC (`skk-live`) | the script typed into the real keyboard loop, arrow keys included: exact final text; console back |
| soak (`skk-soak`, 5 minutes) | 16,740 keys, 27 checks (full recomposition changes nothing, `ERROR_CODE` 0, IME idle), 0 failures; heap floor 109,568 B, steady |
| per key, end to end | p50 under 16.5 ms, p95 under 19.5 ms (Phase 5: 15 and 17.5 ms). Each key now also updates the popup and the indicator, and the soak's keys now open and page the popup. |
| flash, RAM | firmware +4.3 KB; native state +332 B; free heap after boot 140,672 B (−320 B) |
| regression (`hardware/popup-regression-ca4be0e.txt`) | `desktop_ja` 11/11 scene and VRAM CRCs, `ERROR_CODE` 0, soak of 53,197 updates with 0 failures, console back, soft and hard reset |
