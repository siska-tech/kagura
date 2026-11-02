# First capture attempt: HDMI acceptance failed

The firmware runtime/CRC/GC/OOM and restoration checks passed, but the first
0.33-second receiver captures were black / UGREEN no-signal images. These are
not accepted as Japanese HDMI rendering evidence. They are preserved.

Restored MicroPython video was visible. The exact same target ELF was rerun
with a 3-second capture settle and an explicit signal-presence check. That
run produced the Japanese title and normal per-event images. No firmware,
FPGA bitstream, colour tolerance, allocator or stack protection was changed.
See the separate validated run for the unchanged full colour comparison.
