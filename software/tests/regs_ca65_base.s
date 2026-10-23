; SPDX-License-Identifier: Apache-2.0
KAGURA_IO_BASE = $D000
.include "kagura_regs.inc"
.assert KAGURA_IO_COMMAND = $D00E, error, "relocated COMMAND address"
