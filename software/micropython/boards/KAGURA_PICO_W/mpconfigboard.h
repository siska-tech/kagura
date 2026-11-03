// SPDX-License-Identifier: Apache-2.0
#include "boards/RPI_PICO_W/mpconfigboard.h"
#define MICROPY_PY_OS_DUPTERM (1)
#define MICROPY_PY_OS_DUPTERM_NOTIFY (1)
// kagura_audio keeps C state that points into the GC heap: drop it on soft reset.
void kagura_audio_soft_reset(void);
#define MICROPY_BOARD_START_SOFT_RESET() kagura_audio_soft_reset()
