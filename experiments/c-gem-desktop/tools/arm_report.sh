#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Embedded-side measurements without hardware (see BENCHMARKS.md):
#   1. code/data size of the core and the demo apps for Cortex-M0+ (RP2040)
#      and Cortex-M33 (RP2350), from arm-none-eabi-size on the objects;
#   2. per-function stack frames (-fstack-usage), largest first;
#   3. executed Thumb-1 instructions per benchmark operation (op + render +
#      export, bracketed by marker calls), counted by running
#      bench/arm_count.c under qemu-arm user mode one instruction per
#      translation block.
# Requires the Arm GNU toolchain (as for software/starfall) and qemu-arm
# (QEMU env var, default: qemu-arm on PATH). Run from the repository root:
#   bash experiments/c-gem-desktop/tools/arm_report.sh [OUT_DIR]
set -euo pipefail
EXP="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-build/c-gem-arm}"
export PATH="$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin:$PATH"
QEMU="${QEMU:-qemu-arm}"
CC=arm-none-eabi-gcc
mkdir -p "$OUT"
CORE="kd_fb kd_region kd_tile4 kd_font kd_font_data kd_sprite kd_gfx kd_app kd_desktop"
APPS="shell filemgr studio"
COMMON="-std=c11 -Wall -Wextra -Werror -ffunction-sections -fdata-sections -I$EXP/../../software/desktop/core -I$EXP/apps"

size_table() {   # cpu opt
    local dir="$OUT/$1$2"
    mkdir -p "$dir"
    for f in $CORE; do $CC -mcpu=$1 -mthumb $2 $COMMON -fstack-usage -c "$EXP/../../software/desktop/core/$f.c" -o "$dir/$f.o"; done
    for f in $APPS; do $CC -mcpu=$1 -mthumb $2 $COMMON -fstack-usage -c "$EXP/apps/$f.c" -o "$dir/$f.o"; done
    echo "### $1 $2"
    echo
    echo '| objects | text | data | bss |'
    echo '|---|---:|---:|---:|'
    for group in "core:$CORE" "font data:kd_font_data" "core without fonts:${CORE/kd_font_data/}" "demo apps:$APPS"; do
        local name="${group%%:*}" files="${group#*:}" objs=""
        for f in $files; do objs="$objs $dir/$f.o"; done
        arm-none-eabi-size -t $objs | tail -1 | awk -v n="$name" '{printf "| %s | %d | %d | %d |\n", n, $1, $2, $3}'
    done
    echo
}

{
    echo "# Embedded build report ($(date -u +%Y-%m-%dT%H:%MZ))"
    echo
    echo "$($CC --version | head -1)"
    echo
    size_table cortex-m0plus -O2
    size_table cortex-m0plus -Os
    size_table cortex-m33 -O2
    echo "### Largest stack frames (cortex-m0plus -O2, bytes)"
    echo
    echo '| function | frame | kind |'
    echo '|---|---:|---|'
    cat "$OUT"/cortex-m0plus-O2/*.su | sort -t$'\t' -k2 -n -r | head -12 |
        awk -F'\t' '{split($1, a, ":"); printf "| %s | %s | %s |\n", a[length(a)], $2, $3}'
    echo
} > "$OUT/report.md"

# Instruction counts.
$CC -mcpu=cortex-m0plus -mthumb -O2 $COMMON -I"$EXP/bench" -nostartfiles -static --specs=nano.specs \
    "$EXP"/bench/arm_count.c $(for f in $CORE; do echo "$EXP/../../software/desktop/core/$f.c"; done) \
    $(for f in $APPS; do echo "$EXP/apps/$f.c"; done) -lc -lgcc -o "$OUT/kd_count.elf"
count() {   # workload n -> instructions between kd_mark_begin and kd_mark_end, per sample
    "$QEMU" -one-insn-per-tb -d nochain,exec -D /dev/stdout "$OUT/kd_count.elf" "$1" "$2" |
        awk -v n="$2" '/^Trace/ { f = $NF; if (f == "kd_mark_begin") on = 1; else if (f == "kd_mark_end") on = 0; else if (on) c++ }
                       END { printf "%d", c / n }'
}
{
    echo "### Executed Thumb-1 instructions per operation (op + render + TILE4 export)"
    echo
    echo 'Counted between kd_mark_begin/kd_mark_end, mean of 4 samples after 4 warm-up (bench/arm_count.c).'
    echo
    echo '| workload | instructions/op |'
    echo '|---|---:|'
    for w in idle full_redraw full_redraw_painter full_export button_press menu_open menu_close window_activate \
             window_move_live window_move_outline window_drop_outline label_one_char sprite_pixel sprite_import \
             recompose_overlap recompose_overlap_painter pointer_move; do
        echo "| $w | $(count "$w" 4) |"
    done
    echo
} >> "$OUT/report.md"
cat "$OUT/report.md"
