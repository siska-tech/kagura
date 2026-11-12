#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Checks the register spec against the kagura-sdk commit in sdk.lock: the
# SDK's generated host constants (kagura_regs.h, regs.py) must be what
# tools/gen-registers.ps1 generates now, and the C header must compile.
#
# The SDK pins kagura in its hardware.lock, not the other way round, so a
# spec change lands here first and the SDK follows. When spec/registers.json
# differs from the one the pinned SDK was generated from, this reports that
# the SDK has to be regenerated (a warning) and passes; otherwise any
# difference fails.
# KAGURA_SDK_DIR: an existing kagura-sdk clone to read the commit from (not
# modified); without it the commit is fetched into build/kagura-sdk-lock.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
commit="$(awk '$1 == "commit" { print $2 }' sdk.lock)"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "FAIL: sdk.lock: commit must be a full SHA"; exit 1; }

repo="${KAGURA_SDK_DIR:-build/kagura-sdk-git}"
if [ ! -d "$repo/.git" ] && [ ! -f "$repo/.git" ]; then
    git init -q "$repo"
    git -C "$repo" remote add origin https://github.com/siska-tech/kagura-sdk.git
fi
if ! git -C "$repo" cat-file -e "$commit^{commit}" 2> /dev/null; then
    git -C "$repo" fetch -q --depth 1 origin "$commit"
fi
sdk="build/kagura-sdk-lock"
rm -rf "$sdk"
mkdir -p "$sdk"
git -C "$repo" archive "$commit" | tar -x -C "$sdk"

locked="$(awk '$1 == "registers.json-sha256" { print $2 }' "$sdk/hardware.lock")"
current="$(tr -d '\r' < spec/registers.json | sha256sum | cut -d' ' -f1)"
if [ "$locked" != "$current" ]; then
    msg="kagura-sdk ${commit:0:7} was generated from another spec/registers.json ($locked); regenerate its constants with tools/gen-registers.ps1 -SdkDir and update its hardware.lock, then sdk.lock here"
    echo "::warning::$msg"
    echo "SKIP: $msg"
    exit 0
fi
pwsh -NoProfile -File tools/gen-registers.ps1 -Check -SdkDir "$sdk"
mkdir -p build/headers
cc -std=c11 -Wall -Wextra -pedantic -Werror -I"$sdk/software/include" "$sdk/software/tests/regs_c.c" -o build/headers/regs_c
build/headers/regs_c
echo "PASS: kagura-sdk ${commit:0:7} matches spec/registers.json"
