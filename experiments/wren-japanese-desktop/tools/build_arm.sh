#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build-arm
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$PATH"
python3 tools/gen_app.py
python3 ../native-text/tools/gen_font_c.py build-arm/font_data.c
W=../wren-rp2040/vendor/wren
D=../c-gem-desktop/src
arm-none-eabi-gcc -std=gnu11 -mcpu=cortex-m0plus -mthumb -Os -nostartfiles -static \
  -ffunction-sections -fdata-sections -fstack-usage -Wl,--gc-sections \
  -DWREN_OPT_META=0 -DWREN_OPT_RANDOM=0 -DWD_MEMORY_DETAIL=1 -DWD_ARM_TESTS=1 -Dmain=integration_test_main \
  -DWD_JAPANESE=1 -DKD_NATIVE_TEXT=1 \
  -I$W/src/include -I$W/src/vm -I$D -Isrc -I../native-text/include -I../wren-desktop/src -I../wren-desktop/tests -I../../software/pico -I../../software/include \
  ../wren-desktop/tests/arm_host.c ../wren-desktop/tests/mock_hal.c tests/main.c \
  ../wren-desktop/src/ui.c ../wren-desktop/src/transport.c ../wren-desktop/src/runtime.c ../wren-desktop/src/diagnostics.c \
  src/wj_title.c ../native-text/src/kj_text.c ../native-text/src/kj_desktop.c build-arm/font_data.c \
  $D/kd_fb.c $D/kd_region.c $D/kd_tile4.c $D/kd_font.c $D/kd_font_data.c \
  $D/kd_sprite.c $D/kd_gfx.c $D/kd_app.c $D/kd_desktop.c $W/src/vm/*.c \
  -lm -lc -lgcc -o build-arm/integration_memory.elf
