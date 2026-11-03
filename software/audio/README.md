# KAGURA audio: HAL, KSNG songs and player

Native C audio for KAGURA-9. It is reusable by standalone C programs and built into the KAGURA MicroPython firmware as `kagura_audio`. 神楽トラッカー (`software/micropython/examples/desktop_tracker.py`) is built on it.

| Directory | Contents | Depends on |
|---|---|---|
| `hal/` | `ka_audio`: the six-voice synthesizer behind a write cache; frames of register writes | C11 |
| `seq/` | `ks_song`: the KSNG format, checked parse, pack/unpack; `ks_player`: the deterministic player | hal |
| `backend/` | `ka_kagura_host`: sends frames over the RP2040 C host driver (`software/pico/kagura_host.c`) | hal, Pico SDK |
| `binding/` | `kagura_audio`, the MicroPython user C module | hal, seq, MicroPython |
| `pico/` | a standalone C program, run from SRAM: test melody, demo song, timing probe | everything above |
| `songs/` | `demo.ksn`/`.h` (composed with the tracker's keys), `click.ksn`/`.h` (a timing probe) | |
| `tests/` | C tests (HAL against an FPGA model, parser, player, mutants), MicroPython tests (binding, tracker) | |
| `tools/` | `test.sh`; `make_fixtures.py` | |

Python side: `software/micropython/kagura/music.py` (frozen) has `AudioSession`, which sends frames over the console's SDK device, and `Song`, the editable song model.

## Hardware (what the HAL drives)

From [the audio spec](../../docs/audio-spec.md), unchanged (no RTL changes):

- Six voices: pulse 0..2 (8-bit duty), noise 3 (15-bit LFSR, 16-bit period), wave 4..5 (signed 8-bit, 32/64/128/256 samples).
- 24-bit phase step, 48 kHz.
- Each voice has an independent left and right gain (0..255), plus `MASTER_GAIN`.
- All settings are shadow registers behind `AUDIO_REG_INDEX`/`DATA`. `AUDIO_COMMIT` applies them all at one sample boundary and swaps the two wave banks. A commit is refused while the previous one is applying (BUSY_CONFLICT), or if a STEP or LEN_LOG2 is invalid (BAD_ACCESS).
- PCM (CAPS b3): two channels of signed 8-bit PSRAM samples at 48 kHz. The HAL only stops them (silence); playback stays with `kagura.audio.Audio`.
- No ADSR, timers or timestamped commits in hardware. Envelopes and timing are software.

## Architecture

```
 MicroPython app (tracker UI, game)          standalone C game
        |  kagura.music.AudioSession                |
        v                                           v
 kagura_audio (binding) ---------------> ks_player (KSNG, ticks) ---> ka_audio (write cache)
                                                                          | ka_flush(): frame
        +-- transport owner sends the frame: wave uploads, pairs, AUDIO_COMMIT
            MicroPython: the console's SDK device and its accelerated link
            C: ka_kagura_host.c over kagura_host.c
```

- **The HAL never touches the hardware.** Calls change the *wanted* state. `ka_flush()` compares it with what the hardware holds and makes a frame of only the differences. The owner of the FPGA transport sends the frame: wave uploads, then register pairs, then AUDIO_COMMIT.
  - The register logic exists once, in C. The Python side only moves bytes.
  - There is still one transport, shared with the desktop and console, as before.
- **Wave banks.** Every commit swaps the banks, so after a wave changes the HAL uploads it before each of the next two commits. A change of wave content alone forces a commit.
- **Recovery.** `ka_invalidate()` forgets what the hardware holds, so the next frame rewrites every register and both wave banks. It is used after a failed send, after other code wrote audio registers, and at `ka_init`. The first frame of a session is that full rewrite (silence), which also recovers from whatever an earlier program left playing.
- **Ownership.** One audio owner at a time. `kagura.audio.Audio` still works; after using it during a session, call `AudioSession.invalidate()`.
- **Soft reset.** The binding's C state points into the GC heap (the song copy), so the board hook `MICROPY_BOARD_START_SOFT_RESET` drops it. Every call but `init()` then raises.
  - The hook cannot silence the FPGA, because the transport belongs to Python. A program that ends with `close()` in a `finally` (as the tracker does, including on Ctrl+C) leaves silence.
  - Otherwise the next session's first frame silences.

### Timing: why pumped, not interrupt-driven

The scheduler is time-driven and pumped at safe points. There is no timer IRQ.

- **No usable interrupt context.** On the board the PIO transport is owned by Python (`device.busy`, one transaction at a time). An interrupt cannot safely start a transaction in the middle of a desktop tile run, and the hardware has no timestamped commit.
- **Ticks fall at exact times.** Tick *k* is due at `start + floor(k × 2,500,000 / BPM)` µs, kept with an integer remainder, so the tempo cannot drift however the pumps fall.
- **Late pumps.** `ks_player_advance(now)` runs every tick that is due, in order: the music state stays exact, and the HAL sends the final state once. Further behind than 250 ms (a long stall), the player resynchronises, as a pause would.
- **Where the pumps come from.** In MicroPython, `AudioSession.pump()` runs at safe points: the app's loop, and `Desktop.present()` at its start and after every tile run (`desk.audio = session`). So the worst-case lateness is one transport transaction plus whatever the app does between pumps.
- **Measured, not claimed.** The measurements below are the evidence. There is no hard real-time guarantee.

## Song format: KSNG v1

Little-endian. A file is checked completely by `ks_song_parse` before use; after that, playback reads it without bounds checks. The maximum size is 65,535 bytes.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | magic `KSNG` |
| 4 | 1 | version 1 |
| 5 | 1 | flags: b0 LOOP (at the end go to the loop order, else stop); others 0 |
| 6 | 1 | tracks T, 1..6 |
| 7 | 1 | instruments I, 1..32 |
| 8 | 1 | waves W, 0..16 |
| 9 | 1 | patterns P, 1..64 |
| 10 | 1 | orders O, 1..128 |
| 11 | 1 | loop order, < O |
| 12 | 1 | speed: ticks per row, 1..31 |
| 13 | 1 | tempo: BPM 32..255 (tick = 2.5 s / BPM) |
| 14 | 2 | reserved, 0 |
| 16 | 16 | title: printable ASCII, NUL-padded |
| 32 | 16 | author: same |
| 48 | T | the hardware voice of each track, 0..5, all different |
| | O | orders: pattern numbers < P |
| | 8 × I | instruments: kind (0 pulse, 1 wave, 2 noise), data (pulse duty / wave number / 0), volume 0..15, pan 0..255 (128 centre), attack, decay (ticks), sustain 0..15, release (ticks) |
| | W × | wave: LEN_LOG2 (5..8), then 2^LEN signed samples |
| | P × | pattern: rows (16, 32 or 64), packed size (u16), packed rows |

**Packed rows.** Each row has one cell per track. A cell is a mask byte (b0 note, b1 instrument, b2 volume, b3 effect and parameter; b4..7 must be 0), followed by the fields it marks. The rows must use exactly the packed size.

**Cell fields:**
- note: 1..96 is C-0..B-7 (MIDI 12..107); 97 is note off.
- instrument: < I.
- volume: 0..15.
- effect: one of the effects below.

An empty cell is one byte.

| Effect | Parameter | |
|---|---|---|
| 0xy | arpeggio | +0, +x, +y semitones by tick (00: none) |
| 1xx / 2xx | slide up / down | xx sixty-fourths of a semitone per tick |
| 3xx | tone portamento | towards the cell's note, without retrigger |
| 4xy | vibrato | speed x, depth y |
| 7xx | duty | pulse duty |
| 8xx | pan | 0 left, 128 centre, 255 right |
| Axy | volume slide | +x / −y sixteenths per tick |
| Bxx | jump | to order xx |
| Cxx | cut | at tick xx of the row |
| Dxx | break | to row xx of the next order |
| Fxx | speed / tempo | xx < 32: ticks per row; else BPM (F00 is invalid) |

**How a track sounds.** An instrument's kind must fit its track's voice: pulse on 0..2, noise on 3, wave on 4..5. A note that does not fit is silent and counted (`mismatched`). The envelope runs at the tick rate, and the gain sent to the hardware is volume × envelope × pan.

**Sizes.** The demo song (two 32-row patterns, four tracks in use, two waves) is 725 bytes. A 64-row pattern of six empty tracks is 387 bytes.

## Using songs in games

MicroPython:

```python
from kagura.music import AudioSession
audio = AudioSession(kagura_console.screen.device)
audio.load(open('/songs/DEMO.KSN', 'rb').read())
audio.play()
try:
    while running:
        ...game frame...
        audio.pump()             # once or more per frame; allocates nothing
finally:
    audio.close()                # silence
```

- `kagura_audio.voices(mask)` gives voices back to the game for sound effects; the player never writes them.
- `kagura_audio.mute(mask)` silences tracks.

C (the tracker's 書き出し writes `NAME.H`, a song as a C array, as `songs/demo.h`):

```c
#include "demo.h"                  // static const uint8_t ksng_demo[]
ka_audio hal; ka_frame frame; ks_song song; ks_player player;
ka_init(&hal, caps);
ks_song_parse(&song, ksng_demo, sizeof ksng_demo);
ks_player_init(&player, &hal);
ks_player_load(&player, &song);
ks_player_play(&player, time_us_32(), KS_MODE_SONG, 0, 0);
for (;;) {                          // the game loop
    ks_player_advance(&player, time_us_32());
    ka_flush(&hal, &frame);
    if (ka_kh_send(&hal, &frame, KH_DEFAULT_TIMEOUT_US) != KH_OK) ka_invalidate(&hal);
    ...
}
```

`pico/main.c` is a complete example.

## Memory

| | RP2040 | |
|---|---|---|
| `kagura_audio` static state | 1,968 B bss | HAL 672, player 296, frame 100, two song headers |
| firmware text | +10,192 B | ca4be0e → phase 6 |
| song copy | the song's size, GC heap | one copy (two while `load` swaps) |
| standalone C program | 6,288 B bss, 1.2 KB stack peak | SRAM image 44 KB |

## Measurements

The standalone C program ran from SRAM with flash verified unchanged (`pico/`, log in `docs/hardware/`). The physical timing comes from the HDMI audio recorded by the UGREEN 15390 capture and analysed by `tools/kagura-audio-timing.py`.

| 20 s at 150 BPM, click probe | ticks / exact | late max (timer) | jitter on the HDMI audio p50 / p95 / max | tempo on the audio |
|---|---|---|---|---|
| transport idle | 1200 / 1200 | 8 µs | 14 / 35 / 73 µs | +15 ppm |
| transport 98 % busy (VRAM reads) | 1200 / 1200 | 3.2 ms | 1.25 / 1.65 / 1.67 ms | +16 ppm |

- **Tempo.** The +15 ppm is the clock offset between the RP2040 crystal and the FPGA/capture clock: it is the same in both runs.
- **Idle jitter** is the 48 kHz sample quantum.
- **Under load**, lateness is bounded by the longest transport transaction.
- **Cost.** A frame takes 130–160 µs to send from C. The demo uses 0.7 % of the CPU.


Measured on the board through MicroPython, under desktop load, with the tracker and long playback: [docs/hardware.md](docs/hardware.md).
- Ordinary desktop work keeps the click probe within about 5 ms of the beat.
- Window moves keep it within 8 ms.
- File I/O and GC pauses are the known limits.

## Tests

```sh
bash software/audio/tools/test.sh      # WSL/Linux, from the repository root
```

- **HAL** against a model of the FPGA's commit semantics. This includes 200,000 random calls, checking after every frame that the modelled hardware plays exactly what the HAL wants.
- **Parser:** every malformation, every truncation, 200,000 random corruptions, all under ASan/UBSan.
- **Player:** exact tick times at five tempos across the 32-bit wrap; the same music whether pumps are on time, erratic or folded; flow effects, envelopes, pitch effects, pan, pause, preview, reload, voice masks.
- **Mutants:** six that the tests must catch.
- **MicroPython:** the binding and the tracker on the unix port.
- **Fixtures:** the tracker's scripted session must compose `songs/demo.ksn` byte for byte again, and `tools/make_fixtures.py` must write `songs/click.ksn` again.

## 神楽トラッカー

`software/micropython/examples/desktop_tracker.py`, a music tracker in the native desktop's visual language. One window holds:

- **The pattern grid** (4×8 font): 16 rows and 4 of the 6 tracks at a time. The view pages to follow the cursor, and the playing row during playback.
- **The order list and the instruments** (8×8 font).
- **A status line**: state, BPM, speed, octave, instrument.

The cursor, its field and the playback row are movable fills under transparent text, so moving the cursor redraws a few tiles.

- **Keys** (FastTracker II layout): `z s x … /` and `q 2 w … p` are notes, `1` is note off, and hex digits fill the instrument, volume and effect fields. Delete clears a field; Insert and Backspace insert and delete rows.
  - `[ ]` change the octave and `- =` the instrument; Space plays the song and Enter the pattern, Esc stops.
  - Ctrl+Left/Right move through the order list, Ctrl+Up/Down change its pattern.
  - Ctrl+S, Ctrl+O and Ctrl+N save, open and start anew; F10 opens the menus.
- **Editing while playing** reloads the song at once, keeping the position.
- **Dialogs**: an instrument editor (kind, duty or wave, volume, pan, ADSR) and song settings (tempo, speed, loop, loop order, pattern length).
- **The wave editor** (instrument editor > 波形を編集…) draws a wave instrument's table: signed 8-bit samples, 32 to 256 of them (the FPGA's format), as bars on a 256×128 grid.
  - **Keys:** Left/Right choose a sample and Up/Down change it (Shift: ×16; PgUp/PgDn ±32; Home/End the extremes; Delete 0). Shift+Left/Right carry the value along, which draws with the keyboard.
  - **Presets:** 1 sine, 2 triangle, 3 sawtooth, 4 square, 0 flat. L changes the length (resampled); N copies the wave as a new one for the instrument.
  - **Sound:** Space plays a note with it. Every change goes to the HAL at once, so the note sounding plays the new wave from the next frame.
  - **Pointer:** pressing and dragging in the canvas draws, with interpolated lines. It is wired to POINTER_DOWN/MOVE/UP and tested by injecting them, so it works when a pointer is connected.
  - **Drawing cost:** one fill record per sample, so an edit redraws that column only (a few tiles). A 256-sample wave uses 256 of the desktop's 320 records. No framebuffer is allocated.
  - **Saving:** waves are saved in the song (KSNG wave records) and reload byte for byte.
- **Files**: `NAME.KSN` in one folder with write-then-rename. 書き出し also writes `NAME.H`. `ram_songs()` keeps them in RAM.
  - File I/O goes in 512-byte pieces with the audio pumped between them, so a save while the music plays is mostly in time; single littlefs operations can still take tens of ms.
- **A scripted session** (`main(script=True)`, `--host` on a PC) composes the demo song with the tracker's own keys. It plays two loops, saves, reopens and exports, printing a CRC per scene.
