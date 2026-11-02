cmake_minimum_required(VERSION 3.13)
set(PICO_BOARD pico)
set(PICO_PLATFORM rp2040)
set(PICO_DEFAULT_BINARY_TYPE no_flash)
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)
project(wren_rp2040 C CXX ASM)
set(CMAKE_C_STANDARD 11)
option(WREN_LTO "Evaluate Wren-only cross-unit optimization without changing VM/tests" OFF)
pico_sdk_init()
# Fixed-suite ARM stack painting exceeds the old 32 KiB reservation.
# Keep 48 KiB, including margin for the SDK/USB IRQ path (hardware unmeasured).
set(WREN_STACK_KIB 48 CACHE STRING "Native compiler stack reservation, KiB")
if(WREN_STACK_KIB LESS 48)
  message(FATAL_ERROR "Memory audit requires at least 48 KiB native stack")
endif()
option(WREN_USE_ALL_SRAM "Evaluate extending core 0 stack through both unused scratch banks" OFF)
if(WREN_USE_ALL_SRAM)
  set(WREN_STACK_TOP 0x20042000)
else()
  set(WREN_STACK_TOP 0x20040000)
endif()
math(EXPR WREN_STACK_BYTES "${WREN_STACK_KIB} * 1024")
math(EXPR WREN_STACK_BASE "${WREN_STACK_TOP} - ${WREN_STACK_BYTES}" OUTPUT_FORMAT HEXADECIMAL)
math(EXPR WREN_RAM_KIB "(${WREN_STACK_BASE} - 0x20000000) / 1024")
set(SDK_LINKER $ENV{PICO_SDK_PATH}/src/rp2_common/pico_crt0/rp2040/memmap_no_flash.ld)
file(SHA256 ${SDK_LINKER} SDK_LINKER_HASH)
if(NOT SDK_LINKER_HASH STREQUAL "41f543e2550c6fa53d7dd1ff4e937a8278fa50efc562f9e93392315beedb0adc")
  message(FATAL_ERROR "Unexpected SDK no_flash linker script; use pinned Pico SDK 2.2.0")
endif()
file(READ ${SDK_LINKER} LINKER_TEXT)
string(REPLACE "LENGTH = 256k" "LENGTH = ${WREN_RAM_KIB}k" LINKER_TEXT "${LINKER_TEXT}")
string(REPLACE "SCRATCH_Y(rwx) : ORIGIN = 0x20041000, LENGTH = 4k" "SCRATCH_Y(rwx) : ORIGIN = ${WREN_STACK_BASE}, LENGTH = ${WREN_STACK_KIB}k" LINKER_TEXT "${LINKER_TEXT}")
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/wren_no_flash.ld "${LINKER_TEXT}")
file(APPEND ${CMAKE_CURRENT_BINARY_DIR}/wren_no_flash.ld
  "\nASSERT(SIZEOF(.scratch_x) == 0, \"scratch X must be unused\")\n"
  "ASSERT(SIZEOF(.scratch_y) == 0, \"scratch Y data must be unused\")\n"
  "ASSERT(SIZEOF(.stack1_dummy) == 0, \"core 1 stack must be unused\")\n")
include(../wren.cmake)
if(WREN_LTO)
  # Optimize only Wren across translation units. Leave Pico's linker-wrap
  # stdio/malloc definitions outside LTO so wrapping is not internalized.
  set_property(TARGET wren_vm PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
endif()
add_executable(wren_rp2040 main.c ../src/experiment.c)
target_include_directories(wren_rp2040 PRIVATE ../src)
target_compile_options(wren_rp2040 PRIVATE -Os -Wall -Wextra -Werror -fstack-usage)
target_compile_definitions(wren_rp2040 PRIVATE
  PICO_STACK_SIZE=${WREN_STACK_BYTES} PICO_USE_STACK_GUARDS=1
  PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS=0
  PICO_STDIO_USB_STDOUT_TIMEOUT_US=500000
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
target_link_libraries(wren_rp2040 PRIVATE wren_vm pico_stdlib hardware_clocks hardware_watchdog m)
pico_set_linker_script(wren_rp2040 ${CMAKE_CURRENT_BINARY_DIR}/wren_no_flash.ld)
pico_enable_stdio_usb(wren_rp2040 1)
pico_enable_stdio_uart(wren_rp2040 0)
pico_add_extra_outputs(wren_rp2040)
