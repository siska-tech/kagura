# SPDX-License-Identifier: Apache-2.0
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$dir=Join-Path $root 'third_party/hdl-util-hdmi'
$manifest=Get-Content -LiteralPath (Join-Path $dir 'manifest.json') -Raw | ConvertFrom-Json
if($manifest.revision -ne '83b1c9543a91b776671a44e68e130f81cae437b7') { throw 'Unexpected HDMI revision' }
foreach($file in $manifest.files) {
    $hash=(Get-FileHash -LiteralPath (Join-Path $dir $file.path) -Algorithm SHA256).Hash.ToLowerInvariant()
    if($hash -ne $file.sha256) { throw "Dependency modified: $($file.path)" }
}
Write-Output "PASS: $($manifest.files.Count) pinned dependency files match SHA256 manifest."
