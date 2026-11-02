# RP2040 SRAM-only benchmark of the C desktop core

Stage 1 of the hardware validation. It times the same workloads as `kd_bench` and the qemu instruction counts (`bench/workloads.h`) on a real RP2040.
The program runs entirely from SRAM, with no KAGURA FPGA I/O, no GPIO other than USB, no flash write, no filesystem change, and no change to the installed MicroPython firmware.

**Status: built and statically verified; not yet run on hardware (awaiting approval).**

## Build (WSL)

```sh
export PICO_SDK_PATH=$HOME/opt/pico-sdk-2.2.0
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$HOME/opt/cmake-3.31.6-linux-x86_64/bin:$PATH"
cmake -S experiments/c-gem-desktop/pico -B build/c-gem-rp2040 -DCMAKE_BUILD_TYPE=Release \
      -Dpicotool_DIR=$PWD/build/starfall-pico/_deps/picotool   # reuse an already fetched picotool
cmake --build build/c-gem-rp2040 -j
build/c-gem/kd_bench --crc 8 > build/c-gem-rp2040/pc-crc.txt   # reference CRCs from the PC build
```

There are two variants of one program (`main.c`, `PICO_DEFAULT_BINARY_TYPE=no_flash`):

| target | memcpy/memset, division | why |
|---|---|---|
| `kd_rp2040_bench` | Pico SDK defaults: boot ROM memory routines, SIO hardware divider | what a firmware build would use |
| `kd_rp2040_bench_plain` | compiler/newlib implementations | closest to the qemu instruction counts |

Both use `-O2` for the core, as the counts did, and set `clk_sys` to 125 MHz, the clock of the estimates and of the KAGURA-UI records.

## What the program does

1. Enables the watchdog (8 s) and sets `clk_sys` to 125 MHz.
   Calling `watchdog_enable()` overwrites the boot-to-RAM magic in watchdog scratch 4, so any later watchdog reset (a hang, a fault, or the final `watchdog_reboot(0, 0, …)`) takes the normal flash boot path back to the installed MicroPython.
