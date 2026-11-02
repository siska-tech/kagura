# Reusable Native C Japanese Text Engine

Portable C11 UTF-8, KJ8F glyph lookup, measurement, clipped rasterization and packed 4bpp drawing. **No Wren, MicroPython, OS, filesystem, FPGA or heap dependency.** Validated independently before enabling native Desktop titles. No hardware was accessed or flashed.

References: Draft PR #68 at `be344f5c742101f0cff170a29f63d09c0a17c441` and Draft PR #70 at `1c089f2b5d22c4cded5a87f96c8ad74dd3a55914`. This isolated branch uses the latter as its review base; the engine itself links neither runtime. Neither reference branch is modified or merged.

## Existing assets and ownership findings

* `software/micropython/fonts/misaki8.kfnt` is the existing **7,171-glyph, 71,718-byte** Misaki Gothic asset, SHA-256 `cbfb1071801f7ed3b6637bb6763219e59d86c13bd149169bbbab5bca753d9238`. Its location under MicroPython does not make its format or glyphs runtime-specific.
* KJ8F v1 is an 8-byte little-endian header, then sorted records `{u16 BMP scalar, u8 rows[8]}`. Rows are top to bottom, bit 7 at the left. Half-width source glyphs are already centred in 8×8 cells. No glyph shape is modified here.
* The existing native `kd_font_system` uses full-width ASCII forms in 8×8 cells; `kd_font_small` uses 4×8 ASCII. Their `kd_text*` APIs treat input as printable ASCII bytes. They remain unchanged. The adapter supplies their exact 95-glyph tables as bounded overrides for ASCII; Japanese glyphs remain 8×8.
* One `kd_desktop` owns its **32,000-byte** linear 4bpp framebuffer plus damage/window/snapshot state. Drawing through `kd_fb_pixel` preserves clipping and exact changed-tile marking. The compositor's existing 1,280-byte snapshot and ownership rules remain unchanged. Neither a full-screen tile mirror nor a second framebuffer is added.

`tools/gen_font_c.py` embeds the existing asset verbatim as a generated read-only C array after checking its hash. It downloads nothing. The two optional native integration sites are title drawing and bounded title copying in `kd_gfx.c` / `kd_desktop.c`, enabled only by **KD_NATIVE_TEXT**. Default native builds retain the original paths. Menus, buttons, labels and original ASCII APIs are not silently converted to Unicode in this milestone.

## Font license

Font: **Copyright (C) 2002–2021 Num Kadoma (門真なむ)**, Misaki Gothic 2021-05-05. The original font notice, preserved in [the repository font README](../../software/micropython/fonts/README.md), grants unlimited use, copy and distribution, with or without modification, commercially or noncommercially, and disclaims warranty. This font data is **not Apache-2.0**. Generated data carries `LicenseRef-Misaki`; new engine/adapter code is Apache-2.0. See [NOTICE.md](NOTICE.md). No new font has been introduced.

## API and deterministic policy

Public portable API: [kj_text.h](include/kj_text.h). Native adapter: [kj_desktop.h](include/kj_desktop.h).

