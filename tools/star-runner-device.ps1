# SPDX-License-Identifier: Apache-2.0
param(
    [string]$Port = 'COM7',
    [string]$CodeFile,
    [string]$UploadSource,
    [string]$Destination,
    [int]$TimeoutSeconds = 60
)
$ErrorActionPreference = 'Stop'
$connection = [System.IO.Ports.SerialPort]::new($Port, 115200)
$connection.ReadTimeout = 100
$connection.WriteTimeout = 5000
function Invoke-Raw([string]$Code) {
    $connection.DiscardInBuffer()
    $connection.Write([string][char]1)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $response = ''
    while (-not $response.EndsWith('>')) {
        if ($watch.Elapsed.TotalSeconds -gt 5) { throw 'raw REPL prompt timeout (device may be busy)' }
        $response += $connection.ReadExisting()
        Start-Sleep -Milliseconds 10
    }
    for ($position=0; $position -lt $Code.Length; $position+=128) {
        $connection.Write($Code.Substring($position,[Math]::Min(128,$Code.Length-$position)))
        Start-Sleep -Milliseconds 2
    }
    $connection.Write([string][char]4)
    $response = ''
    $watch.Restart()
    while (-not $response.EndsWith(([string][char]4) + '>')) {
        if ($watch.Elapsed.TotalSeconds -gt $TimeoutSeconds) { throw 'raw REPL execution timeout; code may still be running' }
        $response += $connection.ReadExisting()
        Start-Sleep -Milliseconds 10
    }
    if (-not $response.StartsWith('OK')) { throw "raw REPL did not acknowledge code: $response" }
    $parts = $response.Substring(2).Split([char]4)
    $parts[0]
    if ($parts[1]) { throw $parts[1] }
}
try {
    $connection.Open()
    if ($UploadSource) {
        if (-not $Destination -or $Destination.Contains("'") -or $Destination.Contains("`n")) { throw 'valid Destination required' }
        $data = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $UploadSource))
        Invoke-Raw "_sr_file=open('$Destination','wb')" | Out-Null
        for ($offset=0; $offset -lt $data.Length; $offset+=512) {
            $count = [Math]::Min(512,$data.Length-$offset)
            $hex = [BitConverter]::ToString($data,$offset,$count).Replace('-','')
            Invoke-Raw "_sr_file.write(bytes.fromhex('$hex'))" | Out-Null
        }
        Invoke-Raw '_sr_file.close(); del _sr_file' | Out-Null
        "uploaded $Destination ($($data.Length) bytes)"
    }
    if ($CodeFile) { Invoke-Raw ([IO.File]::ReadAllText((Resolve-Path -LiteralPath $CodeFile))) }
} finally {
    if ($connection.IsOpen) {
        try { $connection.Write([string][char]2) }
        finally { $connection.Close() }
    }
    $connection.Dispose()
}
