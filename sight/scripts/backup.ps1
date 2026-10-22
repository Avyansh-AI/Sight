param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
& .venv\Scripts\python.exe -m sight_core.cli backup $Destination
exit $LASTEXITCODE
