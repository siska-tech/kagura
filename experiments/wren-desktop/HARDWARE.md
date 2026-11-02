# RP2040 hardware validation record — 2026-11-02

Status: **authorized, stopped at the recovery preflight gate; no flash programming yet**. Windows picotool sees RP2040 BOOTSEL but cannot open its vendor interface. The user is arranging WinUSB and has confirmed physical BOOTSEL/USB access, unchanged wiring/power and connected HDMI. No Wren hardware result or restoration success is claimed at this stage.

## Provenance and recovery evidence

* Initial PR #70 inspected at `a86d735a22b95b94b184b79fe5fb1da7ca8a79d5`, Draft/open. Original ELF SHA-256 `91d63f885e10160b95b0fecd2fd1bbc33a2aa97d939c17e5058fc2b0769e4d81`.
* The measurement harness adds latency counters, per-frame framebuffer/FPGA readback CRCs, expected OOM probes, stack/recovery canaries and explicit ROM BOOTSEL completion. No foreign method or font support is added. Watchdog, MPU guard, 48 KiB stack, 96 KiB normal payload limit and 132 KiB physical arena are retained. The native malloc-failure test deliberately permits a larger requested payload ceiling while retaining the same hard physical bound, as in the existing ARM recovery test.
* Pico: MicroPython identifies **KAGURA Raspberry Pi Pico with RP2040**, v1.26.0, build 2026-11-01, CPU 125 MHz. Existing communication is QSPI 5 MHz / four lanes: IO0–3 GP2–5, SCK GP6, CS GP7, BUSY GP8, READY GP9, IRQ GP10. FPGA ID `4b39`, ABI **0.6**, CAPS **0x5b**, 240 lines, 1,200 patterns, ERROR_CODE zero. [Device preflight](results/hardware/preflight-device.txt).
* Tang Nano 9K is the existing installation. The loaded FPGA bitstream's exact hash is not exposed through this ABI and was not independently established; ABI/CAPS are verified, not a fabricated bitstream revision. No FPGA firmware or nonvolatile storage was touched.
* Complete 2,097,152-byte original flash backup retained locally at `build/wren-desktop-hardware/flash-backup-20261102T142039Z/flash-2MiB.bin` in the parent workspace. SHA-256 **`d2ccc104c2a14a84e56501632ceb2ef802f3ad39c3493f42eba83c547f14987b`**. Device hash before/after dump, saved-file reread and independent host hashing agree. The backup is excluded from Git because it contains the user's filesystem.
* Known-good MicroPython image: `build/micropython-src/ports/rp2/build-KAGURA_PICO_PINNED/firmware.uf2`, SHA-256 **`9ebfa459351e7e402d7c5690a0ddfc405b91d65093162586e89198733d03f95c`**. All 1,667 flash UF2 payload blocks match the backup byte-for-byte through offset `0x68300`. The complete backup, rather than this program-only UF2, remains the restoration authority.
* Normal control reboot returned the HDMI console attached/unpaused with no error, and the full flash hash stayed unchanged. BOOTSEL reports `UF2 Bootloader v3.0`, `Board-ID: RPI-RP2`. The picotool **2.3.1 Windows** vendor connection then failed for lack of a suitable driver. Its attempted normal reboot also could not connect; the user has been told that the board is in BOOTSEL. [Failure evidence](results/hardware/recovery-preflight.txt).
* HDMI capture device UGREEN 15390 enumerates and an existing MicroPython HDMI image was captured. This is preflight signal evidence, not a Wren rendering result. USB power stability under the new workload has not yet been measured.

