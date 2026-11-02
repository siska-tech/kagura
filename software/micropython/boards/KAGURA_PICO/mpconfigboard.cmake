# SPDX-License-Identifier: Apache-2.0
set(PICO_BOARD "pico")
set(PICO_PLATFORM "rp2040")
set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)
include(${MICROPY_BOARD_DIR}/../../frozen_alignment.cmake)
# Native desktop library and its MicroPython module (software/desktop).
if(NOT USER_C_MODULES)
    set(USER_C_MODULES ${MICROPY_BOARD_DIR}/../../../desktop/binding/micropython.cmake)
endif()
