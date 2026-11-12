# SPDX-License-Identifier: Apache-2.0
set(PICO_BOARD "pico")
set(PICO_PLATFORM "rp2040")
set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)
include(${MICROPY_BOARD_DIR}/../../frozen_alignment.cmake)
# Native modules: audio (software/audio). A project with modules of its own
# (kagura-desktop) passes USER_C_MODULES and FROZEN_MANIFEST, which add the
# SDK's modules and manifest to its own.
if(NOT USER_C_MODULES)
    set(USER_C_MODULES ${MICROPY_BOARD_DIR}/../../../audio/binding/micropython.cmake)
endif()
