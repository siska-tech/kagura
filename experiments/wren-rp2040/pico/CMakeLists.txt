cmake_minimum_required(VERSION 3.13)
set(PICO_BOARD pico)
set(PICO_PLATFORM rp2040)
set(PICO_DEFAULT_BINARY_TYPE no_flash)
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)
project(wren_rp2040 C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()
# Reserve 32 KiB of main RAM for core 0's compiler stack. The default
# SCRATCH_Y stack is only 4 KiB. Keep the official no_flash script otherwise.
set(SDK_LINKER $ENV{PICO_SDK_PATH}/src/rp2_common/pico_crt0/rp2040/memmap_no_flash.ld)
file(SHA256 ${SDK_LINKER} SDK_LINKER_HASH)
if(NOT SDK_LINKER_HASH STREQUAL "41f543e2550c6fa53d7dd1ff4e937a8278fa50efc562f9e93392315beedb0adc")
  message(FATAL_ERROR "Unexpected SDK no_flash linker script; use pinned Pico SDK 2.2.0")
endif()
file(READ ${SDK_LINKER} LINKER_TEXT)
string(REPLACE "LENGTH = 256k" "LENGTH = 224k" LINKER_TEXT "${LINKER_TEXT}")
string(REPLACE "SCRATCH_Y(rwx) : ORIGIN = 0x20041000, LENGTH = 4k" "SCRATCH_Y(rwx) : ORIGIN = 0x20038000, LENGTH = 32k" LINKER_TEXT "${LINKER_TEXT}")
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/wren_no_flash.ld "${LINKER_TEXT}")
include(../wren.cmake)
add_executable(wren_rp2040 main.c ../src/experiment.c)
target_include_directories(wren_rp2040 PRIVATE ../src)
target_compile_options(wren_rp2040 PRIVATE -Os -Wall -Wextra -Werror -fstack-usage)
target_compile_definitions(wren_rp2040 PRIVATE
  PICO_STACK_SIZE=0x8000 PICO_USE_STACK_GUARDS=1
  PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS=0
  PICO_STDIO_USB_STDOUT_TIMEOUT_US=500000
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(wren_rp2040 PRIVATE wren_vm pico_stdlib hardware_clocks hardware_watchdog m)
pico_set_linker_script(wren_rp2040 ${CMAKE_CURRENT_BINARY_DIR}/wren_no_flash.ld)
pico_enable_stdio_usb(wren_rp2040 1)
pico_enable_stdio_uart(wren_rp2040 0)
pico_add_extra_outputs(wren_rp2040)
