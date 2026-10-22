param([switch]$AllowConfiguredCloud)
$ErrorActionPreference = 'Stop'
if (-not $env:SIGHT_DATA_DIR) { $env:SIGHT_DATA_DIR = Join-Path $PSScriptRoot 'owner-data' }
if (-not $env:SIGHT_PORT) { $env:SIGHT_PORT = '8084' }
$sightPython = Join-Path $PSScriptRoot 'sight\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $sightPython)) { throw 'Run sight\scripts\install.ps1 first.' }
$sightLaunch = Join-Path $PSScriptRoot 'sight\scripts\launch.py'
if ($AllowConfiguredCloud) { & $sightPython $sightLaunch } else { & $sightPython $sightLaunch --local-only }
exit $LASTEXITCODE
