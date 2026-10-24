# SPDX-License-Identifier: Apache-2.0
# KAGURA host firmware for Raspberry Pi Pico / Pico W (Pico SDK 2.2.0).
cmake_minimum_required(VERSION 3.13)
if(NOT DEFINED PICO_BOARD)
    set(PICO_BOARD pico)
endif()
include(pico_sdk_import.cmake)
project(kagura_pico_host C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

add_executable(kagura_host main.c kagura_host.c spectacular_demo.c)
pico_generate_pio_header(kagura_host ${CMAKE_CURRENT_LIST_DIR}/kagura_host.pio)
target_include_directories(kagura_host PRIVATE ${CMAKE_CURRENT_LIST_DIR} ${CMAKE_CURRENT_LIST_DIR}/../include)
target_compile_options(kagura_host PRIVATE -Wall -Wextra -Werror)
target_link_libraries(kagura_host PRIVATE pico_stdlib hardware_pio hardware_clocks)
pico_enable_stdio_usb(kagura_host 1)
pico_enable_stdio_uart(kagura_host 0)
pico_add_extra_outputs(kagura_host)
