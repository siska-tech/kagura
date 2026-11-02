# Memory-audit provenance

All execution was on the PC, including ARM CPU emulation. No Pico, serial port,
BOOTSEL volume or device flash was accessed. This directory supersedes the
initial memory/stack interpretation while retaining original benchmark logs.

- Wren: `99d2f0b8fc2686134b32b18166e037639f7e9f2c`, source manifest unchanged.
- Arm GNU 14.2.Rel1, GCC 14.2.1 20241119, Cortex-M0+ Thumb soft float, `-Os`.
- CPU emulator: existing qemu-arm 10.2.1, Linux user mode, Linux process stack.
- Memory binary SHA-256:
  `2d7149c9177d5213a19ead6da42fd3641b1c4b63d43414640ae0c0b6341e4015`.
- Detailed snapshots add no timing evidence; all emulated time fields are zero.
- Reproduce memory runs with `tools/build_arm_memory.sh`, then
  `tools/memory_audit.py`; exact requested and physical minima are binary/layout
  dependent. The latter script validates all balances and bounded recovery runs.
- `_sbrk` models the pinned SDK's strict upper limit and supports downward trim;
  current break and maximum-ever break are separately recorded. The SDK malloc
  wrapper/USB and Pico printf/IRQ behavior are not emulated.
- SDK/TinyUSB/picotool/CMake pins remain as documented in pico/ACCEPTANCE.md.
  Three offline no_flash builds cover the current guarded layout, optional
  scratch expansion and Wren-only LTO. Each has independent ELF/UF2 byte checks,
  eight malformed UF2 rejections, and a separate layout/symbol audit.
- `check_layout.py --min-arena 135168` rejects the best expanded candidate for
  positive GUI acceptance. The old 32 KiB-stack image is separately rejected.

Desktop state sizing reads the existing separate local Desktop worktree only.
No Desktop sources were changed or linked into Wren. Input header SHA-256:

| Existing input | SHA-256 |
|---|---|
| experiments/c-gem-desktop/src/kd_desktop.h | 31a3eb3d3f4c2ca6ce81961ab9164c724a756bbc6ae4c417c2a5bf6b62615e7b |
| experiments/c-gem-desktop/micropython/kagura_desktop/kdm.h | 7ac46e0c629ada2f73bda83b399a1fd9a578e2ee75aa8e0f966f51c6d3aa989a |

`tools/desktop_sizes.c` emits arrays sized by `sizeof` for inspection, never for
linking. Example from the experiment directory (the root worktree contains the
existing Desktop experimental branch):

```sh
arm-none-eabi-gcc -mcpu=cortex-m0plus -mthumb \
  -I../../../experiments/c-gem-desktop/src \
  -I../../../experiments/c-gem-desktop/micropython/kagura_desktop \
  -c tools/desktop_sizes.c -o build-arm-memory/desktop_sizes.o
arm-none-eabi-nm -S --radix=d build-arm-memory/desktop_sizes.o
```

The same header build with `-mcpu=cortex-m33` confirms identical 34,160 B desktop
and 45,960 B retained state sizes. This is an ABI-size check, not an RP2350 VM
build or stack measurement. A fresh main-only checkout needs the separately
identified Desktop/Stage 3A reference sources to repeat this optional sizing.
