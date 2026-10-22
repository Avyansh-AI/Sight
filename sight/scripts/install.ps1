param([switch]$Offline, [string]$Wheelhouse, [string]$BrowserCache)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$sightIndexArgs = @()
if ($Offline) {
    if (-not $Wheelhouse) { $Wheelhouse = Join-Path (Split-Path -Parent (Get-Location).Path) 'offline\wheels' }
    if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) { throw 'Offline installation requires the provisioned, hash-verified wheel directory.' }
    $sightIndexArgs = @('--no-index', '--find-links', (Resolve-Path -LiteralPath $Wheelhouse).Path)
}
if ($BrowserCache) { $env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path -LiteralPath $BrowserCache).Path }
if (!(Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 venv creation failed" }
}
& .venv\Scripts\python.exe -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes @sightIndexArgs -r requirements-bootstrap.lock
if ($LASTEXITCODE -ne 0) { throw "Hash-verified installer bootstrap failed" }
& .venv\Scripts\python.exe -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes @sightIndexArgs -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw "Hash-verified dependency installation failed" }
& .venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed" }
if ($Offline) {
    & .venv\Scripts\python.exe -c "from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); exists=Path(p.chromium.executable_path).is_file(); p.stop(); raise SystemExit(0 if exists else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Chromium is not provisioned. Supply a matching BrowserCache or install it online before going offline.' }
} else {
    & .venv\Scripts\python.exe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Browser test prerequisite installation failed" }
}
& .venv\Scripts\python.exe -m sight_core.cli doctor
exit $LASTEXITCODE
