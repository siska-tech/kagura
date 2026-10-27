# SPDX-License-Identifier: Apache-2.0
# Validate the scoped boot MISO exceptions without replacing the global STA
# report_timing tables. Missing/renamed capture bits must fail closed.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Report,[string]$Reader='boot/reader')
$ErrorActionPreference='Stop'
$raw=Get-Content -LiteralPath $Report -Raw
function Plain([string]$html) {
    ([Net.WebUtility]::HtmlDecode(($html -replace '<[^>]+>',' ')) -replace '\s+',' ').Trim()
}
$plain=Plain $raw
$clock=[regex]::Match($plain,'\bsystem54 Generated (\d+\.\d+)')
if(!$clock.Success) { throw 'Missing system54 clock in boot STA report' }
$period=[double]$clock.Groups[1].Value
$expected=@("$Reader/data_0_s0","$Reader/rx_shift_0_s0")
$results=[ordered]@{}
foreach($kind in @('Setup','Hold')) {
    $section=[regex]::Match($raw,"(?s)<h3><a name=`"${kind}_Analysis_Exceptions`">(.*?)(?=<h3><a name=|$)")
    if(!$section.Success) { throw "Missing boot MISO $kind exception report" }
    $body=$section.Groups[1].Value
    $command="report_exceptions -$($kind.ToLowerInvariant()) -from [get_ports {flash_miso}] -max_paths 100 -max_common_paths 1"
    if(!(Plain $body).Contains($command)) { throw "Missing scoped boot MISO $kind report command" }
    $rows=@()
    foreach($path in @([regex]::Split($body,'<h3>Path\d+</h3>') | Select-Object -Skip 1)) {
        $text=Plain $path
        $summary=[regex]::Match($text,'Path Summary: Slack (-?\d+\.\d+) Data Arrival Time -?\d+\.\d+ Data Required Time -?\d+\.\d+ From (\S+) To (\S+) Launch Clk (\S+) Latch Clk (\S+)')
        $relation=[regex]::Match($text,"$kind Relationship (-?\d+\.\d+)")
        if(!$summary.Success -or !$relation.Success) { throw "Incomplete boot MISO $kind path" }
        $from=$summary.Groups[2].Value; $to=$summary.Groups[3].Value
        if($from -ne 'flash_miso_ibuf' -or $to -notin $expected -or
           $summary.Groups[4].Value -ne 'system54:[R]' -or $summary.Groups[5].Value -ne 'system54:[R]') {
            throw "Unexpected boot MISO $kind endpoint: $from -> $to"
        }
        $sign=if($kind -eq 'Setup') { 1 } else { -1 }
        if([math]::Abs([double]$relation.Groups[1].Value-$sign*4*$period) -gt 0.005) {
            throw "Boot MISO $kind relationship is not $sign * 4 system cycles"
        }
        $slack=[double]$summary.Groups[1].Value
        if($slack -lt 0) { throw "Boot MISO $kind slack is negative" }
        $rows+=[pscustomobject]@{to=$to;slack_ns=$slack;relationship_ns=[double]$relation.Groups[1].Value}
    }
    if($rows.Count -ne 2 -or @($rows.to | Sort-Object -Unique).Count -ne 2) {
        throw "Expected exactly two boot MISO $kind capture endpoints, found $($rows.Count)"
    }
    $results[$kind.ToLowerInvariant()]=$rows
}
[pscustomobject]$results
