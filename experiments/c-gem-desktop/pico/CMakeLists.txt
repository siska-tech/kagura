# SPDX-License-Identifier: Apache-2.0
# SRAM-only RP2040 benchmark of the C desktop core (Pico SDK 2.2.0, no_flash).
# Two variants of the same program:
#   kd_rp2040_bench        SDK defaults: ROM memcpy/memset, hardware divider
#   kd_rp2040_bench_plain  compiler memcpy and division, as counted under qemu
# Build (WSL): see experiments/c-gem-desktop/pico/README.md.
cmake_minimum_required(VERSION 3.13)
set(PICO_BOARD pico)
set(PICO_DEFAULT_BINARY_TYPE no_flash)
include(${CMAKE_CURRENT_LIST_DIR}/../../../software/pico/pico_sdk_import.cmake)
project(kd_rp2040_bench C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

set(KD ${CMAKE_CURRENT_LIST_DIR}/..)
set(KD_SOURCES
    ${KD}/src/kd_fb.c ${KD}/src/kd_region.c ${KD}/src/kd_tile4.c ${KD}/src/kd_font.c
    ${KD}/src/kd_font_data.c ${KD}/src/kd_sprite.c ${KD}/src/kd_gfx.c ${KD}/src/kd_app.c
    ${KD}/src/kd_desktop.c ${KD}/apps/shell.c ${KD}/apps/filemgr.c ${KD}/apps/studio.c)

function(kd_rp2040 target variant)
    add_executable(${target} main.c ${KD_SOURCES})
    target_include_directories(${target} PRIVATE ${KD}/src ${KD}/apps ${KD}/bench)
    # -O2 as in the qemu instruction counts (tools/arm_report.sh).
    target_compile_options(${target} PRIVATE -Wall -Wextra -Werror -O2 -fstack-usage)
    target_compile_definitions(${target} PRIVATE
        KD_RP_VARIANT="${variant}"
        PICO_STACK_SIZE=0x1000          # all of SCRATCH_Y; peak use is measured
        PICO_USE_STACK_GUARDS=1         # MPU no-access region at the stack bottom
        PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS=0
        PICO_STDIO_USB_STDOUT_TIMEOUT_US=500000
        # No reboot-to-BOOTSEL paths (1200 baud, vendor reset interface).
        PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
        PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
    target_link_libraries(${target} PRIVATE pico_stdlib hardware_clocks hardware_watchdog hardware_sync)
    pico_enable_stdio_usb(${target} 1)
    pico_enable_stdio_uart(${target} 0)
    pico_add_extra_outputs(${target})
endfunction()

kd_rp2040(kd_rp2040_bench sdk)
kd_rp2040(kd_rp2040_bench_plain plain)
pico_set_mem_ops_implementation(kd_rp2040_bench_plain compiler)
pico_set_divider_implementation(kd_rp2040_bench_plain compiler)
