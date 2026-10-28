#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Checks tools/ci-changes.sh: path rules, every tracked file, and the event diffs.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
script="$root/tools/ci-changes.sh"
failures=0

# Prints the keys set to true, space-separated, in ci-changes.sh order.
selected() { awk -F= '$2 == "true" { printf "%s%s", sep, $1; sep = " " }'; }
expect() {
    local name="$1" want="$2" got="$3"
    if [ "$got" = "$want" ]; then echo "ok: $name"
    else echo "FAIL: $name: got '$got', want '$want'"; failures=$((failures + 1)); fi
}
files() { local name="$1" want="$2"; shift 2
    expect "$name" "$want" "$(printf '%s\n' "$@" | bash "$script" --files 2> /dev/null | selected)"; }

ALL="verilator rtl_sources pico micropython micropython_firmware"
files "no files" ""
files "docs only" "" README.md docs/video.md software/micropython/README.md rtl/README.md
files "design budget" "" spec/design-budget.json tools/check-design.ps1
files "board constraints" "" boards/tang-nano-9k/vdp-720p.sdc boards/tang-nano-9k/phase1.cst
files "synthesis tools" "" tools/build-nano9k.tcl tools/eval-gowin-hdmi.ps1 tools/run-baseline.ps1
files "register spec" "$ALL" spec/registers.json
files "register generator" "$ALL" tools/gen-registers.ps1
files "workflow" "$ALL" .github/workflows/phase0.yml
files "filter itself" "$ALL" tools/ci-changes.sh
files "unclassified path" "$ALL" software/new-host/main.c
files "unclassified tool" "$ALL" tools/new-tool.py
files "RTL" "verilator rtl_sources" rtl/vdp/kagura_vdp.sv
files "testbench" "verilator rtl_sources" sim/tests/tb_vdp_frame.sv
files "vendored HDMI" "verilator rtl_sources" third_party/hdl-util-hdmi/src/tmds_channel.sv
files "board RTL" "verilator" boards/tang-nano-9k/kagura_hyperram_pcm_source.sv
files "Verilator version" "verilator" tools/verilator.version
files "boot image tool" "verilator" tools/make-boot-image.py
files "header tests" "rtl_sources" software/tests/regs_c.c tools/test-headers.sh
files "C header" "rtl_sources pico" software/include/kagura_regs.h
files "Pico firmware" "pico" software/pico/main.c software/pico/CMakeLists.txt
files "PIO timing model" "pico micropython" software/pico/tests/test_pio_timing.py
files "frozen driver" "micropython micropython_firmware" software/micropython/kagura/console.py
files "board definition" "micropython micropython_firmware" software/micropython/boards/KAGURA_PICO/manifest.py
files "STAR RUNNER audio assets" "micropython" tools/gen-star-runner-audio.py \
    software/micropython/examples/shooter.py software/micropython/examples/star_runner_assets/bgm.pcm
files "STAR RUNNER hardware runner" "" tools/star-runner-device.ps1
# PR #31 without its workflow edit: Python, font and docs only.
files "kagura_ja and font" "micropython" software/micropython/kagura_ja/__init__.py \
    software/micropython/fonts/misaki8.kfnt software/micropython/fonts/README.md \
    software/micropython/examples/ja_menu.py software/micropython/tests/test_kagura_ja.py \
    tools/gen-kagura-ja-font.py README.md THIRD_PARTY.md

# Apart from the files that run everything on purpose, no tracked file may
# fall through to the catch-all.
tracked="$(git -C "$root" ls-files)"
unclassified=()
while IFS= read -r path; do
    case "$path" in
        .github/workflows/*|tools/ci-changes.sh|tools/test-ci-changes.sh|spec/registers.json|tools/gen-registers.ps1) continue ;;
    esac
    [ "$(printf '%s\n' "$path" | bash "$script" --files 2> /dev/null | selected)" != "$ALL" ] || unclassified+=("$path")
done <<< "$tracked"
expect "every tracked file is classified" "" "${unclassified[*]:-}"

# Event diffs in a scratch repository.
repo="$(mktemp -d)"
trap 'rm -rf "$repo"' EXIT
g() { git -C "$repo" -c user.name=ci -c user.email=ci@example.invalid "$@"; }
commit() { mkdir -p "$repo/$(dirname "$1")"; echo "$RANDOM" >> "$repo/$1"; g add -A; g commit -qm "$1"; g rev-parse HEAD; }
event() { local name="$1" want="$2"; shift 2
    expect "$name" "$want" "$(cd "$repo" && env "$@" bash "$script" 2> /dev/null | selected)"; }
g init -q
c0="$(commit README.md)"
c1="$(commit rtl/core/kagura_core.sv)"
c2="$(commit docs/video.md)"
g checkout -q -b topic "$c1"
c3="$(commit software/micropython/kagura_ja/__init__.py)"
event "push range" "" GITHUB_EVENT_NAME=push CI_BASE="$c1" CI_HEAD="$c2"
event "push of two commits" "verilator rtl_sources" GITHUB_EVENT_NAME=push CI_BASE="$c0" CI_HEAD="$c2"
# Only the topic's own commit; main's later docs commit is not part of it.
event "pull request since merge base" "micropython" GITHUB_EVENT_NAME=pull_request CI_BASE="$c2" CI_HEAD="$c3"
event "new branch push" "$ALL" GITHUB_EVENT_NAME=push CI_BASE=0000000000000000000000000000000000000000 CI_HEAD="$c3"
event "missing base after force push" "$ALL" GITHUB_EVENT_NAME=push CI_BASE=1234567890abcdef1234567890abcdef12345678 CI_HEAD="$c3"
event "empty base" "$ALL" GITHUB_EVENT_NAME=pull_request CI_BASE= CI_HEAD="$c3"
event "manual run" "$ALL" GITHUB_EVENT_NAME=workflow_dispatch CI_BASE= CI_HEAD="$c3"
event "scheduled run" "$ALL" GITHUB_EVENT_NAME=schedule CI_BASE= CI_HEAD="$c3"
event "no event" "$ALL" GITHUB_EVENT_NAME= CI_BASE="$c0" CI_HEAD="$c3"

if [ "$failures" != 0 ]; then echo "FAIL: $failures check(s)"; exit 1; fi
echo "PASS: change filter"
