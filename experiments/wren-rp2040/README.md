# Wren / RP2040 feasibility experiment (KAGURA-9)

**Decision: keep MicroPython as the baseline. Wren merits further investigation,
but this experiment does not establish reliable RP2040 hardware operation or a
memory advantage over MicroPython.** The official VM works on the PC and in
ARM allocation-only emulation. The SRAM-only image builds and passes offline
validation, but its remaining allocator space cannot accommodate the full suite.
No physical Pico was accessed or executed by this experiment.

All changes are confined to this directory. No desktop bindings, IME, GUI,
filesystem, MicroPython, SDK, RTL, ABI, firmware, or FPGA changes are included.

## Reproduce

Linux/WSL, C11 compiler, CMake and Python 3 (Python scripts have no dependencies):

```sh
cd experiments/wren-rp2040
python3 tools/acquire.py
cmake -S . -B build-host -DCMAKE_BUILD_TYPE=Release
cmake --build build-host -j4
ctest --test-dir build-host --output-on-failure
python3 tools/benchmark.py build-host/wren_host

cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_C_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer'
cmake --build build-asan -j4
ctest --test-dir build-asan --output-on-failure
```

`build-host/wren_host [requested-byte-budget] [lifecycle-count] [checks]`
prints output and machine-readable `RESULT key=value` lines. Exit 0 = all pass,
1 = one or more VMs discarded for OOM, 2 = correctness failure. A budget is a
cap on live bytes requested by Wren; it is **not** a reserved memory arena.

Source acquisition: official https://github.com/wren-lang/wren, exact commit
`99d2f0b8fc2686134b32b18166e037639f7e9f2c`, MIT; license copied verbatim in
[WREN-LICENSE](WREN-LICENSE). All source files and the license have committed
SHA-256 hashes in `upstream.sha256`; configure verifies them. No upstream source
patches are applied. Optional `meta` and `random` modules are disabled. The
upstream checkout is ignored; the acquisition script recreates it. Generated
`src/workloads.h` comes from `workloads/*.wren` using `tools/gen_workloads.py`.

The initial 0.4.0 release candidate (`4a18fc489f9ea3d253b20dd40f4cdad0d6bb40eb`)
was rejected: low GC thresholds expose an upstream compiler attribute-root
use-after-free. See `results/rejected-wren040-asan.txt`. The selected revision
contains upstream fix `f09ebf6a`; final correctness and ASan/UBSan runs pass.

## Contents and results

- `src/experiment.c`: minimal host, bidirectional calls, tracked allocator,
  whole-VM OOM discard, ordinary compile/runtime errors and recovery.
- `workloads/`: ten deterministic workloads; expected values are independently
  specified in `tools/gen_workloads.py`.
- `tools/test_host.py`: output bytes, numerical checks, handle reuse, foreign
  call counts, 200 successful VM lifecycles, repeated scripts/GC, forced OOM
  during initialization and during later allocations, zero outstanding blocks.
- [REPORT.md](REPORT.md): measured results, limits and MicroPython comparison.
- [pico/ACCEPTANCE.md](pico/ACCEPTANCE.md): build, SRAM map, stack analysis,
  acceptance gates and recovery. Hardware execution requires separate approval.
- `results/`: raw host budget sweeps, timing table, minimums, allocation-only
  ARM emulation, offline ELF/UF2 verification and existing Stage 3A references.

The Pico build is a **candidate for memory feasibility testing**, not a claim
that the suite fits SRAM or that hardware acceptance passed. Read the acceptance
plan before requesting a hardware run. The legacy C Desktop loader is not
compatible with this program's protocol and must not be used unmodified.
