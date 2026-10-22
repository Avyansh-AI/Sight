param([switch]$AllowConfiguredCloud)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Run scripts\install.ps1 first.' }
if ($AllowConfiguredCloud) {
    & .venv\Scripts\python.exe -m sight_core.cli start
} else {
    & .venv\Scripts\python.exe -m sight_core.cli start --local-only
}
exit $LASTEXITCODE
