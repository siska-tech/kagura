# Native Desktop foundation — Stage 5

Native GUI source ownership now lives in `core/` and `gfx/`. The source bytes
are unchanged from PR #73. Old native source/header paths forward to these
canonical files so existing experiment builds and bindings remain buildable.
Compile either the canonical C files or their compatibility wrappers, never
both. Text/runtime/platform ownership still migrates in separate follow-up PRs.
The old experiments and historical evidence remain at their original paths.

See [architecture audit](docs/architecture.md), [Japanese GUI specification](docs/japanese-gui.md),
[PR sequence and risks](docs/plan.md), and [validation/memory report](docs/validation.md).
See the [native source ownership report](docs/native-ownership.md) for the
current follow-up's measurements and compatibility contract.

## Build without a scripting runtime

Supported validation toolchain: GCC on Linux/WSL, CMake 3.13+, Python 3.
The current target flags are GNU flags; MSVC support is not claimed.

```sh
cmake -S software/desktop -B build/native -DCMAKE_BUILD_TYPE=Release -DKAGURA_DESKTOP_WITH_WREN=OFF
cmake --build build/native -j4
ctest --test-dir build/native --output-on-failure
```

`Kagura::Text` exposes `kj_text.h`, immutable font data, decoding, measurement,
generic clipped drawing and packed 4bpp drawing. `Kagura::Native` adds `kd_app.h`,
`kd_desktop.h` and `kj_desktop.h`. Neither links Wren or MicroPython, allocates a
font cache, or acquires hardware. Consumers supply desktop ownership and a sink.
`Kagura::Application` adds the existing single-owner application model and direct
transport, also without a VM; the platform supplies `kh_*`. The runtime-free
host application test checks its seven frames against the Wren reference CRCs.

## Bounded Wren integration

Acquire the pinned VM using `experiments/wren-rp2040/tools/acquire.py` first.
The source manifest is verified at configure time; no network access occurs in
the build. Wren is MIT licensed; the font retains its separate Misaki notice.

```sh
cmake -S software/desktop -B build/desktop -DCMAKE_BUILD_TYPE=Release
cmake --build build/desktop -j4
ctest --test-dir build/desktop --output-on-failure
bash software/desktop/tools/validate.sh
bash software/desktop/tools/build_arm.sh
QEMU=/path/to/qemu-arm python3 software/desktop/tools/arm_checks.py
bash software/desktop/tools/build_pico.sh
python3 software/desktop/tools/memory.py
bash experiments/wren-japanese-desktop/tools/build_pico.sh
python3 -I software/desktop/tools/compare_elf.py
```

`Kagura::WrenDesktop` is the existing single-application integration. Do not link
both it and an independently owned native Desktop into one firmware. The object
modules share compiled code, not instantiated desktops. Tests have their own
process-local owners; host mock FPGA storage is never linked into RP2040.

Pico build pins SDK 2.2.0 and TinyUSB commits, preserves the reference linker
policy, generates ELF/map only, and has **no upload or programming target**.
The CPU-only ARM executable is not a Pico image or timing model.

All implementation paths are explicitly listed in `cmake/modules.cmake`.
Public aliases are build integration boundaries, not a new stable binary ABI.
The native core/raster no longer compile through experimental paths. Text,
application/runtime and hardware entry-point sources still do.
