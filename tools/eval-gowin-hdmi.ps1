# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([string]$Gowin='C:\Gowin\Gowin_V1.9.11.03_Education_x64\IDE\bin\gw_sh.exe', [switch]$IncludeStream)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(!(Test-Path -LiteralPath $Gowin)) { throw 'Specify -Gowin with the installed gw_sh.exe path' }
$rows=@()
$modes=@('dvi','hdmi')
if($IncludeStream) {
    if(!(Test-Path (Join-Path $root 'build/generated/kagura_hdmi_stream.sv'))) { throw 'Run python3 tools/prepare-hdmi-stream.py first' }
    $modes+= 'stream'
}
foreach($mode in $modes) {
    $build=Join-Path $root "build/gowin-$mode"
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    Push-Location $build
    try {
        & $Gowin (Join-Path $root 'tools/eval-gowin-hdmi.tcl') $mode | Tee-Object -FilePath 'synthesis.log'
        if($LASTEXITCODE -ne 0) { throw "$mode synthesis failed" }
    } finally { Pop-Location }
    $report=Join-Path $build "impl/gwsynthesis/kagura_${mode}_eval_syn.rpt.html"
    $html=Get-Content -LiteralPath $report -Raw
    $logic=[regex]::Match($html,'Logic</td>\s*<td>(\d+)\((\d+) LUT, (\d+) ALU(?:, (\d+) RAM16)?\)')
    $ff=[regex]::Match($html,'--Register as FF</td>\s*<td>(\d+)')
    $ram=[regex]::Match($html,'BSRAM</td>\s*<td>(\d+)')
    if(!$logic.Success -or !$ff.Success -or !$ram.Success) { throw 'Unexpected report format; inspect report manually' }
    $rows+= [ordered]@{mode=$mode;logic=[int]$logic.Groups[1].Value;lut=[int]$logic.Groups[2].Value;alu=[int]$logic.Groups[3].Value;ram16=[int]$logic.Groups[4].Value;ff=[int]$ff.Groups[1].Value;bsram=[int]$ram.Groups[1].Value;report_sha256=(Get-FileHash -LiteralPath $report).Hash.ToLowerInvariant()}
}
$summary=[ordered]@{scope='synthesis-only external-clock diagnostics; stream includes FIFO; no PLL/PHY/STA';tool=$Gowin;upstream_revision='83b1c9543a91b776671a44e68e130f81cae437b7';results=$rows}
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $root 'build/gowin-hdmi-summary.json') -Encoding ascii
$rows | ForEach-Object { [pscustomobject]$_ } | Format-Table mode,logic,lut,alu,ram16,ff,bsram
