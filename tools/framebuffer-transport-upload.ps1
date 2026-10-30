# SPDX-License-Identifier: Apache-2.0
# Stage a new isolated benchmark file with a raw-REPL ACK per 512 bytes.
[CmdletBinding()]
param(
    [string]$Port='COM7',
    [Parameter(Mandatory=$true)][string]$CodeFile,
    [Parameter(Mandatory=$true)][string]$LogFile,
    [switch]$Execute,
    [string]$ExecutionLogFile,
    [string]$PostCodeFile,
    [int]$TimeoutSeconds=900
)
$ErrorActionPreference='Stop'
$remote='/transport_bench_20261030.py'
$bytes=[IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $CodeFile))
$expected=(Get-FileHash -LiteralPath $CodeFile -Algorithm SHA256).Hash.ToLowerInvariant()
$serial=[IO.Ports.SerialPort]::new($Port,115200)
$serial.DtrEnable=$true;$serial.RtsEnable=$true
$serial.ReadTimeout=100;$serial.WriteTimeout=5000
$serial.Encoding=[Text.UTF8Encoding]::new($false)
$log=[IO.StreamWriter]::new($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($LogFile),$false,[Text.UTF8Encoding]::new($false))
$log.AutoFlush=$true
function Record([string]$message) {
    $line=([DateTimeOffset]::Now.ToString('o'))+' '+$message
    $log.WriteLine($line);Write-Output $line
}
function UntilPrompt([int]$seconds,[bool]$initial=$false) {
    $watch=[Diagnostics.Stopwatch]::StartNew();$response=''
    $interrupted=$false
    $ending=([string][char]4)+'>'
    while(!($response.EndsWith($ending) -or ($initial -and $response.EndsWith('>')))) {
        if($watch.Elapsed.TotalSeconds -gt $seconds -and !$interrupted){
            if(!$script:CaptureLog){throw 'raw REPL acknowledgement timeout; no automatic replay'}
            $serial.Write([string][char]3);$interrupted=$true
        }
        if($interrupted -and $watch.Elapsed.TotalSeconds -gt $seconds+15){throw 'execution timeout; cleanup unconfirmed'}
        $chunk=$serial.ReadExisting()
        $response+=$chunk
        if($script:CaptureLog -and $chunk){
            [IO.File]::AppendAllText($script:CaptureLog,$chunk,[Text.UTF8Encoding]::new($false))
            $script:CaptureLine+=$chunk
            while($script:CaptureLine.Contains("`n")){
                $end=$script:CaptureLine.IndexOf("`n")
                $line=$script:CaptureLine.Substring(0,$end)
                $script:CaptureLine=$script:CaptureLine.Substring($end+1)
                if($line -match '"event":\s*"([^"]+)"'){[Console]::WriteLine('DEVICE '+$Matches[1])}
            }
        }
        Start-Sleep -Milliseconds 5
    }
    return $response
}
function Raw([string]$code,[int]$seconds=25) {
    for($position=0;$position -lt $code.Length;$position+=128) {
        $serial.Write($code.Substring($position,[Math]::Min(128,$code.Length-$position)))
        Start-Sleep -Milliseconds 2
    }
    $serial.Write([string][char]4)
    $reply=UntilPrompt $seconds
    if(!$reply.StartsWith('OK')){throw 'raw REPL acknowledgement missing'}
    $parts=$reply.Substring(2).Split([char]4)
    if($parts[1]){throw $parts[1]}
    if($parts[0] -and !$script:CaptureLog){Record ($parts[0].Trim())}
}
try {
    Record ('OPEN '+$Port+' bytes='+$bytes.Length+' sha256='+$expected)
    $serial.Open();$serial.DiscardInBuffer()
    $serial.Write([string][char]1)
    $null=UntilPrompt 10 $true
    Record 'RAW_PROMPT_ACK'
    # Execute cleanup BEFORE receiving the larger source, not in its prelude.
    Raw "import gc`nif 'kagura_console' in globals() and kagura_console is not None:kagura_console.close();kagura_console=None`nif '_session' in globals():_session=None`ngc.collect()`nprint('UPLOAD_HEAP',gc.mem_free())"
    Raw ("import binascii`n_transport_file=open('"+$remote+"','wb')")
    for($offset=0;$offset -lt $bytes.Length;$offset+=512) {
        $count=[Math]::Min(512,$bytes.Length-$offset)
        $hex=[BitConverter]::ToString($bytes,$offset,$count).Replace('-','').ToLowerInvariant()
        Raw ("assert _transport_file.write(binascii.unhexlify('"+$hex+"'))=="+$count)
        Record ('FILE_PREFIX_ACK '+($offset+$count))
    }
    Raw "_transport_file.close()`nimport hashlib`n_transport_hash=hashlib.sha256()`nwith open('$remote','rb') as _file:`n while True:`n  _block=_file.read(512)`n  if not _block:break`n  _transport_hash.update(_block)`nassert binascii.hexlify(_transport_hash.digest()).decode()=='$expected'`nprint('UPLOAD_SHA256_PASS','$expected')`ngc.collect()"
    Record 'UPLOAD_COMPLETE'
    if($Execute){
        if(!$ExecutionLogFile){throw 'ExecutionLogFile required with Execute'}
        $script:CaptureLog=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ExecutionLogFile)
        [IO.File]::WriteAllText($script:CaptureLog,'',[Text.UTF8Encoding]::new($false))
        $script:CaptureLine=''
        Record 'EXECUTION_START_SAME_SERIAL_CONNECTION'
        Raw 'import transport_bench_20261030' $TimeoutSeconds
        $script:CaptureLog=$null
        Record 'EXECUTION_RETURNED'
        if($PostCodeFile){
            $script:CaptureLog=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ExecutionLogFile+'.validation.log')
            [IO.File]::WriteAllText($script:CaptureLog,'',[Text.UTF8Encoding]::new($false))
            $script:CaptureLine=''
            Raw ([IO.File]::ReadAllText((Resolve-Path -LiteralPath $PostCodeFile))) 300
            $script:CaptureLog=$null
            Record 'POST_VALIDATION_RETURNED'
        }
    }
} finally {
    if($serial.IsOpen){try{$serial.Write([string][char]2)}finally{$serial.Close()}}
    $serial.Dispose();$log.Dispose()
}