* `kj_utf8_next` accepts only shortest-form Unicode scalar encodings. Overlong forms, lone continuations, truncation, surrogates and values above U+10FFFF are rejected. **One malformed byte consumes one byte and yields U+FFFD**; a malformed three-byte sequence can therefore produce three replacements. This is deliberate byte-wise recovery, not a claim to Unicode maximal-subpart replacement. Empty/NULL input returns consumed=0; rendering rejects NULL with nonzero length.
* Font opening validates exact length/version/count and strictly sorted unique non-surrogate BMP records. Backing data is borrowed, immutable and must outlive the descriptor. ASCII overrides carry their own checked byte length and 4/8-pixel width.
* Missing glyphs, unsupported non-BMP characters and control characters use **U+FFFD if available, otherwise source U+003F, otherwise an embedded 8×8 box**. The bundled asset uses the question-mark fallback. Valid Unicode does not imply glyph coverage. No normalization, combining-mark composition, proportional layout, automatic wrapping or vertical writing is implied.
* Default KJ8F cells are 8 pixels. Desktop ASCII overrides advance 8 or 4 pixels; Japanese/fallback cells advance 8 pixels. Measurement and drawing share the same lookup/advance policy. LF moves to the next 8-pixel line; CR returns to its start. Empty text measures 0×0; a trailing LF includes its final empty line. Other controls, including embedded NUL in a length-bounded core span, use fallback. Native titles remain NUL-terminated and stop at LF/CR.
* `kj_draw` uses a synchronous caller-owned pixel target and half-open clip. It measures/validates first, so invalid arguments or measurement overflow draw nothing. Coordinates use 64-bit intermediates; extreme signed origins/clip endpoints cannot overflow the raster arithmetic. The input/font must remain stable across both passes and callbacks.
* `kj_draw4` supports caller-owned linear 4bpp, even x in the high nibble, checked capacity/stride, odd widths and preserved padding. Optional `changed` callbacks run only for changed pixels. The Desktop adapter instead uses the existing `kd_fb_pixel`, preserving native dirty-tile/statistics behavior.
* No engine function allocates. There is no mutable global state or glyph cache. Independent targets may use independent calls; a Desktop remains single-owner and must not reenter its compositor from callbacks.
* Window storage remains **24 bytes including NUL**. Copying stops before a complete decoded unit would exceed 23 bytes, so valid UTF-8 is never split. Invalid bytes retain the documented byte-wise fallback policy. Display fitting counts glyph advances, not UTF-8 bytes. A seven-glyph Japanese title occupies 21 bytes; this milestone does not expand title capacity.

Example, independent of Desktop:

```c
uint8_t pixels[16 * 16 / 2] = {0};
kj_surface4 surface = {pixels, sizeof pixels, 8, 16, 16,
                       {0, 0, 16, 16}, NULL, NULL};
const uint8_t text[] = {0xe7, 0xa5, 0x9e, 0xe6, 0xa5, 0xbd}; /* 神楽 */
kj_metrics measured;
kj_status status = kj_draw4(&kj_misaki8, text, sizeof text,
                            0, 0, 1, -1, &surface, &measured);
```

## Reproduction and validation

Linux/WSL: CMake, C11 compiler, Python 3; Arm GCC 14.2.1 for static RP2040-class measurements. No font download or hardware tools are needed.

```sh
cmake -S . -B build-core -DKJ_DESKTOP=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-core -j4
ctest --test-dir build-core --output-on-failure
cmake -S . -B build-host -DCMAKE_BUILD_TYPE=Release
cmake --build build-host --target kj_tests kj_oracle -j4
ctest --test-dir build-host -R 'text_core|unicode_font_oracle' --output-on-failure
cmake --build build-host -j4
ctest --test-dir build-host --output-on-failure
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_C_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' \
  -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined'
cmake --build build-asan -j4
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 \
  ctest --test-dir build-asan --output-on-failure
cmake -S ../c-gem-desktop -B build-baseline -DKD_SDL=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-baseline -j4
ctest --test-dir build-baseline --output-on-failure
python3 tools/compare_ascii.py build-baseline build-host/desktop
bash tools/arm_budget.sh
```

Results: **21/21 Release**, **21/21 ASan/UBSan**, **17/17 original opt-out baseline**. The core first passed its two standalone tests before GUI integration; final runs also include both core suites. Tests cover all **1,112,064 Unicode scalar roundtrips**, **85,547 CPython strict-decoder oracle cases**, all **7,171 source glyphs byte-exact**, malformed/truncated fonts, fallback, mixed text/measurement, exact-sized truncated UTF-8 spans, signed coordinate extremes, 4bpp capacity/stride/odd-width padding, transparency, repeated no-change drawing, native clipping/dirty tiles, alias-safe title copy, overlap/reveal and painter equivalence. The thirteen native mutation variants remain required to fail.

All **26 existing ASCII/GUI scenario and HDMI-reference images are byte-identical** between opt-out and Japanese-enabled builds. See [results/](results/) for test logs, hashes and link maps.

