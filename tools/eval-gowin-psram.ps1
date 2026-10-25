# SPDX-License-Identifier: Apache-2.0
param(
    [string]$GowinRoot = 'C:\Gowin\Gowin_V1.9.12.04_x64',
    [ValidateSet('EBR_BASED', 'DSR_BASED', 'LUT_BASED')]
    [string]$Implementation = 'DSR_BASED'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $GowinRoot 'IDE\ipcore\PSRAM_HS\psram_hs_2ch'
$gowin = Join-Path $GowinRoot 'IDE\bin\gw_sh.exe'
$build = Join-Path $root "build\psram-ip-eval-$($Implementation.ToLower())"
$ip = Join-Path $build 'ip'
New-Item -ItemType Directory -Force -Path $ip | Out-Null
foreach ($name in @('PSRAM_TOP.v', 'psram_code.v', 'psram_local_define.v', 'psram_local_param.v')) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination $ip -Force
}
@('`define module_name_psram kagura_psram_hs', ('`define ' + $Implementation)) |
    Set-Content -LiteralPath (Join-Path $ip 'psram_define.v') -Encoding ascii
@(
    'parameter Memory_Clock = 54;',
    'parameter PSRAM_WIDTH = 8;',
    'parameter DQ_WIDTH = 8;',
    'parameter ADDR_WIDTH = 21;',
    'parameter Burst_Length = "16_Bytes";',
    '`define burst16',
    'parameter burst_num = 4;',
    'parameter Fixed_Latency_Enable = "Fixed";',
    'parameter Initial_Latency = 6;',
    'parameter Drive_Strength = 50;',
    'parameter Deep_Power_Down = "OFF";',
    'parameter Hybrid_Sleep_Mode = "OFF";',
    'parameter Refresh_Rate = "normal";',
    'parameter PASR = "full";',
    'parameter C0_Reverse_Clk = "false";',
    'parameter C0_Diff_Clk = "true";',
    'parameter C1_Reverse_Clk = "true";',
    'parameter C1_Diff_Clk = "true";'
) | Set-Content -LiteralPath (Join-Path $ip 'psram_param.v') -Encoding ascii
$env:KAGURA_PSRAM_IP_DIR = $ip
Push-Location $build
try {
    # gw_sh emits a harmless cache-log diagnostic on stderr when its per-user
    # cache directory is unavailable; judge the tool by its process exit code.
    $savedErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $gowin (Join-Path $root 'tools\eval-gowin-psram.tcl') 2>&1 |
        Tee-Object -FilePath (Join-Path $build 'synthesis.log')
    $ErrorActionPreference = $savedErrorActionPreference
    if ($LASTEXITCODE -ne 0) { throw "Gowin synthesis failed with exit code $LASTEXITCODE" }
} finally {
    $ErrorActionPreference = 'Stop'
    Pop-Location
}
