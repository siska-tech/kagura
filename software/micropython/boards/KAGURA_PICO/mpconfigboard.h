// SPDX-License-Identifier: Apache-2.0
// RP2040 Pico, with Python-stream REPL support. USB CDC stays enabled.
#define MICROPY_HW_BOARD_NAME "KAGURA Raspberry Pi Pico"
#define MICROPY_HW_FLASH_STORAGE_BYTES (1408 * 1024)
#define MICROPY_PY_OS_DUPTERM (1)
#define MICROPY_PY_OS_DUPTERM_NOTIFY (1)
// kagura_audio keeps C state that points into the GC heap: drop it on soft reset.
void kagura_audio_soft_reset(void);
#define MICROPY_BOARD_START_SOFT_RESET() kagura_audio_soft_reset()
