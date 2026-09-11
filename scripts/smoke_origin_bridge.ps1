param(
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Mandatory=$true)][string]$InputFile,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$Clsid = '{64CC80B2-4FA1-4F7B-9D6F-1BFACF5715DC}'
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Output directory must be new.' }
$before = (Get-FileHash -LiteralPath $InputFile -Algorithm SHA256).Hash
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
$outputFile = Join-Path $OutputDirectory 'roundtrip.bin'
& $Executable inspect $InputFile
if ($LASTEXITCODE -ne 0) { throw 'Storage inspection failed.' }
& $Executable --probe $InputFile $outputFile --clsid $Clsid
if ($LASTEXITCODE -ne 0) { throw 'Origin storage roundtrip failed.' }
$savedHash = (Get-FileHash -LiteralPath $outputFile -Algorithm SHA256).Hash
& $Executable --probe $InputFile $outputFile --clsid $Clsid
if ($LASTEXITCODE -eq 0) { throw 'Existing output was accepted.' }
if ((Get-FileHash -LiteralPath $outputFile -Algorithm SHA256).Hash -ne $savedHash) {
    throw 'Existing output was modified.'
}
& $Executable --probe $InputFile (Join-Path $OutputDirectory 'rejected.bin') --clsid '{00000000-0000-0000-0000-000000000000}'
if ($LASTEXITCODE -eq 0) { throw 'Incorrect CLSID was accepted.' }
if ((Get-FileHash -LiteralPath $InputFile -Algorithm SHA256).Hash -ne $before) {
    throw 'Input was modified.'
}
Write-Output 'PASS: storage roundtrip, class gate, no overwrite, input unchanged. Interactive editing remains unverified.'
