# SPDX-License-Identifier: Apache-2.0
include(${MICROPY_PORT_DIR}/boards/RPI_PICO_W/mpconfigboard.cmake)
set(MICROPY_BOARD_PINS ${MICROPY_PORT_DIR}/boards/RPI_PICO_W/pins.csv)
set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)
include(${MICROPY_BOARD_DIR}/../../frozen_alignment.cmake)
# Native modules: the desktop (software/desktop) and audio (software/audio).
if(NOT USER_C_MODULES)
    set(USER_C_MODULES ${MICROPY_BOARD_DIR}/../../../desktop/binding/micropython.cmake
        ${MICROPY_BOARD_DIR}/../../../audio/binding/micropython.cmake)
endif()
