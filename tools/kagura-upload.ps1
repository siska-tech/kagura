# SPDX-License-Identifier: Apache-2.0
# Upload a binary file into KAGURA VRAM through the Pico host firmware
# (software/pico) over its USB serial port. Each chunk of up to 4096 bytes is
# sent with `w <addr> <len>`; the Pico's CRC32 of what it received must match
# ours. -Verify also reads the chunk back from the FPGA (`c`) and compares the
# CRC32 of the VRAM contents. Uses System.IO.Ports, so run it with Windows
# PowerShell 5.1 (powershell.exe).
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Port,
    [Parameter(Mandatory)][string]$File,
    [Parameter(Mandatory)][string]$Address,      # hex VRAM address, e.g. 0x0000 or 9400
    [ValidateSet('', 'spi', 'qspi')][string]$Mode = '',
    [int]$Div = 0,
    [switch]$Verify
)
$ErrorActionPreference = 'Stop'
$chunkSize = 4096
$poly = [uint32]3988292384    # 0xEDB88320; hex literals above 0x7FFFFFFF are negative in PowerShell 5.1
$table = New-Object 'uint32[]' 256
for ($i = 0; $i -lt 256; $i++) {
    $c = [uint32]$i
    for ($k = 0; $k -lt 8; $k++) { if ($c -band 1) { $c = $poly -bxor ($c -shr 1) } else { $c = $c -shr 1 } }
    $table[$i] = $c
}
function Get-Crc32([byte[]]$data, [int]$offset, [int]$count) {
    $c = [uint32]::MaxValue
    for ($i = $offset; $i -lt $offset + $count; $i++) { $c = $table[($c -bxor $data[$i]) -band 0xFF] -bxor ($c -shr 8) }
    '{0:x8}' -f ($c -bxor [uint32]::MaxValue)
}
$base = [Convert]::ToUInt32(($Address -replace '^0x', ''), 16)
$data = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $File))
if ($data.Length -eq 0) { throw 'File is empty' }
if ($base + $data.Length -gt 0x1000000) { throw 'Upload exceeds the 24-bit VRAM address space' }

$serial = New-Object System.IO.Ports.SerialPort $Port, 115200
$serial.DtrEnable = $true      # the Pico's USB stdio only talks to an open (DTR) port
$serial.ReadTimeout = 5000
$serial.NewLine = "`n"
$serial.Open()
function Send-Line([string]$text) { $serial.Write("$text`n") }
function Read-Reply([string]$prefix) {
    while ($true) {
        $line = $serial.ReadLine().Trim()
        if ($line.StartsWith('ERR')) { throw "Pico: $line" }
        if ($line.StartsWith($prefix)) { return $line }
    }
}
try {
    Start-Sleep -Milliseconds 200
    $serial.DiscardInBuffer()
    if ($Mode) { Send-Line "mode $Mode"; [void](Read-Reply 'OK') }
    if ($Div) { Send-Line "div $Div"; [void](Read-Reply 'OK') }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $deviceUs = 0L
    for ($offset = 0; $offset -lt $data.Length; $offset += $chunkSize) {
        $count = [math]::Min($chunkSize, $data.Length - $offset)
        $addr = '{0:x6}' -f ($base + $offset)
        $crc = Get-Crc32 $data $offset $count
        Send-Line "w $addr $count"
        [void](Read-Reply 'READY')
        $serial.Write($data, $offset, $count)
        $ok = (Read-Reply 'OK') -split ' '
        if ($ok[3] -ne $crc) { throw "Chunk at 0x${addr}: Pico received CRC $($ok[3]), expected $crc" }
        $deviceUs += [long]$ok[2]
        if ($Verify) {
            Send-Line "c $addr $count"
            $back = (Read-Reply 'CRC') -split ' '
            if ($back[3] -ne $crc) { throw "Chunk at 0x${addr}: VRAM read-back CRC $($back[3]), expected $crc" }
        }
        Write-Host ('0x{0}: {1} bytes OK{2}' -f $addr, $count, $(if ($Verify) { ', verified' } else { '' }))
    }
    $seconds = $watch.Elapsed.TotalSeconds
    Write-Host ('Uploaded {0} bytes to 0x{1:x6} in {2:n2} s; Pico->FPGA {3:n1} KB/s' -f $data.Length, $base, $seconds, ($data.Length / 1.0 / [math]::Max(1, $deviceUs) * 1000))
} finally {
    $serial.Close()
}
