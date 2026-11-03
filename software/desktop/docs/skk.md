# SKK Japanese input (Phase 5)

神楽メモ帳 accepts Japanese through an SKK-style input method. It works with every keyboard path the desktop has: terminal bytes over USB CDC or UART, decoded by `kagura.keyinput`. A future USB HID bridge only needs to produce the same key calls.

```python
from kagura import skk
app = desktop_editor.Editor(desk, docs, ime=skk.SkkEngine(skk.test_dictionary()))
desktop_editor.keyboard(app)        # SkkInput sits between the decoder and the desktop
```

## Architecture

| part | where | role |
|---|---|---|
| `SkkEngine` | `kagura/skk.py` (MicroPython, frozen) | the state machine (normal, ▽ reading, ▼ conversion), romaji, okurigana, candidates; independent of the desktop |
| `SkkDict` / `SortedFileDict` | `kagura/skk.py` | the dictionary in memory, or binary-searched in a sorted file |
| `SkkInput` | `kagura/skk.py` | the sink of `TerminalKeys`; passes on every key the IME does not use |
| preedit | native, `kdm_set_preedit` | drawn at the caret of the focused field or editor; never part of the document |
| candidate line and mode label | `examples/desktop_editor.py` | a line above the status line, and [A] / [あ] / [ア] |

- **Committed text** goes in through `Desktop.text`, exactly as typed UTF-8 would.
- **The preedit** belongs to the native control. `Window.set_preedit(id, text, start, end)` draws it at the caret: the text after the caret moves right, the conversion is shown inverted, the preedit is underlined, and the caret follows it. Scrolling and clipping account for its width. The document's text, version and undo are untouched, so a cancelled conversion leaves no trace (tests compare frames before and after). A change invalidates only from the caret to the end of its row.
- **Where the IME acts:** only while an editable control has the focus (`Desktop.input_target()`). With a menu open or a button focused, keys go to the desktop as before. Dialog fields get SKK too.

## Supported

| key | effect |
|---|---|
| Ctrl+J | ASCII → かな mode; in かな mode, commits the preedit. A terminal sends a lone LF for it; Enter is CR. |
| `l` | かな → ASCII mode (in ▽: commit the reading first) |
| `q` | ひらがな ↔ カタカナ mode; in ▽, commits the reading in the other kana |
| romaji | a, ka, kya, shi/si, chi/ti, tsu/tu, fu/hu, ja/jya, cha, dya, fa, vu, wo, … ; `nn`, `n'`, and `n` before a consonant → ん; a doubled consonant → っ; `x` small kana (`xtu`, `xya`); `- , . [ ]` → `ー 、 。 「 」`; `z/ z- z. z,` → `・ 〜 … ‥` |
| uppercase | starts ▽ (`Kanji` → ▽かんじ). An uppercase letter after a complete reading starts the okurigana: `KaKu` → key `かk` → 書く; `OkoTta` → 怒った |
| Space | ▽ → ▼ first candidate; again: next candidate. From the 5th on, a list of 7 at a time, chosen with `a s d f j k l` |
| `x` | previous candidate or page; from the first candidate, back to ▽ |
| Enter | commits the candidate (▼) or the reading (▽), without a new line; with nothing pending, a new line |
| Escape, Ctrl+G | ▼ → ▽ (okurigana back into the reading); ▽ → preedit discarded; pending romaji dropped; otherwise the application gets Escape |
| Backspace | pending romaji, then the okurigana, then the reading, then ▽ itself; in ▼, back to ▽ |
| typing on in ▼ | commits the candidate, then the key |
| other keys (arrows, Tab, F10, Ctrl+S, …) | commit the preedit, then act as usual |
| UTF-8 text from the terminal | commits the preedit, then goes in as typed |

## Not supported (yet)

- **Dictionary registration:** a reading without candidates stays in ▽ with 候補なし.
- **Learning:** candidates keep the dictionary's order.
- **Annotations** are stripped, not shown.
- **Also missing:** abbrev mode (`/`), zenkaku ASCII (`L`), numeric conversion (`#`), completion, and the kana-input table.
- **Real SKK-JISYO files:** they are EUC-JP, with separate okuri-ari and okuri-nasi sections. `SortedFileDict` reads UTF-8 sorted by reading, so a converter is needed.
- **The dictionary** is the compact deterministic one (`skk.TEST_DICTIONARY`, about 30 readings). `SortedFileDict` takes a larger file without loading it into the heap, but none ships yet.

## Verification

**Host** (`tools/test.sh`):
- `tests/test_skk.py`: romaji, modes, conversion, candidates and pages, okurigana, cancel and Backspace, other keys, UTF-8 and katakana, dictionaries in memory and in a file, a long typing run.
- `tests/test_editor.py`: the demonstration, its determinism, and SKK in the Save As dialog alongside menus.
- kdm: the preedit (text untouched, caret, highlight, exact restore, scrolling, moving between records, closing), input targets, 3,000 random steps against full recomposition, and a mutant.

**Board** (firmware 75134de; logs `hardware/phase5-*.txt`, frames `hardware/phase5-skk-hdmi.png`):

| check | result |
|---|---|
| scripted demonstration (`kagura-editor-board.py skk`) | 12/12 scene CRCs equal to the host; VRAM read back equals the host's TILE4 image in every scene; `ERROR_CODE` 0; the final text is exact |
| live typing over USB CDC (`skk-live`) | the same keys typed at 8 per second into the real keyboard loop: exact final text; quit through F10 > 終了 > 破棄; console back |
| soak (`skk-soak`, 5 minutes) | 17,901 keys, 30 checks (full recomposition changes nothing, `ERROR_CODE` 0, IME idle), 0 failures; heap floor 110,928 B, steady |
| per key, end to end (decoder, SKK, preedit, editor, present) | p50 under 15 ms, p95 under 17.5 ms, worst 69 ms (a GC collection) |
| flash, RAM | firmware +14.0 KB (SKK frozen, native preedit); static RAM +100 B; free heap after boot 140,992 B |
| regression (`kagura-desktop-device.py`, log `hardware/phase5-regression-75134de.txt`) | `desktop_ja` 11/11 scene and VRAM CRCs, `ERROR_CODE` 0, soak of 10,497 updates with 0 failures, console back, soft and hard reset |
