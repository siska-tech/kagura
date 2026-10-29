# SPDX-License-Identifier: Apache-2.0
# Raw REPL runner with streaming logs, so long hardware runs remain observable.
[CmdletBinding()]
param(
    [string]$Port='COM7',
    [Parameter(Mandatory=$true)][string]$CodeFile,
    [Parameter(Mandatory=$true)][string]$LogFile,
    [int]$TimeoutSeconds=180,
    [string]$StopFile
)
$ErrorActionPreference='Stop'
$serial=[IO.Ports.SerialPort]::new($Port,115200)
$serial.DtrEnable=$true
$serial.RtsEnable=$true
$serial.ReadTimeout=100
$serial.WriteTimeout=5000
$serial.Encoding=New-Object Text.UTF8Encoding($false)
$log=[IO.StreamWriter]::new($LogFile,$false,(New-Object Text.UTF8Encoding($false)))
$log.AutoFlush=$true
$watch=[Diagnostics.Stopwatch]::StartNew()
$response='';$line='';$stopped=$false
try {
    $serial.Open()
    $serial.DiscardInBuffer()
    $serial.Write([string][char]1)
    while(!$response.EndsWith('>')) {
        if($watch.Elapsed.TotalSeconds -gt 10) { throw 'raw REPL prompt timeout' }
        $response+=$serial.ReadExisting()
        Start-Sleep -Milliseconds 10
    }
    $code=[IO.File]::ReadAllText((Resolve-Path -LiteralPath $CodeFile))
    for($offset=0;$offset -lt $code.Length;$offset+=128) {
        $serial.Write($code.Substring($offset,[Math]::Min(128,$code.Length-$offset)))
        Start-Sleep -Milliseconds 2
    }
    $serial.Write([string][char]4)
    $response='';$watch.Restart()
    while(!$response.EndsWith(([string][char]4)+'>')) {
        if($watch.Elapsed.TotalSeconds -gt $TimeoutSeconds) {
            $serial.Write([string][char]3)
            throw 'raw REPL timeout; interrupt requested, check device before retry'
        }
        if($StopFile -and !$stopped -and (Test-Path -LiteralPath $StopFile)) {
            $serial.Write([string][char]3);$stopped=$true
            Write-Output 'HOST_STOP_REQUESTED'
        }
        $chunk=$serial.ReadExisting()
        if($chunk) {
            $response+=$chunk
            $log.Write($chunk)
            $line+=$chunk.Replace([string][char]4,'')
            while($line.Contains("`n")) {
                $break=$line.IndexOf("`n")
                Write-Output $line.Substring(0,$break).TrimEnd("`r")
                $line=$line.Substring($break+1)
            }
        }
        Start-Sleep -Milliseconds 10
    }
    if(!$response.StartsWith('OK')) { throw 'raw REPL acknowledgement missing' }
    $parts=$response.Substring(2).Split([char]4)
    if($parts[1]) { throw $parts[1] }
} finally {
    if($serial.IsOpen) { try { $serial.Write([string][char]2) } finally { $serial.Close() } }
    $serial.Dispose();$log.Dispose()
}
