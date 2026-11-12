# SPDX-License-Identifier: Apache-2.0
# Standalone C on KAGURA-9 from SRAM (Pico SDK 2.2.0, no_flash): the audio HAL
# and the KSNG player over the C host driver, playing the tracker's demo song.
# Build (WSL):
#   cmake -S software/audio/pico -B build/audio-pico -DPICO_SDK_PATH=$HOME/opt/pico-sdk
#   cmake --build build/audio-pico
# Run (flash untouched; the watchdog returns the board to MicroPython):
#   python tools/rp2040_sram_bench.py run --approved \
#       --uf2 build/audio-pico/ka_rp2040_audio.uf2 --elf build/audio-pico/ka_rp2040_audio.elf --log LOG
cmake_minimum_required(VERSION 3.13)
set(PICO_BOARD pico)
set(PICO_DEFAULT_BINARY_TYPE no_flash)
include(${CMAKE_CURRENT_LIST_DIR}/../../pico/pico_sdk_import.cmake)
project(ka_rp2040_audio C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

set(KA ${CMAKE_CURRENT_LIST_DIR}/..)
set(KH ${KA}/../pico)
add_executable(ka_rp2040_audio main.c ${KA}/backend/ka_kagura_host.c ${KA}/hal/ka_audio.c
    ${KA}/seq/ks_song.c ${KA}/seq/ks_player.c ${KH}/kagura_host.c)
pico_generate_pio_header(ka_rp2040_audio ${KH}/kagura_host.pio)
target_include_directories(ka_rp2040_audio PRIVATE ${KA}/hal ${KA}/seq ${KA}/backend ${KA}/songs ${KH}
    ${KA}/../include)
target_compile_options(ka_rp2040_audio PRIVATE -Wall -Wextra -Werror -O2 -fstack-usage)
target_compile_definitions(ka_rp2040_audio PRIVATE
    PICO_STACK_SIZE=0x1000
    PICO_USE_STACK_GUARDS=1
    PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS=0
    PICO_STDIO_USB_STDOUT_TIMEOUT_US=500000
    PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
    PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(ka_rp2040_audio PRIVATE pico_stdlib hardware_pio hardware_clocks hardware_watchdog)
pico_enable_stdio_usb(ka_rp2040_audio 1)
pico_enable_stdio_uart(ka_rp2040_audio 0)
pico_add_extra_outputs(ka_rp2040_audio)
