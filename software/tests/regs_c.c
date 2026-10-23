/* SPDX-License-Identifier: Apache-2.0 */
/* Compile check for the generated C header; values are hand-written from
   docs/register-map.md, docs/audio-spec.md and docs/memory-map.md. */
#include "kagura_regs.h"

_Static_assert(KAGURA_REG_COMMAND == 0x0Eu, "COMMAND offset");
_Static_assert(KAGURA_REG_CAPS == 0x1Cu, "CAPS offset");
_Static_assert(KAGURA_STATUS_INIT_DONE == 0x01u && KAGURA_STATUS_ENGINE_BUSY == 0x80u, "STATUS bits");
_Static_assert(KAGURA_IRQ_STATUS_ERROR == 0x40u, "IRQ ERROR bit");
_Static_assert(KAGURA_ERROR_CODE_BUSY_CONFLICT == 0x80u, "ERROR_CODE bit 7");
_Static_assert(KAGURA_FIFO_STATUS_FREE_MASK == 0x3Fu && KAGURA_FIFO_STATUS_FULL == 0x80u, "FIFO_STATUS");
_Static_assert(KAGURA_CAPS_VALUE_FULL == 0x13u && KAGURA_CAPS_VALUE_WIDE == 0x33u, "CAPS values");
_Static_assert(KAGURA_CMD_AUDIO_COMMIT == 0x04u, "AUDIO_COMMIT");
_Static_assert(KAGURA_EXT_SCREEN_HEIGHT == 0x0Au && KAGURA_EXT_SCREEN_HEIGHT_WIDE == 180u, "SCREEN_HEIGHT");
_Static_assert(KAGURA_AUDIO_INDEX(4, KAGURA_AUDIO_LEN_LOG2) == 0x47u, "wave ch4 LEN_LOG2");
_Static_assert(KAGURA_AUDIO_MASTER_GAIN == 0xE0u && KAGURA_AUDIO_MASTER_GAIN_RESET == 32u, "MASTER_GAIN");
_Static_assert(KAGURA_VRAM_WAVE_BASE == 0x9800u && KAGURA_VRAM_WAVE_SIZE == 0x200u, "wave shadow");

int main(void) { return 0; }
