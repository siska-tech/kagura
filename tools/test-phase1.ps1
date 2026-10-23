# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([string]$Iverilog='', [string]$Vvp='')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(!$Iverilog) { $Iverilog=(Get-Command iverilog -ErrorAction Stop).Source }
if(!$Vvp) { $Vvp=(Get-Command vvp -ErrorAction Stop).Source }
$build=Join-Path $root 'build/phase1'
New-Item -ItemType Directory -Force -Path $build | Out-Null
$output=Join-Path $build 'sources.vvp'
& $Iverilog -g2012 -s tb_phase1_sources -o $output (Join-Path $root 'rtl/vdp/kagura_bar_pattern.sv') (Join-Path $root 'rtl/vdp/kagura_test_pattern.sv') (Join-Path $root 'rtl/audio/kagura_test_tone.sv') (Join-Path $root 'sim/tests/tb_phase1_sources.sv')
if($LASTEXITCODE -ne 0) { throw 'RTL compilation failed' }
$result=@(& $Vvp $output)
$result | Write-Output
if($LASTEXITCODE -ne 0 -or ($result -join "`n") -notmatch 'PASS: two complete video frames') { throw 'RTL simulation failed' }
$output=Join-Path $build 'tmds.vvp'
# Icarus 10.2 portable parser does not accept upstream always_comb/always_ff/unique.
# Make a test-only scheduling-compatible copy; preserve upstream bytes/hashes.
$upstream=Get-Content -LiteralPath (Join-Path $root 'third_party/hdl-util-hdmi/src/tmds_channel.sv') -Raw
$compat=Join-Path $build 'tmds_channel_compat.sv'
$upstream.Replace('always_comb','always @*').Replace('always_ff','always').Replace('unique case','case') | Set-Content -LiteralPath $compat -Encoding ascii
& $Iverilog -g2012 -s tb_tmds_channel -o $output $compat (Join-Path $root 'sim/tests/tb_tmds_channel.sv')
if($LASTEXITCODE -ne 0) { throw 'TMDS compilation failed' }
$result=@(& $Vvp $output)
$result | Write-Output
if($LASTEXITCODE -ne 0 -or ($result -join "`n") -notmatch 'PASS: upstream TMDS') { throw 'TMDS simulation failed' }
