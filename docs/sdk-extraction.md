# KAGURA SDK extraction: dependencies and ownership

Status: analysis and plan (2026-11-12). The desktop already lives in siska-tech/kagura-desktop (siska-tech/kagura#96). This document decides what moves to a new **kagura-sdk** repository, what stays with the hardware in **kagura**, and how the two stay compatible. Nothing here changes behaviour; the extraction is a move plus pinning, with functional changes in separate PRs.

## 1. What exists today

| Path | Size | Talks to | Kind |
|---|---|---|---|
| `spec/registers.json` | | | **the hardware contract**: register ABI 0.6, the source of all generated constants |
| `tools/gen-registers.ps1` | | spec → `regs.py`, `kagura_regs.h`, `kagura_regs.inc` (+ RTL package) | generator, shared by both sides |
| `software/micropython/kagura` | 2.6 MB with examples | FPGA through `regs`, `device` | MicroPython SDK (see §2) |
| `software/micropython/kagura/ui`, `kagura_ja` | | `kagura.framebuffer`, `kagura.video` | UI toolkit, Japanese text |
| `software/micropython/boards`, `manifest.py`, `align_frozen.py`, `usermods/` | | MicroPython v1.26.0 rp2 port | firmware packaging |
| `software/micropython/examples` | | the SDK | demos: STARFALL, sakura, showcase, shooter, UI gallery |
| `software/audio` | 474 KB | `hal` emits register pairs; `backend/ka_kagura_host.c` sends them | C audio: HAL, KSNG player, `kagura_audio` binding |
| `software/pico` | 584 KB | PIO transport, `kagura_regs.h` | C host driver (`kagura_host`), `tile_fb`, diagnostics firmware, demos |
| `software/include` | | generated | `kagura_regs.h` |
| `software/starfall` | 209 KB | `backend.h` (host or Pico) | the original C game; also an RTL test (`test-rtl.sh`) |
| `software/w65c02` | | generated | `kagura_regs.inc` for the W65C02S host inside the FPGA |
| `software/tests` | | generated headers | header compile tests (`tools/test-headers.sh`) |
| `rtl`, `sim`, `boards`, bitstream tools | | | the hardware |

Cross references (grep, 2026-11-12):
- Hardware → software: `sim`/RTL tests use `software/starfall` (`test-rtl.sh`), the boot image tools and `software/w65c02`; CI's `phase1.yml` builds `software/pico`, `software/starfall` and `software/audio/pico`.
- Software → hardware: only the generated constants (`regs.py`, `kagura_regs.h`, `kagura_regs.inc`) and documentation links into `docs/` (register map, host interface, audio spec).
- 22 tools in `tools/` touch `software/` (UI measurement, asset generators, showcase packaging, the CI filter).

## 2. Layers inside the SDK

Read from the import graph of `kagura/*.py` and the C includes.

| Layer | MicroPython | C | Hardware-specific? |
|---|---|---|---|
| **L0 contract** | `kagura/regs.py` (generated) | `kagura_regs.h` (generated) | Kagura-9, ABI 0.6 |
| **L1 host transport** | `transport_rp2`, `dma_pack`, `acceleration`, `link`, `link_viper` | `pico/kagura_host.c`, `.pio` | RP2040 host + Kagura-9 bus protocol (SPI/QSPI, READY/BUSY) |
| **L2 device** | `device` (`Kagura`: registers, VRAM, FENCE, COMMIT, errors) | `kagura_host` API | Kagura-9 |
| **L3 Kagura-9 graphics and sound** | `video`, `framebuffer(_viper)`, `tileplane`, `image256`, `terminal`, `console`, `audio` | `pico/tile_fb*`, `audio/hal` (6-voice synth, register pairs), `audio/backend` | Kagura-9: tile/pattern model, 4bpp TILE4, palette banks, its synth |
| **L4 hardware-independent** | `kagura.ui` core (widget, layout, events, theme, canvas; `render` is the Kagura-9 backend), `kagura_ja` glyph decoding, `music` song/pattern model | `audio/seq` (KSNG format and player), `pico/img_quant` | no |
| **Apps** | `examples/*` | `starfall`, `pico/*_demo.c` | use the layers above |

Findings:
- The **L4 modules already have narrow seams**: `ka_audio` never touches hardware (it returns frames), `ks_player` only drives a `ka_audio`, `kagura.ui` reaches pixels only through `render.py`. They can be kept in the SDK as they are and gain a second backend later.
- `kagura_ja.Font` mixes glyph lookup (independent) with pattern upload through `kagura.video` (Kagura-9). Split later, behind the same public names.
- `kagura.music.AudioSession` takes a device and sends HAL frames: the transport-facing half is Kagura-9, the song model is not.
- `console`/`terminal` are Kagura-9 tile consoles; `console.active()` is a host convention (boot.py) and hardware-independent.
- `showcase_music.py` is an example, not API, yet kagura-desktop's showcase imports it for optional background music (§5).

## 3. Ownership after the extraction

| Repository | Owns | Why |
|---|---|---|
| **kagura** (hardware) | `rtl`, `sim`, `boards`, `spec/registers.json`, `tools/gen-registers.ps1`, synthesis and bitstream tools, releases and known-good bitstreams, hardware docs (register map, host interface, audio spec), `software/w65c02` (in-FPGA host constants) | the ABI is defined with the RTL; releases stay where they are |
| **kagura-sdk** | `software/micropython`, `software/audio`, `software/pico`, `software/include`, `software/starfall`, `software/tests`, the SDK tools (UI measurement, asset generators, showcase packaging, `build-micropython-unix.sh`, `rp2040-firmware.py`, `rp2040_sram_bench.py`) and the SDK docs | everything a host program links against |
| **kagura-desktop** | the desktop, editor, SKK, tracker | an application of the SDK (done) |

Generated constants: the SDK keeps committed copies of `regs.py`, `kagura_regs.h` and `kagura_regs.inc`, and a pin file `hardware.lock` naming the kagura commit and the SHA-256 of `spec/registers.json` they were generated from. CI regenerates them from that commit and fails on any difference. RTL tests that run SDK code (`starfall/test-rtl.sh`, boot images) stay in kagura and check out kagura-sdk at a pinned commit.

### Dry run (`tools/sdk-extraction-check.py`)

`docs/sdk-extraction-paths.txt` lists what moves, in `git filter-repo --paths-from-file` format. The check reads it and reports every reference that would cross the boundary. On main after #96:

| | |
|---|---|
| tracked files | 845: 584 move, 261 stay |
| kagura-sdk → kagura | 65 references in 25 files |
| kagura → kagura-sdk | 259 references in 22 files |
| already broken or generated paths | 46 in 29 files (not caused by the move) |

- **SDK → hardware, code:** only two scripts.
  - `software/starfall/test-rtl.sh` runs STARFALL against the RTL and testbenches. It is an integration test, so it moves to kagura beside the RTL tests and checks out kagura-sdk at a pin.
  - `tools/test-headers.sh` regenerates the headers with `tools/gen-registers.ps1`. It runs the generator from the pinned kagura commit.
- **SDK → hardware, documentation:** links to the hardware specifications (`docs/audio-spec.md`, `host-interface.md`, `memory-map.md`, `register-map.md`, `video.md`). These become links into kagura at the pinned commit. Generated files keep naming `spec/registers.json` as their source.
- **Hardware → SDK:** 169 of the 259 are CI configuration (`ci-changes.sh`, `test-ci-changes.sh`, workflows), which is split with the move. The rest are README and docs links, which become links into kagura-sdk.

## 4. Kagura-HD

Kagura-HD is a different graphics architecture, so the SDK does **not** force one graphics model on both:
- Kagura-9-specific modules keep their names (`kagura.video`, `kagura.framebuffer`, `kagura.tileplane`, `tile_fb`, the audio HAL) and are documented as the Kagura-9 implementation.
- What is shared is limited to what really is common: the host transport conventions where the bus matches, the device lifecycle (probe, ABI check, errors, `busy` ownership), `console.active()`, KSNG/`ks_player`, `kagura.ui` core, glyph decoding, image quantization.
- A future Kagura-HD implementation lives beside the Kagura-9 one (for example `kagura_hd/`), selected by the ABI that `Kagura.probe()` reads, and gets its own renderer backends. No common "surface" abstraction is introduced until two implementations exist to compare.

## 5. Plan

Each step is its own PR; none mixes a move with functional changes.

1. **Compatibility tests in kagura first** (before any move):
   - an API snapshot test: the public names and signatures of `kagura.*`, `kagura.ui`, `kagura_ja`, `kagura_audio`, and the public C headers (`kagura_host.h`, `tile_fb.h`, `ka_audio.h`, `ks_player.h`, `ks_song.h`), compared with a committed snapshot;
   - the generated-constants check against `spec/registers.json` (exists: `gen-registers.ps1 -Check`), extended to write the pin.
2. **Extract kagura-sdk** with `git filter-repo` (history kept), the same way as kagura-desktop. Paths stay the same (`software/...`), so the C and MicroPython APIs and the board directories are unchanged. Add `hardware.lock` and CI that checks out kagura at the pin.
3. **Remove the SDK from kagura**: kagura's CI checks out kagura-sdk at a pinned commit for the RTL tests that run SDK code.
4. **kagura-desktop**: point `sdk/` at kagura-sdk and `KAGURA_SDK_REF` at a pinned commit (today it follows `siska-tech/kagura` main).
5. **SDK cleanup** (separate PRs): move the background music used by kagura-desktop's showcase from `examples/showcase_music.py` into a public module (or have the showcase use `kagura.music`); split `kagura_ja.Font`'s glyph lookup from its Kagura-9 upload; document the layer of each module.

## 6. Pending hardware validation

The desktop split was verified in software only. Still to run on an RP2040 with KAGURA-9: TilePlane transfer overhead, HDMI rendering and VRAM readback, the desktop and SKK, the tracker, and the firmware built from kagura-desktop. The SDK extraction adds no hardware behaviour, so its validation is the same software CI plus these pending checks. Known-good firmware, bitstreams and the `abi0.6-2026-11-12` release are not changed or reclassified.
