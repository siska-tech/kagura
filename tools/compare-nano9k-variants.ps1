# SPDX-License-Identifier: Apache-2.0
# P1-05: build the DVI and HDMI+audio board tops with identical device, tool,
# options, pins, clocks and serializer placement, then tabulate the difference.
# The stress video source keeps every TMDS encoder bit; the flashable colour-bar
# image (tools/build-nano9k.tcl defaults) is not used for these numbers.
[CmdletBinding()]
param([string]$Gowin='C:\Gowin\Gowin_V1.9.11.03_Education_x64\IDE\bin\gw_sh.exe',[string]$Pattern='stress')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(!(Test-Path -LiteralPath $Gowin)) { throw 'Specify -Gowin with the installed gw_sh.exe path' }
if(!(Test-Path (Join-Path $root 'build/generated/kagura_hdmi_stream.sv'))) { throw 'Run python3 tools/prepare-hdmi-stream.py first' }
function Get-Count([string]$text,[string]$label) {
    $m=[regex]::Match($text,"(?m)^\s*-*$([regex]::Escape($label))\s*\|\s*(\d+)")
    if($m.Success) { [int]$m.Groups[1].Value } else { 0 }
}
$rows=@()
foreach($mode in 'dvi','hdmi') {
    $dir="build/p1-05-$mode-$Pattern"
    $build=Join-Path $root $dir
    $base= if($mode -eq 'hdmi') { 'kagura_phase1' } else { 'kagura_phase1_dvi' }
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    Push-Location $build
    $watch=[Diagnostics.Stopwatch]::StartNew()
    try {
        & $Gowin (Join-Path $root 'tools/build-nano9k.tcl') $mode $Pattern *> build.log
        if($LASTEXITCODE -ne 0) { throw "$mode build failed; see $dir/build.log" }
    } finally { Pop-Location }
    $seconds=[math]::Round($watch.Elapsed.TotalSeconds,1)
    $rpt=Get-Content -LiteralPath (Join-Path $build "impl/pnr/$base.rpt.txt") -Raw
    $logic=[regex]::Match($rpt,'--LUT,ALU,ROM16\s*\|\s*(\d+)\((\d+) LUT, (\d+) ALU')
    $timing=& (Join-Path $PSScriptRoot 'check-nano9k-timing.ps1') -ReportOnly -BuildDir $dir -BaseName $base | ConvertFrom-Json
    $tr=[regex]::Replace((Get-Content -LiteralPath (Join-Path $build "impl/pnr/${base}_tr_content.html") -Raw),'<[^>]+>',' ') -replace '&nbsp;',' ' -replace '\s+',' '
    $fmax=[ordered]@{}
    foreach($m in [regex]::Matches($tr,'\d+ (pixel25|system54|serial126) \S+\(MHz\) ([\d.]+)\(MHz\)')) { $fmax[$m.Groups[1].Value]=[double]$m.Groups[2].Value }
    $tns=[ordered]@{}
    foreach($m in [regex]::Matches($tr,'(clk27|serial126|pixel25|system54) (Setup|Hold) (-?[\d.]+) (\d+)')) { $tns["$($m.Groups[1].Value)_$($m.Groups[2].Value.ToLower())"]=[double]$m.Groups[3].Value }
    $rows+= [ordered]@{
        mode=$mode; pattern=$Pattern
        logic=Get-Count $rpt 'Logic'; lut=[int]$logic.Groups[2].Value; alu=[int]$logic.Groups[3].Value
        ram16=Get-Count $rpt 'SSRAM(RAM16)'; ff=Get-Count $rpt 'Logic Register as FF'
        bsram=Get-Count $rpt 'BSRAM'; dsp=Get-Count $rpt 'DSP'
        rpll=Get-Count $rpt 'rPLL'; clkdiv=Get-Count $rpt 'CLKDIV'; oser10=Get-Count $rpt 'OSER10'
        setup_violated=$timing.setup_violated_endpoints; hold_violated=$timing.hold_violated_endpoints
        worst=$timing.worst; tns=$tns; fmax_mhz=$fmax; runtime_s=$seconds
        report_sha256=$timing.report_sha256
        bitstream_sha256=(Get-FileHash -LiteralPath (Join-Path $build "impl/pnr/$base.fs")).Hash.ToLowerInvariant()
    }
}
$diff=[ordered]@{}
foreach($k in 'logic','lut','alu','ram16','ff','bsram','dsp','rpll','oser10') { $diff[$k]=$rows[1][$k]-$rows[0][$k] }
$summary=[ordered]@{
    scope='P1-05 board P&R comparison; same device/tool/options/CST; stress video source; audio diff includes test tone, FIFO, transport and packets'
    tool=$Gowin; device='GW1NR-LV9QN88PC6/I5 (GW1NR-9C)'
    results=$rows; hdmi_minus_dvi=$diff
    budget_hdmi_protocol_phy=[ordered]@{lut=2000;ff=1500;bsram=1}
}
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $root 'build/p1-05-summary.json') -Encoding ascii
$rows | ForEach-Object { [pscustomobject]$_ } | Format-Table mode,logic,lut,alu,ram16,ff,bsram,dsp,rpll,oser10,setup_violated,hold_violated,runtime_s
[pscustomobject]$diff | Format-Table
