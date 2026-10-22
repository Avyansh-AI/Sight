$ErrorActionPreference = 'Stop'
$sightPython = Join-Path $PSScriptRoot 'sight\.venv\Scripts\python.exe'
$sightVerify = Join-Path $PSScriptRoot 'sight\scripts\verify.py'
if (-not (Test-Path -LiteralPath $sightPython)) { throw 'Run sight\scripts\install.ps1 first.' }
& $sightPython $sightVerify
exit $LASTEXITCODE
