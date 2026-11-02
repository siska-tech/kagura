# Existing Stage 3A references (read-only inspection)

Captured 2026-11-02 from the pre-existing local experiment/c-gem-micropython
worktree, commit `9552c975f143ce6b777043554776aa46b9ca701e` with uncommitted changes.
These are provisional comparison inputs, not reproducible results of this branch.

| Input | SHA-256 |
|---|---|
| build/c-gem-mp/bench-binding.md | b5a204e46acaab8c8631839982ce45e3a13b2fe145ae68bcbfe1762021979cfc |
| build/c-gem-mp/bench-native.md | 1c21794b3988fe164ea7dfe08e88c62a5fcbf49959972987b4ca6f83be160b9e |
| build/micropython-src/ports/rp2/build-KAGURA_PICO-stage3a-kd/firmware.elf | 1fc0bbccd3584b505d3539a770c2711375518e45dad71abb39dc9c206427075e |

The two markdown inputs are copied here as reference-stage3a-host-*.md.
They are MicroPython 1.26.0 Unix-host measurements; no device was accessed.
The RP2 ELF is not copied or loaded, only analyzed with Arm GNU 14.2.Rel1:

```
arm-none-eabi-size: text=463560 data=0 bss=51088
__bss_start__   0x20001318
__bss_end__     0x2000daa8
__GcHeapStart  0x2000daa8
__GcHeapEnd    0x20040000
__StackBottom  0x20040000
__StackTop     0x20042000
```

GC capacity is 206,168 B, a linker allowance, not measured use or minimum heap.
The RP2 ELF text includes some RAM-resident functions; BSS omits those. Neither
the host native state nor this firmware footprint is a Wren integration result.
