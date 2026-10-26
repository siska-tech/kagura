# Third-party audio

`piano_c4_sample.h` contains a 1.5-second, 48 kHz, signed 8-bit conversion of
`INSPiano_Vel03_C4_01.ogg` from Meta Open Sound's Meta Piano collection.

- Upstream: https://github.com/facebookincubator/Meta-open-sound
- Source path: `systems/instruments/meta-piano/ogg/INSPiano_Vel03_C4_01.ogg`
- Source SHA-256: `f6df379bfb60e074fdb640eb33298a3150960b9c27fa9247740036fb8d9b55d6`
- License: CC0 1.0 Universal

The conversion keeps the source's 48 kHz mono rate, normalizes the signed
8-bit peak to 92, and applies a 100 ms fade-out at the end of the excerpt.