The official [picotool Windows instructions](https://github.com/raspberrypi/picotool#zadig) specify WinUSB on **RP2 Boot (Interface 1)**. Preserve the mass-storage interface. Programming remains forbidden until read-only `tools/recovery_preflight.py` successfully reads all flash through BOOTSEL, matches the backup, reboots and verifies MicroPython/hash again.

## Regressions and prepared test

After adding instrumentation: host Release **18/18**, ASan/UBSan **18/18**, unchanged Wren baseline **1/1**, and ARM CPU-emulated correctness, cap sweeps and native OOM recovery pass. Updated ARM emulation still peaks at 91,970 B requested payload; arena break is 126,032 B and painted stack upper bound 33,552 B. None of these are physical measurements.

The detailed linker map and program headers are regenerated for the measurement image. Its static SRAM is **45,556 B**, bounded arena **135,168 B**, stack **49,152 B**, recovery reserve **8,192 B**, and unassigned SRAM **32,268 B (31.51 KiB)**. Instrumentation adds **196 B static SRAM** over the initial PR #70 link; stack and heap reservations are unchanged. Firmware source is pinned at **`fdd45fbfc31453032d22930e3dcde2ea79c42a25`**, ELF SHA-256 **`1b90d5d63f8775e49724651bfffa6b906fcb5bd8d39d075af77f0ace8611bb39`**. The offline plan passed and limits programming/restoration to **`0x10000000–0x10026000`** (155,648 bytes), with the remainder of the 2 MiB compared unchanged. No programming command has been run.

Prepared sequence, requiring the exact artifact/backup hashes and explicit `--approved`:

1. `tools/hardware_run.py --plan-only ...` validates ELF-derived physical flash ranges and the linker layout without device access. The program binary is padded only to the last required 4 KiB sector; the same-sized original prefix is retained for restoration. No all-flash erase is used.
2. Read all 2 MiB again in BOOTSEL before the first write. Program the bounded prefix without executing, read all flash and compare both the programmed prefix and unchanged tail against the expected full image.
3. Boot once and verify runtime-reported heap/stack/recovery addresses against the ELF. Report raw reset reason separately from an unexpected enabled-watchdog reboot.
4. Run one visual application with seven acknowledged frames. Every 32,000-byte FPGA pattern plane is read back and compared byte-for-byte to native TILE4 export, then CRC-checked against the host golden. Only 64 bytes of stack scratch are needed; there is no second framebuffer. Frame zero precedes display enable and is not claimed as an HDMI image. Capture settled HDMI for visible frames 1–6 before advancing.
5. Reset latency counters, run twenty compiled callbacks without capture/readback delays, and report open/rect/event/present foreign-body time, GC, compiled-call, initialization and compilation time. Present includes actual blocking render/transport/FENCE work. These measurements do not isolate VM dispatch overhead from the foreign body.
6. Exercise requested-limit OOM, live-window injected OOM and real native malloc failure; each must have zero live ledger blocks and no native owner. Then run twenty fresh VMs in the same bounded arena. Check stack bottom canaries and the independent 8 KiB reserve.
7. Enter ROM BOOTSEL explicitly. Restore only the original affected flash prefix, read all 2 MiB and require exact backup equality/hash. Boot MicroPython, hash all flash again and confirm the healthy KAGURA console before reporting restoration. Retain raw failure logs if anything stops early. Physical BOOTSEL remains the fallback if the image crashes.

For the visible frame comparison, build the host `hdmi_reference` target and run it in an empty reference directory; `tools/compare_hdmi.py REFERENCE_DIR HARDWARE_RUN_DIR` reuses the unchanged native Desktop capture classifier. This target is host-only and does not alter the pinned firmware. Interface 1 was independently observed with Windows PnP **Code 28**, while Interface 0 continued to use Microsoft's normal USB mass-storage driver.

Host frame CRC goldens for the single-window workload: `be72ff88`, `c91b4078`, `7017406d`, `e89d5ada`, `f07a198f`, `abb5deb8`, `be72ff88`. No Japanese font rendering or expanded foreign API is part of the run.

## Results still pending

Wren boot, physical allocator/stack measurements, foreign latency, GC/OOM recovery, Wren HDMI screenshots and CRCs, reset behavior, programmed-flash readback and post-test restoration verification are **not measured yet**. A successful backup/control reset is not a successful post-flash restoration. PRs #68, #69 and #70 remain Draft and unmerged.
