# SPDX-License-Identifier: Apache-2.0
# Arithmetic/document and board timing-contract checks. No simulation/synthesis.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
# MISO exceptions rely on four system clocks per half-SCLK. Check the actual
# board instances as well as the timing bench; a default/override change must
# not silently keep the old multicycle exception.
foreach($entry in @(
    @('boards/tang-nano-9k/kagura_phase2_boot_top.sv','FLASH_CLK_DIV'),
    @('boards/tang-nano-9k/kagura_boot_probe_top.sv','FLASH_CLK_DIV'),
    @('boards/tang-nano-9k/kagura_flash_magic_probe_top.sv','CLK_DIV'),
    @('sim/tests/tb_flash_reader_timing.sv','CLK_DIV')
)) {
    $source=Get-Content -LiteralPath (Join-Path $root $entry[0]) -Raw
    if($source -notmatch "\.$($entry[1])\(4\)") {
        throw "Boot MISO timing contract requires $($entry[1])=4 in $($entry[0]); re-audit RTL, SDC and timing test together"
    }
}
$budget = Get-Content -LiteralPath (Join-Path $root 'spec/design-budget.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function Assert-Equal($actual, $expected, [string]$name) {
    if ($actual -ne $expected) { throw "$name expected $expected, got $actual" }
}
$blocks = 0
$payload = 0
$unused = 0
foreach ($mem in $budget.memories) {
    Assert-Equal ($mem.depth * $mem.width) 16384 "$($mem.name) mode capacity"
    $capacity = $mem.depth * $mem.width * $mem.blocks / 8
    if ($mem.payload_bytes -gt $capacity) { throw "$($mem.name) payload exceeds capacity" }
    $blocks += $mem.blocks
    $payload += $mem.payload_bytes
    $unused += $capacity - $mem.payload_bytes
}
Assert-Equal $blocks $budget.expected.bsram_blocks 'BSRAM blocks'
Assert-Equal $payload $budget.expected.payload_bytes 'Memory payload'
Assert-Equal $unused $budget.expected.mode_unused_bytes 'Mode unused bytes'
foreach ($field in @('lut','ff','bsram','pll','dsp')) {
    $total = ($budget.resources | Measure-Object -Property $field -Sum).Sum
    if ($total -gt $budget.capacity.$field) { throw "Resource budget exceeds $field capacity" }
    if ($field -eq 'bsram') { Assert-Equal $total $blocks 'Module and memory BSRAM totals' }
    if ($field -in @('lut','ff')) { Assert-Equal $total $budget.expected.$field "$field total" }
}
$c = $budget.clocks
$v = $budget.video
$r = $budget.renderer
Assert-Equal ($c.serializer_hz / $c.pixel_hz) 5 'Serializer ratio'
Assert-Equal ($c.system_hz / $c.cpu_divisor) 3375000 'PHI2 frequency'
Assert-Equal ($c.system_hz / $c.sample_divisor) 48000 'Audio frequency'
Assert-Equal ($c.pixel_hz / ($v.h_total * $v.v_total)) 60 'Frame rate'
Assert-Equal ($c.pixel_hz * $budget.acr.n / (128 * $budget.acr.cts)) 48000 'ACR frequency'
Assert-Equal $r.bg_tiles ([math]::Ceiling(($v.width + 7) / 8)) 'Worst-case tile count'
$available = [math]::Floor($c.system_hz * $v.scale * $v.h_total / $c.pixel_hz)
$cycles = $r.registered_sprites * $r.oam_cycles_per_sprite + $r.line_sprites * $r.oam_hit_cycles + $r.bg_tiles * $r.bg_cycles_per_tile + $r.line_sprites * ($r.sprite_setup_fetch_cycles + $r.sprite_width * $r.sprite_cycles_per_pixel) + $r.control_cycles
$cpu = $available - $cycles - $r.cdc_guard_cycles
Assert-Equal $available $budget.expected.available_cycles 'Available cycles'
Assert-Equal $cycles $budget.expected.renderer_cycles 'Renderer cycles'
Assert-Equal $cpu $budget.expected.cpu_cycles 'CPU spare cycles'
if ($cpu -lt 0) { throw 'Renderer misses deadline in design model' }

# Check local Markdown file links. External URLs/anchors are outside this check.
$files = @(Get-ChildItem -LiteralPath $root -Filter '*.md' -File)
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'docs') -Filter '*.md' -File -Recurse)
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'boards') -Filter '*.md' -File -Recurse)
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'rtl') -Filter '*.md' -File -Recurse)
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'sim') -Filter '*.md' -File -Recurse)
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'software') -Filter '*.md' -File -Recurse)
foreach ($file in $files) {
    $body = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
    foreach ($match in [regex]::Matches($body, '\[[^\]]*\]\(([^)]+)\)')) {
        $target = $match.Groups[1].Value
        if ($target -match '^(https?://|#|mailto:)') { continue }
        $target = ($target -split '#',2)[0]
        $resolved = Join-Path $file.DirectoryName $target
        if (-not (Test-Path -LiteralPath $resolved)) { throw "Broken link in $($file.Name): $target" }
    }
}
# Numbers duplicated in prose are intentionally checked so edits cannot silently drift.
$schedule = Get-Content -LiteralPath (Join-Path $root 'docs/memory-access-schedule.md') -Raw -Encoding UTF8
foreach ($value in @($cycles,$available,$cpu)) {
    if (-not $schedule.Contains([string]$value)) { throw "Schedule document missing calculated value $value" }
}
$memoryDoc = Get-Content -LiteralPath (Join-Path $root 'docs/memory-map.md') -Raw -Encoding UTF8
foreach ($value in @($payload,$unused)) {
    if (-not $memoryDoc.Contains([string]$value)) { throw "Memory document missing calculated value $value" }
}
$irqDoc = Get-Content -LiteralPath (Join-Path $root 'docs/register-map.md') -Raw -Encoding UTF8
$directTable = ($irqDoc -split '(?m)^CAPS',2)[0]
$rows = [regex]::Matches($directTable, '(?m)^\| ([0-9A-F]{2}) \| [A-Z][A-Z0-9_]* \|')
$offsets = @($rows | ForEach-Object { $_.Groups[1].Value })
Assert-Equal $offsets.Count 32 'Direct register row count'
Assert-Equal (@($offsets | Select-Object -Unique).Count) 32 'Unique direct register offsets'
for ($offset = 0; $offset -lt 32; $offset++) {
    if ($offsets -notcontains ('{0:X2}' -f $offset)) { throw "Missing direct register offset $offset" }
}
Write-Output "PASS: BSRAM $blocks/26, payload $payload bytes, renderer $cycles/$available cycles, CPU reserve $cpu cycles."
Write-Output "PASS: local document links and direct register offsets."
Write-Output 'PASS: boot board instances and MISO timing test use CLK_DIV=4.'
Write-Output 'Scope: design arithmetic and source contracts; no RTL simulation, synthesis, STA or hardware test was performed.'
