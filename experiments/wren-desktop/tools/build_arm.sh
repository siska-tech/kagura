#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build-arm
W=../wren-rp2040/vendor/wren
D=../c-gem-desktop/src
arm-none-eabi-gcc -std=gnu11 -mcpu=cortex-m0plus -mthumb -Os -nostartfiles -static \
  -ffunction-sections -fdata-sections -fstack-usage -Wl,--gc-sections \
  -DWREN_OPT_META=0 -DWREN_OPT_RANDOM=0 -DWD_MEMORY_DETAIL=1 -DWD_ARM_TESTS=1 -Dmain=integration_test_main \
  -I$W/src/include -I$W/src/vm -I$D -Isrc -Itests -I../../software/pico -I../../software/include \
  tests/arm_host.c tests/mock_hal.c tests/main.c src/ui.c src/transport.c src/runtime.c \
  $D/kd_fb.c $D/kd_region.c $D/kd_tile4.c $D/kd_font.c $D/kd_font_data.c \
  $D/kd_sprite.c $D/kd_gfx.c $D/kd_app.c $D/kd_desktop.c $W/src/vm/*.c \
  -lm -lc -lgcc -o build-arm/integration_memory.elf
