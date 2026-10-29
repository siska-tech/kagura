#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Selects the CI jobs that a change needs (.github/workflows/*.yml).
#   tools/ci-changes.sh           diff of the current GitHub event
#   tools/ci-changes.sh --files   classify the paths read from stdin
# Prints key=true|false lines for $GITHUB_OUTPUT; the reason goes to stderr.
# Environment: GITHUB_EVENT_NAME, CI_BASE and CI_HEAD (the compared commits).
# A path that no rule below names runs every job, so a new kind of file is
# tested until it is classified here (and in tools/test-ci-changes.sh).
set -euo pipefail
keys=(verilator rtl_sources pico micropython micropython_firmware)
declare -A need=()
mark() { local key; for key in "$@"; do need[$key]=true; done; }
all() { mark "${keys[@]}"; }

classify() {
    case "$1" in
        # Phase 0 runs on every change: links in all Markdown, design budget.
        *.md|docs/*|LICENSE|.gitignore|.gitattributes|.vscode/*) ;;
        spec/design-budget.json|tools/check-design.ps1) ;;
        .github/workflows/*|tools/ci-changes.sh|tools/test-ci-changes.sh) all ;;
        # Generated into RTL, both host headers, the Pico build and regs.py.
        spec/registers.json|tools/gen-registers.ps1) all ;;
        rtl/*|sim/*|third_party/*) mark verilator rtl_sources ;;
        boards/*.sv) mark verilator ;;
        boards/*.cst|boards/*.sdc|boards/*.csv) ;;
        tools/test-verilator.sh|tools/verilator.version|tools/prepare-hdmi-stream.py|\
        tools/render-audio-wav.py|tools/make-boot-image.py|tools/gen-demo-art.py) mark verilator ;;
        tools/test-phase1.ps1|tools/check-dependencies.ps1|tools/test-headers.sh|\
        software/tests/*|software/w65c02/*) mark rtl_sources ;;
        software/include/*) mark rtl_sources pico ;;
        # The MicroPython driver tests load this PIO timing model.
        software/pico/tests/test_pio_timing.py) mark pico micropython ;;
        software/pico/*) mark pico ;;
        # Frozen into the UF2 (software/micropython/manifest.py).
        software/micropython/kagura/*|software/micropython/manifest.py|\
        software/micropython/boards/*) mark micropython micropython_firmware ;;
        software/micropython/*|tools/gen-kagura-ja-font.py|tools/gen-star-runner-audio.py) mark micropython ;;
        # Synthesis and board tools; CI does not run them.
        tools/*.tcl|tools/eval-gowin-*|tools/check-nano9k-timing.ps1|tools/compare-nano9k-variants.ps1|\
        tools/check-boot-miso-timing.ps1|tools/read-hyperram-uart.ps1|tools/kagura-upload.ps1|\
        tools/run-baseline.ps1|tools/star-runner-device.ps1) ;;
        *) all ;;
    esac
}

full() { echo "full run: $1" >&2; all; }

if [ "${1:-}" = --files ]; then
    mapfile -t files
    reason="given files"
else
    base="${CI_BASE:-}" head="${CI_HEAD:-HEAD}" files=() range=()
    case "${GITHUB_EVENT_NAME:-}" in
        pull_request) range=("$base...$head") ;;
        push) range=("$base" "$head") ;;
    esac
    if [ "${#range[@]}" = 0 ]; then
        full "${GITHUB_EVENT_NAME:-no event}"
    elif [[ "$base" =~ ^0*$ ]] || ! git cat-file -e "$base^{commit}" 2> /dev/null; then
        full "base commit '$base' unavailable"
    elif ! diff_out="$(git diff --name-only --no-renames "${range[@]}")"; then
        full "git diff failed"
    else
        mapfile -t files <<< "$diff_out"
        reason="${GITHUB_EVENT_NAME} ${range[*]}"
    fi
fi
if [ -n "${reason:-}" ]; then
    echo "changed files ($reason):" >&2
    for file in "${files[@]}"; do
        [ -n "$file" ] || continue
        echo "  $file" >&2
        classify "$file"
    done
fi
for key in "${keys[@]}"; do echo "$key=${need[$key]:-false}"; done
