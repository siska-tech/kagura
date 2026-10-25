# SPDX-License-Identifier: Apache-2.0
# Read-only UART evidence capture for the HyperRAM diagnostic/HDMI evaluation.
[CmdletBinding()]
param(
    [string]$Port='COM8',
    [int]$Passes=16,
    [int]$TimeoutSeconds=120,
    [string]$LogPath='build/hyperram-uart.log'
)
$ErrorActionPreference='Stop'
if($Passes -lt 1 -or $TimeoutSeconds -lt 1) { throw 'Passes and timeout must be positive' }
$serial=New-Object System.IO.Ports.SerialPort $Port,115200,None,8,One
$serial.ReadTimeout=1000
$serial.NewLine="`n"
$count=0
$previous=$null
$lines=New-Object 'System.Collections.Generic.List[string]'
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    $serial.Open()
    # Opening in the middle of a UART message is normal; ignore that first fragment.
    $first=$true
    while($count -lt $Passes -and $watch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try { $line=$serial.ReadLine().Trim() } catch [TimeoutException] { continue }
        if($first) { $first=$false; if($line -notmatch '^P [0-9A-F]{4} ') { continue } }
        $lines.Add($line)
        Write-Output $line
        if($line -notmatch '^P ([0-9A-F]{4}) S 03 R 6 E 00000000 A 00000 G 00000000 X 00000000$') {
            throw 'Unexpected UART line or memory failure; inspect the saved log'
        }
        $pass=[Convert]::ToInt32($Matches[1],16)
        if($null -ne $previous -and $pass -ne (($previous+1) -band 65535)) {
            throw 'UART pass sequence is not consecutive'
        }
        $previous=$pass
        $count++
    }
    if($count -ne $Passes) { throw "Timed out after $count/$Passes complete passes" }
    Write-Output "PASS: $count consecutive zero-error passes at phase 3, rd_latency 6"
} finally {
    if($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
    [IO.File]::WriteAllLines($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($LogPath),$lines)
}
