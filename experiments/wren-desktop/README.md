# Minimal flash-resident Wren Desktop experiment

Status: host and CPU-emulated validation complete. Physical flash validation is now authorized, but requires all recovery gates to pass; see [HARDWARE.md](HARDWARE.md) for current preflight status. No Wren image has yet been flashed. See [REPORT.md](REPORT.md) for measured limits and the actual SRAM map. This is a separate experiment, not a replacement for MicroPython or the native desktop.

Inputs are pinned to PR #68 `be344f5c742101f0cff170a29f63d09c0a17c441` and PR #69 `d03912b4339495379302b286383eb40cf8a6d53e`. Their source directories and `software/` remain unchanged. `tools/verify_inputs.py` checks this. Wren revision `99d2f0b8fc2686134b32b18166e037639f7e9f2c` is MIT licensed; acquisition, manifest and license are inherited from `../wren-rp2040`.

## Reproduction (Linux / WSL)

Use CMake 3.31.6, GCC host compiler, Python 3, and Arm GNU toolchain 14.2.Rel1 (GCC 14.2.1). Run from this directory:

```sh
python3 ../wren-rp2040/tools/acquire.py
python3 tools/gen_app.py
python3 tools/verify_inputs.py
cmake -S . -B build-host -DCMAKE_BUILD_TYPE=Release
cmake --build build-host -j4
ctest --test-dir build-host --output-on-failure
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_C_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' \
  -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined'
cmake --build build-asan -j4
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 \
  ctest --test-dir build-asan --output-on-failure
cmake -S ../wren-rp2040 -B build-wren-baseline -DCMAKE_BUILD_TYPE=Release
cmake --build build-wren-baseline -j4
ctest --test-dir build-wren-baseline --output-on-failure
bash tools/build_arm.sh
# Set QEMU to a qemu-arm 10.2.1 executable if not on PATH.
python3 tools/arm_checks.py
export PICO_SDK_PATH=/path/to/pico-sdk-2.2.0
bash tools/build_pico.sh
bash tools/evidence.sh
```

Pico SDK commit must be `a1438dff1d38bd9c65dbd693f0e5db4b9ae91779`, TinyUSB `86ad6e56c1700e85f1c5678607a762cfe3aa2f47`. The SDK flash linker script is SHA-256 checked before deriving the experiment's bounded layout. Build output is `build-pico/wren_desktop_flash.elf` and `.map`; no UF2 or hardware loading command is generated. The committed detailed map and ELF analysis live in `results/`.

## Application and ownership

Exactly one static `kd_desktop` owns its original 32,000-byte framebuffer. The four foreign methods are `Desktop.open(title)`, `rect(x,y,w,h,color)`, `nextEvent()` and `present()`. The application opens one window, displays a copied ASCII title using the unchanged native renderer, updates one retained rectangle, consumes four native POD events and presents each update. Japanese UTF-8 is verified through Wren output, not through a new title renderer. The test-only overlapping native window uses the same desktop.

The 1,280-byte native snapshot is shared with tile export and initialization scratch only after rendering finishes. A synchronous busy guard spans rendering, acknowledged export and observers; reentrant UI calls are rejected. No pointer to VM-managed strings survives a foreign call. The direct sink blocks through VRAM write, a fresh DONE-tag fence and error check before acknowledging a run. Failed writes keep tiles dirty and latch transport failure; only explicit reinitialization repairs it. The fake external VRAM in tests is not linked into firmware.

OOM discards the entire interrupted VM through the allocator boundary, closes its native window, and frees every allocation through the ledger. It never resumes a damaged VM or invokes Wren finalizers during recovery. There are no foreign objects or external script resources. A later fresh VM can recover in the same bounded allocator arena. No tests or baseline OOM safeguards have been removed.

## Hardware boundary

This flash-resident image reserves 48 KiB native stack and 8 KiB recovery storage. It starts at 125 MHz with USB serial and an 8-second watchdog. A timeout, test failure or normal completion explicitly enters ROM BOOTSEL for restoration; an unexpected watchdog reboot is reported and stops the test. USB automatic reset interfaces remain disabled. Watchdog reset alone restarts **this flash image**, not MicroPython.

The authorized hardware procedure requires a full-flash backup/hash, proven BOOTSEL readback and a known-good MicroPython image before programming. `tools/hardware_run.py` writes only the ELF's sector-aligned flash prefix, checks the complete flash including the untouched tail, captures metrics and HDMI, then restores the original prefix and verifies all 2 MiB against the backup before rebooting MicroPython. Exact hashes, recovery log and `--approved` are required. Backups remain outside Git. The previous SRAM-only loading procedure cannot be used for this flash-addressed ELF. The firmware itself contains no erase/program routine.
