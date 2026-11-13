# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([switch]$ReportOnly,[string]$BuildDir='build/nano9k',[string]$BaseName='kagura_phase1')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$build=Join-Path $root $BuildDir
$report=Join-Path $build "impl/pnr/${BaseName}_tr_content.html"
$raw=Get-Content -LiteralPath $report -Raw
$plain=[regex]::Replace($raw,'<[^>]+>',' ') -replace '&nbsp;',' ' -replace '\s+',' '
# Gowin's "Setup Violated Endpoints" count also includes recovery failures.
$values=@{}
foreach($kind in @('Setup','Hold')) {
    $match=[regex]::Match($plain,"Numbers of $kind Violated Endpoints\s+(\d+)")
    if(!$match.Success) { throw "Missing $kind result in STA report" }
    $values[$kind]=[int]$match.Groups[1].Value
}
# Path tables are sorted by slack; row 1 is the worst path of each analysis.
$worst=[ordered]@{}
foreach($kind in @('Setup','Hold','Recovery','Removal')) {
    $table=[regex]::Match($plain,"$kind Paths Table Report Command:report_timing -$($kind.ToLowerInvariant()) .*? Data Delay (\d+) (-?\d+\.\d+) (\S+) (\S+)")
    if(!$table.Success) { $worst[$kind]=$null; continue }
    $worst[$kind]=[ordered]@{slack_ns=[double]$table.Groups[2].Value;from=$table.Groups[3].Value;to=$table.Groups[4].Value}
}
$negative=@($worst.Keys | Where-Object { $worst[$_] -and $worst[$_].slack_ns -lt 0 })
$summary=[ordered]@{
    scope='board P&R; I/O and CDC constraints audited; P1-07 hardware compatibility tests pending'
    setup_violated_endpoints=$values.Setup
    hold_violated_endpoints=$values.Hold
    worst=$worst
    negative_analyses=$negative
    release_ready=$false
    report_sha256=(Get-FileHash -LiteralPath $report).Hash.ToLowerInvariant()
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $build 'timing-status.json') -Encoding ascii
$summary | ConvertTo-Json -Depth 4 | Write-Output
if(!$ReportOnly) {
    if($values.Setup -gt 0 -or $values.Hold -gt 0 -or $negative.Count -gt 0) { throw 'STA gate failed; bitstream is not release-ready' }
    throw 'Numeric checks passed, but P1-07 hardware compatibility tests are still required before release'
}
