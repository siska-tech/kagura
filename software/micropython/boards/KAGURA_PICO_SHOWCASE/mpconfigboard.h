// SPDX-License-Identifier: Apache-2.0
// KAGURA_PICO plus the live showcase: the showcase modules are frozen and its
// assets live in a read-only ROMFS partition (mounted at /rom by
// kagura_showcase). Flash map (2 MB): firmware, ROMFS, filesystem.
#define MICROPY_HW_BOARD_NAME "KAGURA Raspberry Pi Pico (showcase)"
#define MICROPY_HW_FLASH_STORAGE_BYTES (512 * 1024)
#define MICROPY_HW_ROMFS_BYTES (576 * 1024)
#define MICROPY_PY_OS_DUPTERM (1)
#define MICROPY_PY_OS_DUPTERM_NOTIFY (1)
// kagura_audio keeps C state that points into the GC heap: drop it on soft reset.
void kagura_audio_soft_reset(void);
#define MICROPY_BOARD_START_SOFT_RESET() kagura_audio_soft_reset()