2. Paints guard words over the free part of the stack, all of SCRATCH_X (core 1's unused stack) and all main RAM above the heap.
3. Waits for a USB CDC host and the character `g`.
4. Prints `KDRP_INFO` (variant, `clk_sys` and the frequency counter's measurement of it) and `KDRP_LAYOUT` (linker symbols).
5. Correctness pass: for every workload, setup plus 8 samples, then the CRC32 of the framebuffer and the exported VRAM copy (`KDRP_CRC`). This must equal `kd_bench --crc 8` on the PC.
6. Timing: for every workload, 4 warm-up and 32 measured samples.
   Each sample runs the untimed pre-step and then, with interrupts masked, the operation plus render, then the TILE4 export. The cycles come from SysTick (24 bits at `clk_sys`, falling back to the 1 µs timer above 100 ms).
   Output `KDRP_TIME`: render, export and total p50/p90/max cycles; tiles; bytes.
7. `KDRP_MEM`: static size, malloc arena and in-use bytes, stack peak, and intact guard words in each painted region. Then `KDRP_DONE`.
8. Waits for `r` (or 10 s) and calls `watchdog_reboot(0, 0, 10)`, a regular flash boot.

## Static verification (done, no device involved)

ELF layout, `kd_rp2040_bench` (the plain variant differs by a few hundred bytes):

| region | address | size |
|---|---|---:|
| entry point | `0x20000001` (Thumb), the lowest loaded address | |
| loaded image: `.text`, `.rodata`, `.binary_info`, `.data` | `0x20000000–0x2001027C` | 66,172 B |
| `.bss`: desktop state 34,792 B, RAM "VRAM" 32,000 B, staging 1,280 B, SDK/USB | `0x20010280–0x20021F3C` | 72,892 B |
| heap (`__end__` to `__HeapLimit`), unused by the program | `0x20021F3C–0x20040000` | 123,076 B |
| SCRATCH_X, unused, painted as a guard | `0x20040000–0x20041000` | 4,096 B |
| core 0 stack in SCRATCH_Y, MPU no-access guard of 32 B at its bottom (`PICO_USE_STACK_GUARDS`) | `0x20041000–0x20042000` | 4,096 B |

- **Program headers:** exactly one `PT_LOAD` with file data, at `0x20000000`. The stack segment is NOLOAD.
- **Flash:** nothing is placed in `0x10000000+`.
- **Flash code:** no `flash_*` function is linked.
  The SDK makes `flash_get_unique_id` panic in no_flash builds, and the USB serial number is the fixed placeholder `EEEEEEEEEEEEEEEE`, so it is never read from flash.
- **ROM lookups:** only the float and double function tables (`__aeabi_float_init`, `__aeabi_double_init`).
- **Reboot paths:** the stdio_usb reboot-to-BOOTSEL paths (1200 baud and the vendor reset interface) are compiled out, and `rom_reset_usb_boot*` is not linked.
- **Stack:** the largest frames are `kd_desktop_render` 896 B, `damage_from` 472 B, `menu_hook` 288 B, `kd_filemgr_open` 280 B and `main` 224 B.
  The deepest chains add up to about 2.3 KB, including an interrupt frame (**estimate**), against 4 KB. The device measures the real peak.

UF2 (`tools/rp2040_sram_bench.py verify-uf2`), against the datasheet's rules for RAM-only binaries (RP2040 datasheet 2.8.4.2):
- 259 blocks, all with valid magic, flags = familyID-present only (no `NOT_MAIN_FLASH`), family `0xE48BFF56` and 256-byte payloads, numbered 0..258 with no gaps or duplicates;
- every target inside main SRAM `0x20000000–0x20042000`, the first block at `0x20000000`; the boot ROM decides "RAM binary" from the first block;
- no block in flash or in the XIP cache alias;
- the payload equals the ELF load image byte for byte, and padding is zero;
- the ELF entry is the lowest address, where the boot ROM enters RAM binaries.

The verifier rejected seven deliberately bad inputs: a flash target in the first block, a flash target in the last block, the `NOT_MAIN_FLASH` flag, a RAM overrun past `0x20042000`, one changed payload byte, a wrong family ID, and an existing flash UF2 (`build/starfall-arcade-*.uf2`).

## Why loading through BOOTSEL does not touch flash, and how that is checked

What the datasheet says (RP2040 datasheet section 2.8.4):
- **Transfer type:** "the type of binary being downloaded ... is determined by the address of the first UF2 block encountered".
  A RAM-only binary must have all data in `0x20000000–0x20042000` (or the cache alias), and "a change of ... the binary type ... will discard the current transfer".
- **Entry:** "A downloaded RAM only binary is entered by watchdog reset into the start of the binary, which is calculated as the lowest address of a downloaded block".
- **Erasing:** the 4 kB sector erase is described only for flash binaries.
- **Other files:** files that are not UF2 "are not stored".
- **`machine.bootloader()`** jumps to the boot ROM's USB boot; that is a reset, not a write.

The datasheet does not say in so many words that flash is untouched for a RAM-only download. The procedure therefore does not rely on it alone. Three independent checks:

1. **Static:** the exact file to be copied is verified block by block immediately before copying (above). Nothing in it targets flash, and the program contains no flash code.
2. **Empirical, with a control:**
   - The installed MicroPython computes a SHA-256 over the whole 2 MB flash (`0x10000000–0x10200000`) through XIP reads only (`uctypes.bytearray_at`).
   - A normal reboot follows, and the hash is taken again. It must be unchanged, or the run stops before BOOTSEL; this proves the comparison is meaningful (boot.py writes nothing).
   - After the benchmark the Pico returns to flash MicroPython and the hash is taken a third time. It must equal the first.
3. **Fail-safe return:** the RAM program enables the watchdog first. A hang or fault, including the MPU stack guard, returns to flash MicroPython within 8 s. Unplugging USB always works too: SRAM content is lost and the Pico boots from its unchanged flash.

## Loading procedure (for approval)

Run from the repository root in Windows PowerShell, with the uv CPython and `build/transport-analysis/python-deps` (mpremote 1.29.0, pyserial 3.5) used by the existing device tools.
Close other serial terminals first.
The Pico must be the only Raspberry Pi USB device attached. The tool refuses otherwise, and never prints the USB serial.

```powershell
$py = "$env:APPDATA\uv\python\cpython-3.14.7-windows-x86_64-none\python.exe"
$env:PYTHONPATH = "build\transport-analysis\python-deps"
& $py experiments/c-gem-desktop/tools/rp2040_sram_bench.py run --approved `
    --uf2 build/c-gem-rp2040/kd_rp2040_bench.uf2 --elf build/c-gem-rp2040/kd_rp2040_bench.elf `
    --log build/c-gem-rp2040/device-sdk.txt
# second run with the _plain variant, log device-plain.txt
& $py experiments/c-gem-desktop/tools/rp2040_sram_bench.py summarize build/c-gem-rp2040/device-sdk.txt `
    --crc build/c-gem-rp2040/pc-crc.txt --counts build/c-gem-arm/report.md
```

What `run` does, step by step (every device step is logged):

1. Finds the only Raspberry Pi USB device (MicroPython CDC), keeping its serial in memory. Verifies the UF2 against the ELF.
2. **Hash 1:** a raw REPL without soft reset runs the read-only flash hash.
3. **Control:** `machine.reset()`. Waits for the device to leave and come back, then **hash 2**. If it differs from hash 1, the run stops here.
4. `machine.bootloader()`: the boot ROM's USB boot. Waits for exactly one drive whose `INFO_UF2.TXT` says `Board-ID: RPI-RP2` and logs that file (boot ROM version).
5. Verifies the UF2 again, then copies that single file to the drive root with one binary write.
   The boot ROM loads it into SRAM and enters it by watchdog reset.
6. Waits for the program's CDC port (serial `EEEEEEEEEEEEEEEE`), opens it at 115200 baud (never 1200), sends `g`, and logs every line up to `KDRP_DONE` (timeout 300 s). Then sends `r`.
7. The program reboots into flash. Waits for the device to leave and for MicroPython to return, then **hash 3**.
   The run is OK only if hash 3 equals hash 1 and `KDRP_DONE` arrived.

Abort and recovery:

| Situation | Effect | What to do |
|---|---|---|
| Any check fails before step 4 | No BOOTSEL entry, no copy | Nothing |
| The program does not enumerate | The watchdog returns the Pico to flash MicroPython within about 8 s (the boot ROM itself returns to BOOTSEL only if the download is incomplete) | Unplug and replug USB |
| No `KDRP_DONE` | The log is kept | Unplug and replug USB if MicroPython does not come back |

The FPGA is not addressed at any point: its configuration and the HDMI output keep whatever they showed. MicroPython's boot.py restores the console after step 7.

Device-side effects:
- the Pico reboots three times (control reset, BOOTSEL, return to flash);
- SRAM content is replaced;
- a host-side `kd_rp2040_bench.uf2` "file" appears on the RPI-RP2 drive (not stored by the device).

Nothing else changes.
