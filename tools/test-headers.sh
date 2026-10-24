#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Compile/assemble checks for the generated host headers (tools/gen-registers.ps1).
# ca65 (cc65 package) is optional locally and required with KAGURA_REQUIRE_CA65=1.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
out=build/headers
mkdir -p "$out"
cc -std=c11 -Wall -Wextra -pedantic -Werror -Isoftware/include software/tests/regs_c.c -o "$out/regs_c"
"$out/regs_c"
echo "PASS: C header"
if command -v ca65 > /dev/null; then
    for src in regs_ca65 regs_ca65_base; do
        ca65 -I software/w65c02 -o "$out/$src.o" "software/tests/$src.s"
    done
    echo "PASS: ca65 include"
elif [ "${KAGURA_REQUIRE_CA65:-0}" = 1 ]; then
    echo "FAIL: ca65 not found"; exit 1
else
    echo "SKIP: ca65 not found"
fi
