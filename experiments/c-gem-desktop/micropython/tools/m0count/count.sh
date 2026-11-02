#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Cortex-M0+ (RP2040 ISA) instruction counts of the stage 3A workloads, with
# and without MicroPython in the loop, by the method of tools/arm_report.sh:
# freestanding Thumb-1 ELFs run under qemu-arm user mode, one instruction per
# translation block, counting executed instructions between kd_mark_begin
# and kd_mark_end.
#
#   mp_count   MicroPython v1.26.0 embed port configured like rp2 (see
#              mpconfigport.h) + kagura_desktop + bench/workloads.py
#   kdm_count  the same workloads in C through kdm (bench/bench_native.c)
#
# Compiled as the rp2 port compiles firmware (MinSizeRel: -Os; py/vm.c,
# py/map.c and py/mpz.c at -O2). Needs the Arm GNU toolchain, qemu-arm
# (QEMU env var), python3, and build/micropython-src (v1.26.0). From the
# repository root:
#   bash experiments/c-gem-desktop/micropython/tools/m0count/count.sh [OUT_DIR] [N]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"
EXP="$ROOT/experiments/c-gem-desktop/micropython"
MPY="${MPY_DIR:-$ROOT/build/micropython-src}"
OUT="$(mkdir -p "${1:-$ROOT/build/c-gem-m0count}" && cd "${1:-$ROOT/build/c-gem-m0count}" && pwd)"
N="${2:-4}"
export PATH="${ARM_GCC_BIN:-$HOME/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin}:$PATH"
QEMU="${QEMU:-qemu-arm}"
CORE="kd_fb kd_region kd_tile4 kd_font kd_font_data kd_sprite kd_gfx kd_app kd_desktop"

# 1. MicroPython embed package (host-generated qstrs and module table include
#    kagura_desktop and kdmark).
cp "$EXP/tools/m0count/mpconfigport.h" "$OUT/"
make -C "$OUT" -f "$MPY/ports/embed/embed.mk" MICROPYTHON_TOP="$MPY" \
    USER_C_MODULES="$EXP/tools/m0count/modules" PACKAGE_DIR="$OUT/micropython_embed" >&2
python3 -I - "$EXP/bench/workloads.py" "$EXP/tools/m0count/driver.py" > "$OUT/workloads_py.h" <<'PY'
import sys
src = ''.join(open(p).read() for p in sys.argv[1:])
print('static const char kd_workloads_py[] =')
for line in src.splitlines(True):
    print('    "%s"' % line.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n'))
print('    ;')
PY

# 2. Thumb-1 objects.
CFLAGS=(-mcpu=cortex-m0plus -mthumb -ffunction-sections -fdata-sections -std=gnu99 -Wall -Werror
        -Wno-unused-but-set-variable -I"$OUT" -I"$OUT/micropython_embed" -I"$EXP/kagura_desktop"
        -I"$EXP/../src")
mkdir -p "$OUT/obj"
compile() {   # source -> object, -O2 for the files rp2 builds at -O2
    local src="$1" opt=-Os
    case "$src" in */py/vm.c|*/py/map.c|*/py/mpz.c) opt=-O2 ;; esac
    local obj="$OUT/obj/$(echo "${src#"$ROOT"/}" | tr / _).o"
    arm-none-eabi-gcc "${CFLAGS[@]}" $opt -c "$src" -o "$obj"
    echo "$obj"
}
CORE_OBJ=()
for f in $CORE; do o="$(compile "$EXP/../src/$f.c")"; CORE_OBJ+=("$o"); done
KDM_OBJ="$(compile "$EXP/kagura_desktop/kdm.c")"
MP_OBJ=()
for f in "$OUT"/micropython_embed/py/*.c "$OUT/micropython_embed/port/embed_util.c" \
         "$OUT/micropython_embed/shared/runtime/gchelper_generic.c" \
         "$EXP/kagura_desktop/modkagura_desktop.c" "$EXP/tools/m0count/modules/kdmark/modkdmark.c" \
         "$EXP/tools/m0count/main.c"; do
    o="$(compile "$f")"
    MP_OBJ+=("$o")
done
LDFLAGS=(-mcpu=cortex-m0plus -mthumb -nostartfiles -static --specs=nano.specs -Wl,--gc-sections)
arm-none-eabi-gcc "${LDFLAGS[@]}" "${MP_OBJ[@]}" "$KDM_OBJ" "${CORE_OBJ[@]}" -lc -lm -lgcc -o "$OUT/mp_count.elf"
arm-none-eabi-gcc "${CFLAGS[@]}" -Os -DKDM_COUNT -c "$EXP/bench/bench_native.c" -o "$OUT/obj/bench_native_count.o"
arm-none-eabi-gcc "${LDFLAGS[@]}" "$OUT/obj/bench_native_count.o" "$KDM_OBJ" "${CORE_OBJ[@]}" -lc -lgcc \
    -o "$OUT/kdm_count.elf"
arm-none-eabi-size "$OUT/mp_count.elf" "$OUT/kdm_count.elf" >&2

# 3. Counts: instructions between the markers, per sample.
count() {   # elf workload n -> "instructions/sample checkline"
    "$QEMU" -one-insn-per-tb -d nochain,exec -D /dev/stdout "$1" "$2" "$3" |
        awk -v n="$3" '/^Trace/ { f = $NF; if (f == "kd_mark_begin") on = 1; else if (f == "kd_mark_end") on = 0; else if (on) c++; next }
                       { line = $0 } END { printf "%d %s", c / n, line }'
}
read -r MARK _ <<< "$(count "$OUT/mp_count.elf" markers "$N")"
{
    echo "# Cortex-M0+ instructions per sample (op + present), $N samples after 4 warm-up"
    echo
    echo "MicroPython marker bracket (subtracted from the MicroPython column): $MARK instructions."
    echo
    echo '| workload | C through kdm | MicroPython + binding | VM + binding overhead | ratio | crc C | crc MicroPython |'
    echo '|---|---:|---:|---:|---:|---|---|'
    for w in idle full_redraw label_one_char button_press panel_move_4px window_rebuild sprite_pixel \
             sprite_16px_calls sprite_16px_batched sprite_import window_activate window_move_8px window_open_close \
             events_3 events_3_poll_into rects_1_calls rects_16_calls rects_256_calls rects_16_batched rects_256_batched; do
        cw="$w"
        [ "$w" = events_3_poll_into ] && cw=events_3
        read -r c ccheck <<< "$(count "$OUT/kdm_count.elf" "$cw" "$N")"
        read -r m mcheck <<< "$(count "$OUT/mp_count.elf" "$w" "$N")"
        m=$((m - MARK))
        awk -v w="$w" -v c="$c" -v m="$m" -v cc="${ccheck##* }" -v mc="${mcheck##* }" \
            'BEGIN { printf "| %s | %d | %d | %d | %.2f | %s | %s |\n", w, c, m, m - c, c ? m / c : 0, cc, mc }'
    done
} | tee "$OUT/counts.md"
