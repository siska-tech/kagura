# SPDX-License-Identifier: Apache-2.0
# Generate register constants from spec/registers.json:
#   rtl/core/kagura_abi_pkg.sv       SystemVerilog package
#   software/include/kagura_regs.h   C header (SPI/QSPI hosts, W65C02S C)
#   software/w65c02/kagura_regs.inc  ca65 include
# -Check validates the definition, fails if any output is stale, and compares
# offsets, names, access, bits and reset values with the document tables
# (register-map.md, audio-spec.md, memory-map.md). The documents stay the
# normative prose; this keeps the two from drifting.
[CmdletBinding()]
param([switch]$Check)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$spec = Get-Content -LiteralPath (Join-Path $root 'spec/registers.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$errors = New-Object System.Collections.Generic.List[string]
function Fail([string]$message) { $errors.Add($message) }
function Props($object) { if ($null -eq $object) { @() } else { @($object.PSObject.Properties) } }
function Has($object, [string]$name) { $null -ne $object.PSObject.Properties[$name] }
function Get($object, [string]$name) { if (Has $object $name) { $object.$name } else { $null } }
function Hex2([int]$v) { '{0:X2}' -f $v }

# ---- definition checks ----
$accessKinds = @('RO', 'RW', 'RW1C', 'RW shadow', 'WO', 'indexed')
$direct = @($spec.direct)
if ($direct.Count -ne 32) { Fail "direct: expected 32 registers, got $($direct.Count)" }
for ($i = 0; $i -lt $direct.Count; $i++) { if ($direct[$i].offset -ne $i) { Fail "direct: offset $($direct[$i].offset) out of order at position $i" } }
if (@($direct.name | Select-Object -Unique).Count -ne $direct.Count) { Fail 'direct: duplicate names' }
$byName = @{}
foreach ($r in $direct) { $byName[$r.name] = $r }
function Test-Bits([string]$owner, $reg) {
    $used = @{}
    foreach ($p in (Props (Get $reg 'bits'))) {
        if ($p.Value -lt 0 -or $p.Value -gt 7) { Fail "${owner}: bit $($p.Name) out of range" }
        if ($used.ContainsKey([int]$p.Value)) { Fail "${owner}: bit $($p.Value) defined twice" }
        $used[[int]$p.Value] = $p.Name
    }
    foreach ($p in (Props (Get $reg 'fields'))) {
        $hi = $p.Value[0]; $lo = $p.Value[1]
        if ($hi -lt $lo -or $hi -gt 7 -or $lo -lt 0) { Fail "${owner}: field $($p.Name) has bad range" }
        for ($b = $lo; $b -le $hi; $b++) { if ($used.ContainsKey($b)) { Fail "${owner}: field $($p.Name) overlaps bit $b" }; $used[$b] = $p.Name }
    }
}
function Test-Reset([string]$owner, $reg) {
    $reset = Get $reg 'reset'
    if ($null -eq $reset) {
        $exempt = (Get $reg 'access') -in @('WO', 'indexed') -or (Has $reg 'variants') -or (Get $reg 'live')
        if (-not $exempt) { Fail "${owner}: reset value missing" }
    } elseif ($reset -lt 0 -or $reset -gt 255) { Fail "${owner}: reset out of range" }
    foreach ($v in (Props (Get $reg 'variants'))) { if ($v.Value -lt 0 -or $v.Value -gt 255) { Fail "${owner}: variant $($v.Name) out of range" } }
}
foreach ($r in $direct) {
    if ($r.access -notin $accessKinds) { Fail "direct $($r.name): unknown access '$($r.access)'" }
    Test-Bits "direct $($r.name)" $r
    Test-Reset "direct $($r.name)" $r
    $like = Get $r 'bits_like'
    if ($like -and -not $byName.ContainsKey($like)) { Fail "direct $($r.name): bits_like $like not found" }
}
$caps = $byName['CAPS']
foreach ($v in (Props $caps.variants)) {
    $defined = 0; foreach ($p in (Props $caps.bits)) { $defined = $defined -bor (1 -shl $p.Value) }
    if (($v.Value -band (-bnot $defined) -band 0xFF) -ne 0) { Fail "CAPS variant $($v.Name) sets undefined bits" }
}
$commands = @($spec.commands)
if (@($commands.value | Select-Object -Unique).Count -ne $commands.Count) { Fail 'commands: duplicate values' }
foreach ($c in $commands) { if ($c.value -lt 1 -or $c.value -gt 255) { Fail "command $($c.name): value out of range" } }
$ext = @($spec.ext)
for ($i = 0; $i -lt $ext.Count; $i++) {
    if ($ext[$i].index -ne $i) { Fail "ext: index $($ext[$i].index) out of order at position $i" }
    if ($ext[$i].access -notin @('RO', 'RW shadow')) { Fail "ext $($ext[$i].name): unexpected access" }
    Test-Reset "ext $($ext[$i].name)" $ext[$i]
}
if ($spec.ext_implemented_end -ne $ext.Count) { Fail 'ext: ext_implemented_end does not match the table' }
$audio = $spec.audio
$channelRegs = @($audio.channel_registers)
if (@($channelRegs.offset | Select-Object -Unique).Count -ne $channelRegs.Count) { Fail 'audio: duplicate channel offsets' }
foreach ($a in $channelRegs) {
    if ($a.offset -ge $audio.channel_stride) { Fail "audio $($a.name): offset beyond stride" }
    Test-Bits "audio $($a.name)" $a; Test-Reset "audio $($a.name)" $a
}
$channels = @($audio.channels)
if ($audio.channel_end -ne $audio.channel_stride * $channels.Count) { Fail 'audio: channel_end does not match channels x stride' }
$global = @($audio.global)
foreach ($g in $global) {
    if ($g.index -lt $audio.channel_end -or $g.index -gt 255) { Fail "audio $($g.name): index overlaps channels" }
    Test-Bits "audio $($g.name)" $g; Test-Reset "audio $($g.name)" $g
}
if (@($global.index | Select-Object -Unique).Count -ne $global.Count) { Fail 'audio: duplicate global indices' }
$vram = @($spec.vram)
for ($i = 0; $i -lt $vram.Count; $i++) {
    if ($vram[$i].end -lt $vram[$i].start) { Fail "vram $($vram[$i].name): end before start" }
    if ($i -gt 0 -and $vram[$i].start -le $vram[$i - 1].end) { Fail "vram $($vram[$i].name): overlaps previous region" }
}

# ---- generation ----
function Remove-AudioPrefix([string]$name) { $name -replace '^AUDIO_', '' }
function Get-Symbols {
    # Ordered (section, name, value, width) rows shared by all three outputs.
    $rows = New-Object System.Collections.Generic.List[object]
    function Add([string]$section, [string]$name, [long]$value, [int]$width) { $rows.Add([pscustomobject]@{section = $section; name = $name; value = $value; width = $width}) }
    Add 'ABI and identification' 'ABI_MAJOR' $spec.abi.major 8
    Add 'ABI and identification' 'ABI_MINOR' $spec.abi.minor 8
    Add 'ABI and identification' 'ID0' $byName['ID0'].reset 8
    Add 'ABI and identification' 'ID1' $byName['ID1'].reset 8
    foreach ($r in $direct) { Add 'Direct register offsets' "REG_$($r.name)" $r.offset 5 }
    foreach ($r in $direct) {
        foreach ($p in (Props (Get $r 'bits'))) { Add 'Direct register bits (masks)' "$($r.name)_$($p.Name)" (1 -shl $p.Value) 8 }
        foreach ($p in (Props (Get $r 'fields'))) {
            $mask = 0; for ($b = $p.Value[1]; $b -le $p.Value[0]; $b++) { $mask = $mask -bor (1 -shl $b) }
            Add 'Direct register bits (masks)' "$($r.name)_$($p.Name)_MASK" $mask 8
            Add 'Direct register bits (masks)' "$($r.name)_$($p.Name)_SHIFT" $p.Value[1] 8
        }
    }
    foreach ($r in $direct) { if ($null -ne (Get $r 'reset') -and $r.access -notin @('WO', 'indexed')) { Add 'Direct register reset values' "$($r.name)_RESET" $r.reset 8 } }
    foreach ($v in (Props $caps.variants)) { Add 'Direct register reset values' "CAPS_VALUE_$($v.Name.ToUpperInvariant())" $v.Value 8 }
    foreach ($c in $commands) { Add 'COMMAND values' "CMD_$($c.name)" $c.value 8 }
    foreach ($e in $ext) { Add 'Extended register indices (EXT_REG_INDEX)' "EXT_$($e.name)" $e.index 8 }
    foreach ($e in $ext) { Add 'Extended register reset values' "EXT_$($e.name)_RESET" $e.reset 8 }
    foreach ($e in $ext) { foreach ($v in (Props (Get $e 'variants'))) { Add 'Extended register reset values' "EXT_$($e.name)_$($v.Name.ToUpperInvariant())" $v.Value 8 } }
    Add 'Audio registers (AUDIO_REG_INDEX)' 'AUDIO_CHANNELS' $channels.Count 8
    Add 'Audio registers (AUDIO_REG_INDEX)' 'AUDIO_CH_STRIDE' $audio.channel_stride 8
    foreach ($a in $channelRegs) { Add 'Audio registers (AUDIO_REG_INDEX)' "AUDIO_$($a.name)" $a.offset 8 }
    foreach ($g in $global) { Add 'Audio registers (AUDIO_REG_INDEX)' "AUDIO_$(Remove-AudioPrefix $g.name)" $g.index 8 }
    foreach ($a in @($channelRegs) + @($global)) {
        foreach ($p in (Props (Get $a 'bits'))) { Add 'Audio register bits (masks)' "AUDIO_$(Remove-AudioPrefix $a.name)_$($p.Name)" (1 -shl $p.Value) 8 }
    }
    foreach ($a in @($channelRegs) + @($global)) { if ($null -ne (Get $a 'reset')) { Add 'Audio register reset values' "AUDIO_$(Remove-AudioPrefix $a.name)_RESET" $a.reset 8 } }
    foreach ($m in $vram) {
        Add 'VRAM regions (24-bit addresses)' "VRAM_$($m.name)_BASE" $m.start 24
        Add 'VRAM regions (24-bit addresses)' "VRAM_$($m.name)_SIZE" ($m.end - $m.start + 1) 24
    }
    $rows
}
$symbols = @(Get-Symbols)
$duplicates = @($symbols | Group-Object name | Where-Object { $_.Count -gt 1 })
foreach ($d in $duplicates) { Fail "generated symbol $($d.Name) defined $($d.Count) times" }
$header = 'Generated by tools/gen-registers.ps1 from spec/registers.json. Do not edit.'
$abi = "ABI $($spec.abi.major).$($spec.abi.minor)"
function Sections { $symbols | Group-Object section | Sort-Object { [array]::IndexOf(@($symbols.section | Select-Object -Unique), $_.Name) } }

$c = New-Object System.Text.StringBuilder
[void]$c.AppendLine('/* SPDX-License-Identifier: Apache-2.0 */')
[void]$c.AppendLine("/* $header */")
[void]$c.AppendLine("/* KAGURA register ${abi}: docs/register-map.md, docs/audio-spec.md, docs/memory-map.md. */")
[void]$c.AppendLine('/* IRQ_ENABLE uses the IRQ_STATUS bit masks. */')
[void]$c.AppendLine('#ifndef KAGURA_REGS_H')
[void]$c.AppendLine('#define KAGURA_REGS_H')
foreach ($s in (Sections)) {
    [void]$c.AppendLine(''); [void]$c.AppendLine("/* $($s.Name) */")
    foreach ($r in $s.Group) { $digits = if ($r.width -gt 8) { 6 } else { 2 }; [void]$c.AppendLine(('#define KAGURA_{0,-36} 0x{1}u' -f $r.name, (("{0:X$digits}") -f $r.value))) }
}
[void]$c.AppendLine('')
[void]$c.AppendLine('/* AUDIO_REG_INDEX value for channel ch (0..5) and per-channel offset off. */')
[void]$c.AppendLine('#define KAGURA_AUDIO_INDEX(ch, off) ((unsigned)(ch) * KAGURA_AUDIO_CH_STRIDE + (unsigned)(off))')
[void]$c.AppendLine('')
[void]$c.AppendLine('#endif')

$a = New-Object System.Text.StringBuilder
[void]$a.AppendLine('; SPDX-License-Identifier: Apache-2.0')
[void]$a.AppendLine("; $header")
[void]$a.AppendLine("; KAGURA register $abi for ca65. Define KAGURA_IO_BASE before .include to")
[void]$a.AppendLine('; relocate the register window; the default is the W65C02S board base.')
[void]$a.AppendLine('; IRQ_ENABLE uses the IRQ_STATUS bit masks. Do not use RMW instructions on I/O.')
[void]$a.AppendLine('.ifndef KAGURA_IO_BASE')
[void]$a.AppendLine(('KAGURA_IO_BASE = ${0:X4}' -f $spec.io_base.w65c02))
[void]$a.AppendLine('.endif')
foreach ($s in (Sections)) {
    [void]$a.AppendLine(''); [void]$a.AppendLine("; $($s.Name)")
    foreach ($r in $s.Group) { $digits = if ($r.width -gt 8) { 6 } else { 2 }; [void]$a.AppendLine(('KAGURA_{0,-36} = ${1}' -f $r.name, (("{0:X$digits}") -f $r.value))) }
}
[void]$a.AppendLine(''); [void]$a.AppendLine('; Absolute register addresses')
foreach ($r in $direct) { [void]$a.AppendLine(('KAGURA_IO_{0,-33} = KAGURA_IO_BASE + KAGURA_REG_{0}' -f $r.name)) }
[void]$a.AppendLine('')
[void]$a.AppendLine('; AUDIO_REG_INDEX value for channel ch (0..5) and per-channel offset off.')
[void]$a.AppendLine('.define KAGURA_AUDIO_INDEX(ch, off) ((ch) * KAGURA_AUDIO_CH_STRIDE + (off))')

$sv = New-Object System.Text.StringBuilder
[void]$sv.AppendLine('// SPDX-License-Identifier: Apache-2.0')
[void]$sv.AppendLine("// $header")
[void]$sv.AppendLine("// KAGURA register $abi constants. Not yet used by the synthesized RTL; the")
[void]$sv.AppendLine('// register modules keep their own decode and tb_register_abi compares them.')
[void]$sv.AppendLine('package kagura_abi_pkg;')
foreach ($s in (Sections)) {
    [void]$sv.AppendLine(''); [void]$sv.AppendLine("    // $($s.Name)")
    foreach ($r in $s.Group) { [void]$sv.AppendLine(('    localparam logic [{0}:0] {1,-36} = {2}''h{3};' -f ($r.width - 1), $r.name, $r.width, ('{0:X}' -f $r.value))) }
}
# Per-offset access summary for the direct window, bit i = offset i.
$readable = 0L; $writable = 0L; $hasReset = 0L; $resetBits = New-Object System.Text.StringBuilder
foreach ($r in $direct) {
    $bit = [long]1 -shl $r.offset
    if ($r.access -notin @('WO', 'indexed')) { $readable = $readable -bor $bit }
    if ($r.access -notin @('RO', 'indexed')) { $writable = $writable -bor $bit }
    if ($null -ne (Get $r 'reset') -and $r.access -notin @('WO', 'indexed')) { $hasReset = $hasReset -bor $bit }
}
for ($i = 31; $i -ge 0; $i--) { $v = Get $direct[$i] 'reset'; if ($null -eq $v) { $v = 0 }; [void]$resetBits.Append((Hex2 $v)) }
[void]$sv.AppendLine(''); [void]$sv.AppendLine('    // Direct window summary, bit/byte i = offset i (indexed registers excluded).')
[void]$sv.AppendLine(('    localparam logic [31:0] DIRECT_READABLE = 32''h{0:X8};' -f $readable))
[void]$sv.AppendLine(('    localparam logic [31:0] DIRECT_WRITABLE = 32''h{0:X8};' -f $writable))
[void]$sv.AppendLine(('    localparam logic [31:0] DIRECT_HAS_RESET = 32''h{0:X8};' -f $hasReset))
[void]$sv.AppendLine("    localparam logic [255:0] DIRECT_RESET_VALUES = 256'h$resetBits;")
[void]$sv.AppendLine('endpackage')

$outputs = [ordered]@{
    'rtl/core/kagura_abi_pkg.sv' = $sv.ToString()
    'software/include/kagura_regs.h' = $c.ToString()
    'software/w65c02/kagura_regs.inc' = $a.ToString()
}

# ---- document checks ----
function Read-Doc([string]$path) { Get-Content -LiteralPath (Join-Path $root $path) -Raw -Encoding UTF8 }
function Get-TableRows([string]$text, [string]$pattern) { @([regex]::Matches($text, "(?m)^$pattern")) }
function Get-BitNames([string]$text) {
    $set = @{}
    foreach ($m in [regex]::Matches($text, 'b(\d) ([A-Z][A-Z0-9_]+)')) { $set[$m.Groups[2].Value] = [int]$m.Groups[1].Value }
    $set
}
function Compare-Bits([string]$owner, $docBits, $bits) {
    $mine = @{}; foreach ($p in (Props $bits)) { $mine[$p.Name] = [int]$p.Value }
    foreach ($k in $docBits.Keys) { if (-not $mine.ContainsKey($k) -or $mine[$k] -ne $docBits[$k]) { Fail "${owner}: document bit $k=b$($docBits[$k]) not in spec" } }
    foreach ($k in $mine.Keys) { if (-not $docBits.ContainsKey($k)) { Fail "${owner}: spec bit $k missing from document" } }
}
if ($Check) {
    # Japanese text in the documents is matched with \uXXXX escapes so this
    # script stays ASCII (Windows PowerShell 5.1 reads BOM-less files as ANSI).
    $regDoc = Read-Doc 'docs/register-map.md'
    $directDoc = ($regDoc -split '(?m)^CAPS\u306F', 2)[0]
    $rows = Get-TableRows $directDoc '\| ([0-9A-F]{2}) \| ([A-Z][A-Z0-9_]*) \| ([^|]+?) \| ([^\r\n]*) \|'
    if ($rows.Count -ne 32) { Fail "register-map.md: expected 32 direct rows, got $($rows.Count)" }
    foreach ($m in $rows) {
        $offset = [Convert]::ToInt32($m.Groups[1].Value, 16); $r = $direct[$offset]; $desc = $m.Groups[4].Value
        if ($m.Groups[2].Value -ne $r.name) { Fail "register-map.md $(Hex2 $offset): name $($m.Groups[2].Value) vs spec $($r.name)" }
        if ($m.Groups[3].Value.Trim() -ne $r.access) { Fail "register-map.md $($r.name): access '$($m.Groups[3].Value.Trim())' vs spec '$($r.access)'" }
        if ((Has $r 'bits') -and $r.name -notin @('FIFO_STATUS', 'ERROR_CODE')) { Compare-Bits "register-map.md $($r.name)" (Get-BitNames $desc) $r.bits }
        $resetMatch = [regex]::Match($desc, 'reset(\d+)')
        if ($resetMatch.Success -and [int]$resetMatch.Groups[1].Value -ne $r.reset) { Fail "register-map.md $($r.name): reset $($resetMatch.Groups[1].Value) vs spec $($r.reset)" }
        $constMatch = [regex]::Match($desc, '^(?:reset/read )?(?:0x([0-9A-F]{2})|(\d+))(?: |$|\uFF08)')
        if ($constMatch.Success) {
            $value = if ($constMatch.Groups[1].Success) { [Convert]::ToInt32($constMatch.Groups[1].Value, 16) } else { [int]$constMatch.Groups[2].Value }
            if ($value -ne $r.reset) { Fail "register-map.md $($r.name): value $value vs spec $($r.reset)" }
        }
    }
    $fifo = [regex]::Match($directDoc, '(?m)^\| 0F \| FIFO_STATUS \| RO \| b5:0 [^|]+b6\u4E88\u7D04[^|]+b7 FULL \|')
    if (-not $fifo.Success) { Fail 'register-map.md FIFO_STATUS: expected b5:0 free entries and b7 FULL' }
    foreach ($pair in @(@('\u5168\u4F53\u7248', 'full'), @('16:9\u7248', 'wide'))) {
        $m = [regex]::Match($directDoc, "$($pair[0])\u306F0x([0-9A-F]{2})")
        if (-not $m.Success -or [Convert]::ToInt32($m.Groups[1].Value, 16) -ne $caps.variants.($pair[1])) { Fail "register-map.md CAPS: $($pair[1]) value differs" }
    }
    $errorLine = [regex]::Match($regDoc, '(?m)^ERROR_CODE: ([^\r\n]+)')
    if (-not $errorLine.Success) { Fail 'register-map.md: ERROR_CODE bit list not found' } else { Compare-Bits 'register-map.md ERROR_CODE list' (Get-BitNames $errorLine.Groups[1].Value) $byName['ERROR_CODE'].bits }
    $cmdStart = $regDoc.IndexOf('| COMMAND value |'); $extStart = $regDoc.IndexOf('## Extended registers')
    $cmdRows = @(Get-TableRows $regDoc '\| ([0-9A-F]{2}) \| ([A-Z_]+) \| ' | Where-Object { $_.Index -gt $cmdStart -and $_.Index -lt $extStart })
    if ($cmdRows.Count -ne $commands.Count) { Fail "register-map.md: expected $($commands.Count) command rows, got $($cmdRows.Count)" }
    foreach ($m in $cmdRows) {
        $value = [Convert]::ToInt32($m.Groups[1].Value, 16); $cmd = @($commands | Where-Object { $_.value -eq $value })
        if ($cmd.Count -ne 1 -or $cmd[0].name -ne $m.Groups[2].Value) { Fail "register-map.md command $(Hex2 $value): $($m.Groups[2].Value) not in spec" }
    }
    $extDoc = $regDoc.Substring($extStart)
    $extRows = Get-TableRows $extDoc '\| ([0-9A-F]{2}) \| ([^|]+) \| (RW shadow|RO) ?/(\d+)([^|]*) \|'
    if ($extRows.Count -ne $ext.Count) { Fail "register-map.md: expected $($ext.Count) EXT rows, got $($extRows.Count)" }
    foreach ($m in $extRows) {
        $e = $ext[[Convert]::ToInt32($m.Groups[1].Value, 16)]
        if (-not $m.Groups[2].Value.Contains($e.doc_label)) { Fail "register-map.md EXT $(Hex2 $e.index): label lacks $($e.doc_label)" }
        if ($m.Groups[3].Value -ne $e.access) { Fail "register-map.md EXT $($e.name): access differs" }
        if ([int]$m.Groups[4].Value -ne $e.reset) { Fail "register-map.md EXT $($e.name): reset $($m.Groups[4].Value) vs spec $($e.reset)" }
        $wide = [regex]::Match($m.Groups[5].Value, '16:9\u7248(\d+)')
        if ($wide.Success -and [int]$wide.Groups[1].Value -ne $e.variants.wide) { Fail "register-map.md EXT $($e.name): 16:9 value differs" }
    }
    if ($extDoc -notmatch ('(?m)^\| {0}\.\.FF \| \u672A\u5B9F\u88C5' -f (Hex2 $spec.ext_implemented_end))) { Fail 'register-map.md: EXT unimplemented range differs' }

    $audioDoc = Read-Doc 'docs/audio-spec.md'
    $chRows = Get-TableRows $audioDoc '\| ([0-9A-F]) \| ([^|\r\n]+) \|'
    $offsets = @($chRows | ForEach-Object { [Convert]::ToInt32($_.Groups[1].Value, 16) })
    if ((@($offsets) -join ',') -ne (@($channelRegs.offset) -join ',')) { Fail "audio-spec.md: channel offsets $($offsets -join ',') vs spec $(@($channelRegs.offset) -join ',')" }
    foreach ($m in $chRows) {
        $reg = @($channelRegs | Where-Object { $_.offset -eq [Convert]::ToInt32($m.Groups[1].Value, 16) })[0]
        $resetMatch = [regex]::Match($m.Groups[2].Value, 'reset(\d+)')
        $docReset = if ($resetMatch.Success) { [int]$resetMatch.Groups[1].Value } else { 0 }
        if ($docReset -ne $reg.reset) { Fail "audio-spec.md $($reg.name): reset $docReset vs spec $($reg.reset)" }
    }
    if ($audioDoc -notmatch ('ch c\u306Findex={0}\*c\+offset\uFF0800\.\.{1}\uFF09' -f $audio.channel_stride, (Hex2 ($audio.channel_end - 1)))) { Fail 'audio-spec.md: channel index formula differs' }
    foreach ($g in $global) {
        $m = [regex]::Match($audioDoc, ('(?m)^\| {0} \| {1} ([^|\r\n]+) \|' -f (Hex2 $g.index), $g.name))
        if (-not $m.Success) { Fail "audio-spec.md: $($g.name) row not found at $(Hex2 $g.index)"; continue }
        if (-not $m.Groups[1].Value.StartsWith($g.access)) { Fail "audio-spec.md $($g.name): access differs" }
        $resetMatch = [regex]::Match($m.Groups[1].Value, 'reset(\d+)')
        if ($resetMatch.Success -and [int]$resetMatch.Groups[1].Value -ne $g.reset) { Fail "audio-spec.md $($g.name): reset differs" }
        if ($g.name -eq 'AUDIO_STATUS') { Compare-Bits "audio-spec.md $($g.name)" (Get-BitNames $m.Groups[1].Value) $g.bits }
    }

    $memDoc = Read-Doc 'docs/memory-map.md'
    $memRows = Get-TableRows $memDoc '\| ([0-9A-F]{6})\u2013([0-9A-F]{6}) \|'
    if ($memRows.Count -ne $vram.Count) { Fail "memory-map.md: expected $($vram.Count) regions, got $($memRows.Count)" }
    for ($i = 0; $i -lt [math]::Min($memRows.Count, $vram.Count); $i++) {
        $s = [Convert]::ToInt32($memRows[$i].Groups[1].Value, 16); $e = [Convert]::ToInt32($memRows[$i].Groups[2].Value, 16)
        if ($s -ne $vram[$i].start -or $e -ne $vram[$i].end) { Fail "memory-map.md: region $($vram[$i].name) range differs" }
    }
}

if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Host "FAIL: $_" }; throw "$($errors.Count) register definition error(s)" }
$utf8 = New-Object System.Text.UTF8Encoding $false
$stale = @()
foreach ($path in $outputs.Keys) {
    $full = Join-Path $root $path
    $text = $outputs[$path] -replace "`r`n", "`n"
    if ($Check) {
        # A Windows checkout may convert line endings; compare the text only.
        $current = if (Test-Path -LiteralPath $full) { [IO.File]::ReadAllText($full) -replace "`r`n", "`n" } else { '' }
        if ($current -ne $text) { $stale += $path }
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $full) | Out-Null
        [IO.File]::WriteAllText($full, $text, $utf8)
    }
}
if ($stale.Count -gt 0) { throw "Generated files are stale; run tools/gen-registers.ps1: $($stale -join ', ')" }
if ($Check) { Write-Host "PASS: register spec ($($direct.Count) direct, $($ext.Count) EXT, $($channelRegs.Count)+$($global.Count) audio, $($commands.Count) commands) matches documents and generated files." }
else { Write-Host "Generated $($outputs.Keys -join ', ')" }
