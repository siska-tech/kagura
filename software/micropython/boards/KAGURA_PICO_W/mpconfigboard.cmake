# SPDX-License-Identifier: Apache-2.0
include(${MICROPY_PORT_DIR}/boards/RPI_PICO_W/mpconfigboard.cmake)
set(MICROPY_BOARD_PINS ${MICROPY_PORT_DIR}/boards/RPI_PICO_W/pins.csv)
set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)
