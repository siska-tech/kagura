# SPDX-License-Identifier: Apache-2.0
# M0 baseline: build maintained Tang Nano 9K configurations from the current
# checkout, run the STA summary, and store one evidence manifest per
# configuration under reports/<revision>/<tool-version>/<configuration>/.
# reports/ is outside Git; only the small summary is meant to be quoted in
# docs. Run tools/test-verilator.sh (or tools/prepare-hdmi-stream.py) first.
[CmdletBinding()]
param(
    [string]$Gowin='C:\Gowin\Gowin_V1.9.11.03_Education_x64\IDE\bin\gw_sh.exe',
    [string[]]$Configs=@('hdmi','dvi','phase2','spi','qspi','spipsram','qspipsram','hdmi720','phase2720','spi720','qspi720','qspipsram720','phase2boot','phase2boot720'),
    [string]$Pattern='bars',
    [double]$MinSetupSlack=0.10
)
$ErrorActionPreference='Stop'
# `powershell -File ... -Configs spi,demo` passes one comma-joined string.
$Configs=@($Configs | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
$root=Split-Path -Parent $PSScriptRoot
if(!(Test-Path -LiteralPath $Gowin)) { throw 'Specify -Gowin with the installed gw_sh.exe path' }
$stream=Join-Path $root 'build/generated/kagura_hdmi_stream.sv'
if(!(Test-Path -LiteralPath $stream)) { throw 'Run python3 tools/prepare-hdmi-stream.py first' }
function Get-Sha([string]$path) { (Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant() }
function Get-TextSha([string[]]$lines) {
    $bytes=[Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $sha=[Security.Cryptography.SHA256]::Create()
    try { -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) } finally { $sha.Dispose() }
}
function Get-Count([string]$text,[string]$label) {
    $m=[regex]::Match($text,"(?m)^\s*-*$([regex]::Escape($label))\s*\|\s*(\d+)")
    if($m.Success) { [int]$m.Groups[1].Value } else { 0 }
}
$revision=(git -C $root rev-parse HEAD).Trim()
$tree=(git -C $root rev-parse 'HEAD^{tree}').Trim()
# Only tracked changes count as dirty; untracked build outputs are ignored.
$dirty=@(git -C $root status --porcelain --untracked-files=no)
$trackedDiff=@(git -C $root diff --binary HEAD)
$trackedDiffSha=Get-TextSha $trackedDiff
$sourceHashes=[ordered]@{}
foreach($path in @(git -C $root ls-files rtl boards tools/build-nano9k.tcl tools/prepare-hdmi-stream.py third_party/hdl-util-hdmi)) {
    $sourceHashes[$path]=Get-Sha (Join-Path $root $path)
}
$toolVersion=Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Gowin)))
$runId=$revision.Substring(0,7)
if($dirty.Count) { $runId="$runId-dirty-$($trackedDiffSha.Substring(0,8))" }
$reportRoot=Join-Path $root "reports/$runId/$toolVersion"
$rows=@()
foreach($config in $Configs) {
    $wide=$config -match '720$'
    $base=$config -replace '720$',''
    $name=@{hdmi='kagura_phase1';dvi='kagura_phase1_dvi';phase2='kagura_phase2';phase2boot='kagura_phase2boot';demo='kagura_demo';spi='kagura_spi';qspi='kagura_qspi';spipsram='kagura_spi_psram';qspipsram='kagura_qspi_psram'}[$base]
    if(!$name -or ($wide -and $base -eq 'dvi')) { throw "Unknown configuration $config" }
    if($wide) { $name= if($base -eq 'hdmi') { 'kagura_hdmi720' } else { "${name}720" } }
    $dir="build/baseline/$config"
    $build=Join-Path $root $dir
    if(Test-Path -LiteralPath $build) { Remove-Item -Recurse -Force -LiteralPath $build }
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    $command="gw_sh tools/build-nano9k.tcl $config $Pattern"
    Write-Host "== $config"
    Push-Location $build
    $watch=[Diagnostics.Stopwatch]::StartNew()
    try {
        & $Gowin (Join-Path $root 'tools/build-nano9k.tcl') $config $Pattern *> build.log
        $exit=$LASTEXITCODE
    } finally { Pop-Location }
    $seconds=[math]::Round($watch.Elapsed.TotalSeconds,1)
    $pnr=Join-Path $build 'impl/pnr'
    $fs=Join-Path $pnr "$name.fs"
    $out=Join-Path $reportRoot $config
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    Copy-Item -LiteralPath (Join-Path $build 'build.log') -Destination $out
    $row=[ordered]@{configuration=$config; base_name=$name; command=$command; exit_code=$exit; runtime_s=$seconds}
    if($exit -ne 0 -or !(Test-Path -LiteralPath $fs)) {
        $row.result='build_failed'
    } else {
        $rpt=Get-Content -LiteralPath (Join-Path $pnr "$name.rpt.txt") -Raw
        $timing=& (Join-Path $PSScriptRoot 'check-nano9k-timing.ps1') -ReportOnly -BuildDir $dir -BaseName $name | ConvertFrom-Json
        $tr=[regex]::Replace((Get-Content -LiteralPath (Join-Path $pnr "${name}_tr_content.html") -Raw),'<[^>]+>',' ') -replace '&nbsp;',' ' -replace '\s+',' '
        $fmax=[ordered]@{}
        foreach($m in [regex]::Matches($tr,'\d+ ((?:pixel|system|serial)\d+) [\d.]+\(MHz\) ([\d.]+)\(MHz\)')) { $fmax[$m.Groups[1].Value]=[double]$m.Groups[2].Value }
        $tns=[ordered]@{}
        foreach($m in [regex]::Matches($tr,'((?:clk|pixel|system|serial)\d+) (Setup|Hold) (-?[\d.]+) (\d+)')) { $tns["$($m.Groups[1].Value)_$($m.Groups[2].Value.ToLower())"]=[double]$m.Groups[3].Value }
        $negativeTns=@($tns.Keys | Where-Object { $tns[$_] -lt 0 })
        $pass=$timing.setup_violated_endpoints -eq 0 -and $timing.hold_violated_endpoints -eq 0 -and $timing.negative_analyses.Count -eq 0 -and $negativeTns.Count -eq 0
        $marginOk=$pass -and $timing.worst.Setup.slack_ns -ge $MinSetupSlack
        $row.result= if(!$pass) { 'sta_fail' } elseif(!$marginOk) { 'sta_margin_fail' } else { 'sta_pass' }
        $row.resources=[ordered]@{logic=Get-Count $rpt 'Logic'; register=Get-Count $rpt 'Register'; ff=Get-Count $rpt 'Logic Register as FF'; ram16=Get-Count $rpt 'SSRAM(RAM16)'; bsram=Get-Count $rpt 'BSRAM'; dsp=Get-Count $rpt 'DSP'; rpll=Get-Count $rpt 'rPLL'; oser10=Get-Count $rpt 'OSER10'}
        $row.timing=[ordered]@{setup_violated_endpoints=$timing.setup_violated_endpoints; hold_violated_endpoints=$timing.hold_violated_endpoints; worst=$timing.worst; tns_ns=$tns; fmax_mhz=$fmax}
        $row.hashes=[ordered]@{bitstream=Get-Sha $fs; cst=Get-Sha (Join-Path $build "kagura_$config.cst"); sdc=Get-Sha (Join-Path $build "kagura_$config.sdc"); sta_report=$timing.report_sha256; resource_report=Get-Sha (Join-Path $pnr "$name.rpt.txt")}
        foreach($file in "$name.rpt.txt","${name}_tr_content.html") { Copy-Item -LiteralPath (Join-Path $pnr $file) -Destination $out }
        foreach($file in "kagura_$config.cst","kagura_$config.sdc",'timing-status.json') { Copy-Item -LiteralPath (Join-Path $build $file) -Destination $out }
    }
    $manifest=[ordered]@{
        scope='M0 board P&R baseline; numeric STA only. 720p excludes OSER10 RESET recovery/removal (docs/timing.md). No hardware test.'
        revision=$revision; tree=$tree; tracked_changes=$dirty; tracked_diff_sha256=$trackedDiffSha; source_hashes=$sourceHashes
        minimum_setup_slack_ns=$MinSetupSlack; tool=$toolVersion; device='GW1NR-LV9QN88PC6/I5 (GW1NR-9C)'
        pattern=$Pattern; generated_hdmi_stream_sha256=Get-Sha $stream; build=$row
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $out 'manifest.json') -Encoding ascii
    $rows+=$row
}
$summary=[ordered]@{revision=$revision; tree=$tree; tracked_changes=$dirty; tracked_diff_sha256=$trackedDiffSha; run_id=$runId; minimum_setup_slack_ns=$MinSetupSlack; tool=$toolVersion; results=$rows}
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'summary.json') -Encoding ascii
$rows | ForEach-Object { [pscustomobject]@{config=$_.configuration; result=$_.result; logic=$_.resources.logic; register=$_.resources.register; bsram=$_.resources.bsram; setup_ns=$_.timing.worst.Setup.slack_ns; hold_ns=$_.timing.worst.Hold.slack_ns; s=$_.runtime_s} } | Format-Table -AutoSize
if(@($rows | Where-Object { $_.result -ne 'sta_pass' }).Count -gt 0) { throw 'One or more configurations failed to build or meet STA' }
