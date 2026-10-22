$ErrorActionPreference = 'Stop'
if (-not $env:SIGHT_DATA_DIR) { $env:SIGHT_DATA_DIR = Join-Path $PSScriptRoot 'owner-data' }
if (-not $env:SIGHT_PORT) { $env:SIGHT_PORT = '8084' }
Push-Location (Join-Path $PSScriptRoot 'sight')
try { & .venv\Scripts\python.exe -m sight_core.cli open; $sightExit = $LASTEXITCODE } finally { Pop-Location }
exit $sightExit
