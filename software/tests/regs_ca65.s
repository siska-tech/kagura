; SPDX-License-Identifier: Apache-2.0
; Assemble check for the generated ca65 include, default and relocated base.
.include "kagura_regs.inc"
.assert KAGURA_IO_COMMAND = $9F0E, error, "default COMMAND address"
.assert KAGURA_STATUS_INIT_DONE = $01, error, "STATUS INIT_DONE"
.assert KAGURA_AUDIO_INDEX(4, KAGURA_AUDIO_LEN_LOG2) = $47, error, "wave ch4 LEN_LOG2"
.assert KAGURA_VRAM_WAVE_BASE = $9800, error, "wave shadow"
.segment "CODE"
        lda KAGURA_IO_STATUS
        and #KAGURA_STATUS_INIT_DONE
        lda #KAGURA_CMD_COMMIT
        sta KAGURA_IO_COMMAND