The native host demo `build-host/kj_desktop_demo OUTPUT_DIRECTORY` creates three streaming PPM screenshots with one Desktop and no image-sized export buffer. The committed PNGs are lossless 3× nearest-neighbour conversions for viewing: [Japanese title](results/japanese-title.png), [overlap](results/overlap.png), [revealed title](results/revealed-title.png). These are **C host output**, not hardware captures. The existing optional SDL viewer is not used, avoiding its host-only full-screen mirrors.

## Measured ROM/RAM budget

Arm GCC 14.2.1, Cortex-M0+, Thumb, `-Os`, function/data sections. Read-only totals exclude debug/file-format metadata. [Machine-readable accounting](results/arm-budget.json), [object sections](results/arm-objects.txt), [compiler stack frames](results/arm-stack-frames.txt).

| Component | Read-only bytes | Writable static RAM |
|---|---:|---:|
| Complete portable engine object, all APIs | **2,055** | **0** |
| Existing KJ8F bytes + immutable font descriptor | **71,742** = 71,718 + 24 | **0** |
| Native adapter object | **347** | **0** |
| All three objects before link elimination/alignment | **74,144** | **0** |

An identical minimal native Desktop link probe is **12,088 B ROM** without the option and **85,792 B ROM** with Japanese titles: **+73,704 B ROM (~72 KiB), +0 B static SRAM** after link elimination. Both use **34,164 B static RAM**, comprising the unchanged **34,160-byte Desktop** (including its 32,000-byte framebuffer) and a 4-byte probe result. No framebuffer or window-state size increases.

The standalone core link probe is 74,438 B ROM / 36 B static RAM. Its **32-byte test surface and 4-byte result belong to the probe**, not the engine. The analysis ELFs intentionally lack Pico boot2/vectors, SDK/USB and a load target; **they are not firmware to run or flash**. Their maps measure a portable link, not a whole integrated Pico firmware image.

ARM caller-owned descriptor sizes: font **24 B**, glyph **8 B**, metrics **28 B**, pixel target **24 B**, packed surface **44 B**, decoder result **8 B**. Descriptors can be stack-local; the bundled descriptor is in ROM. Largest compiler-reported engine frame is `kj_draw` **200 B**. The longest direct in-engine call-chain estimate is about **424 B** for packed drawing, before caller/callback/interrupt usage. This is a static analysis, **not a measured hardware stack high-water mark**; keep PR #70's 48 KiB stack reservation unchanged.

For a future flash-resident PR #70 integration, the font naturally resides in flash, so the expected incremental persistent native SRAM is zero and ROM growth is approximately 72 KiB. UTF-8 strings themselves still occupy application/VM bytes; this is not a claim of zero total heap growth. That is an **estimate from a different link**, not an updated Wren firmware measurement. PR #70's 45,556 B static SRAM / 132 KiB allocator / 48 KiB stack / 8 KiB reserve and 31.51 KiB unassigned layout have not been rebuilt or changed here. A full integration must relink, remeasure and retain its protections.

## Next Wren-facing steps

1. Keep this validated native API as the implementation. Do not load/copy the font into the VM heap or add a tile/glyph framebuffer cache by default.
2. In a separate integration change, replace PR #70's explicit ASCII-only title rejection with checked `wrenGetSlotBytes` length handling and whole-codepoint copying into native-owned title storage. Decide and document invalid-byte/embedded-NUL handling at the foreign boundary; do not retain a VM string pointer.
3. Expose measurement and clipped text drawing only if the application needs them, borrowing the Desktop's existing framebuffer/clip under its present non-reentrancy guard. Keep allocator/OOM cleanup and native window ownership unchanged.
4. Add Wren/native CRC equivalence, Japanese-title overlap/reveal, GC/lifecycle/OOM regressions and a new linked map before any separately approved hardware test. Budget real interrupt/callback stack use; do not lower the 48 KiB reservation.

No Wren binding, SKK, IME, full editor, filesystem integration, FPGA ABI change, hardware programming or merge is included in this milestone.
