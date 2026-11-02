cmake_minimum_required(VERSION 3.13)
set(PICO_BOARD pico)
set(PICO_PLATFORM rp2040)
set(PICO_DEFAULT_BINARY_TYPE default) # flash-resident ELF; NEVER use SRAM loader
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)
project(wren_desktop_flash C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()
include(../../cmake/modules.cmake)
target_compile_definitions(desktop_wren PRIVATE WD_MEMORY_DETAIL=1)
set(SDK_LINKER $ENV{PICO_SDK_PATH}/src/rp2_common/pico_crt0/rp2040/memmap_default.ld)
file(SHA256 ${SDK_LINKER} HASH)
if(NOT HASH STREQUAL "d409afb35ec0a8c3edf5ad6935907cb45f225a3cbdfd4c3b8505a7ed92df28dc")
  message(FATAL_ERROR "Use the pinned Pico SDK 2.2.0 flash linker script")
endif()
file(READ ${SDK_LINKER} LDS)
string(REPLACE "LENGTH = 256k" "LENGTH = 200k" LDS "${LDS}")
string(REPLACE "SCRATCH_X(rwx) : ORIGIN" "RECOVERY(rw) : ORIGIN = 0x20032000, LENGTH = 8k\n    CORE_STACK(rw) : ORIGIN = 0x20034000, LENGTH = 48k\n    SCRATCH_X(rwx) : ORIGIN" LDS "${LDS}")
string(REPLACE "__HeapLimit = ORIGIN(RAM) + LENGTH(RAM);" "__HeapLimit = __end__ + 135168;" LDS "${LDS}")
string(REPLACE "__StackLimit = ORIGIN(RAM) + LENGTH(RAM);" "__StackLimit = __HeapLimit;" LDS "${LDS}")
string(REPLACE "__StackTop = ORIGIN(SCRATCH_Y) + LENGTH(SCRATCH_Y);" "__StackTop = ORIGIN(CORE_STACK) + LENGTH(CORE_STACK);" LDS "${LDS}")
string(REPLACE "KEEP(*(.stack*))\n    } > SCRATCH_Y" "KEEP(*(.stack*))\n    } > CORE_STACK" LDS "${LDS}")
string(REPLACE "    .flash_end : {" "    .recovery_reserve (NOLOAD) : {\n        __recovery_start = .;\n        . += 8192;\n        __recovery_end = .;\n    } > RECOVERY\n\n    .flash_end : {" LDS "${LDS}")
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/integration_flash.ld "${LDS}\n"
  "ASSERT(__HeapLimit <= ORIGIN(RAM) + LENGTH(RAM), \"132 KiB arena does not fit\")\n"
  "ASSERT(SIZEOF(.stack_dummy) == 49152, \"48 KiB stack required\")\n"
  "ASSERT(__recovery_end <= __StackBottom, \"recovery overlaps stack\")\n"
  "ASSERT(SIZEOF(.stack1_dummy) == 0, \"core 1 must remain parked\")\n"
  "ASSERT(SIZEOF(.scratch_x) == 0 && SIZEOF(.scratch_y) == 0, \"scratch banks reserved\")\n")
add_executable(wren_desktop_flash ${KD_WD}/pico/main.c ${KD_REPO}/software/pico/kagura_host.c)
pico_generate_pio_header(wren_desktop_flash ${KD_REPO}/software/pico/kagura_host.pio)
target_link_libraries(wren_desktop_flash PRIVATE Kagura::WrenDesktop pico_stdlib hardware_pio hardware_clocks hardware_watchdog)
target_link_options(wren_desktop_flash PRIVATE "-Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/wren_desktop_flash.map,--cref")
target_compile_options(wren_desktop_flash PRIVATE -Os -Wall -Wextra -Werror -fstack-usage)
target_compile_definitions(wren_desktop_flash PRIVATE
  # Expected malloc/realloc failure must reach Wren's whole-VM discard path.
  # sbrk remains hard bounded by __StackLimit == __HeapLimit; successful Wren
  # allocations also get an explicit range check in the platform hook.
  PICO_MALLOC_PANIC=0
  PICO_STACK_SIZE=49152 PICO_USE_STACK_GUARDS=1
  PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS=0
  PICO_STDIO_USB_STDOUT_TIMEOUT_US=500000
  PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
  PICO_STDIO_USB_ENABLE_RESET_VIA_VENDOR_INTERFACE=0)
pico_set_linker_script(wren_desktop_flash ${CMAKE_CURRENT_BINARY_DIR}/integration_flash.ld)
pico_enable_stdio_usb(wren_desktop_flash 1)
pico_enable_stdio_uart(wren_desktop_flash 0)
# ELF/map only: no UF2 packaging, loader, flashing or hardware execution target.
