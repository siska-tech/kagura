#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build-arm results
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$PATH"
arm-none-eabi-gcc --version | head -1 >results/arm-toolchain.txt
python3 tools/gen_font_c.py build-arm/font_data.c
D=../c-gem-desktop/src
flags=(-std=c11 -mcpu=cortex-m0plus -mthumb -Os -g -ffunction-sections -fdata-sections -fstack-usage -Wall -Wextra -Werror -Iinclude -I"$D")
arm-none-eabi-gcc "${flags[@]}" -c src/kj_text.c -o build-arm/kj_text.o
arm-none-eabi-gcc "${flags[@]}" -c build-arm/font_data.c -o build-arm/font_data.o
arm-none-eabi-gcc "${flags[@]}" -c src/kj_desktop.c -o build-arm/kj_desktop.o
for mode in core baseline japanese; do
  mkdir -p "build-arm/$mode"
  defs=(); objs=()
  if [ "$mode" = core ]; then
    objs=(build-arm/kj_text.o build-arm/font_data.o)
  else
    defs=(-DKJ_DESKTOP_PROBE=1)
    if [ "$mode" = japanese ]; then
      defs+=(-DKD_NATIVE_TEXT=1)
      objs=(build-arm/kj_text.o build-arm/font_data.o build-arm/kj_desktop.o)
    fi
    for name in kd_fb kd_region kd_tile4 kd_font kd_font_data kd_sprite kd_gfx kd_app kd_desktop; do
      arm-none-eabi-gcc "${flags[@]}" "${defs[@]}" -c "$D/$name.c" -o "build-arm/$mode/$name.o"
      objs+=("build-arm/$mode/$name.o")
    done
  fi
  arm-none-eabi-gcc "${flags[@]}" "${defs[@]}" -c tests/arm_probe.c -o "build-arm/$mode/probe.o"
  arm-none-eabi-gcc -mcpu=cortex-m0plus -mthumb -nostartfiles --specs=nosys.specs \
    -Wl,--gc-sections,--undefined=kj_type_sizes,-T,tools/analysis.ld,-Map,build-arm/$mode/link.map \
    "build-arm/$mode/probe.o" "${objs[@]}" -lc -lgcc -o "build-arm/$mode/analysis.elf"
  arm-none-eabi-size -A "build-arm/$mode/analysis.elf" >"results/arm-$mode-sections.txt"
  cp "build-arm/$mode/link.map" "results/arm-$mode-link.map"
done
arm-none-eabi-size -A build-arm/kj_text.o build-arm/font_data.o build-arm/kj_desktop.o >results/arm-objects.txt
arm-none-eabi-nm -u build-arm/kj_text.o >results/portable-core-symbols.txt
python3 tools/arm_report.py
