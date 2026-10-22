$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
& .venv\Scripts\python.exe scripts\verify.py
exit $LASTEXITCODE
