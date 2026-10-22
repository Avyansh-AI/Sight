"""Exercise cross-account launcher choices without touching a real model store."""
import os
from pathlib import Path
import subprocess

import pytest


SCENARIOS = ['ready_without_install', 'initializing_without_install', 'environment_store',
             'default_store', 'legacy_store', 'explicit_store', 'missing_explicit_store',
             'path_executable', 'spawn_failure']


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_runtime_portable_paths_and_parent_environment(tmp_path, scenario):
    if os.name != 'nt':
        pytest.skip('Windows runtime launcher')
    launcher = str(Path(__file__).resolve().parents[2] / 'Start-Local-Runtime.ps1').replace("'", "''")
    wrapper = tmp_path / 'portable.ps1'
    wrapper.write_text(r'''
$ErrorActionPreference = 'Stop'
$global:sightScenario = 'SCENARIO'
$global:sightCalls = 0
$global:sightSpawned = 0
$global:sightSelectedStore = $null
$global:sightSelectedExe = $null
$global:sightPerUserExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
$global:sightPathExe = Join-Path $env:TEMP 'Synthetic App\ollama.exe'
$global:sightEnvironmentStore = Join-Path $env:TEMP 'Synthetic Env Models'
$global:sightExplicitStore = Join-Path $env:TEMP 'Synthetic Explicit Models'
$global:sightDefaultStore = Join-Path $env:USERPROFILE '.ollama\models'
$global:sightExpectedStore = switch ($global:sightScenario) {
    'environment_store' { $global:sightEnvironmentStore }
    'explicit_store' { $global:sightExplicitStore }
    'legacy_store' { 'D:\Ollama Models' }
    default { $global:sightDefaultStore }
}
$sightNames = @('OLLAMA_MODELS','OLLAMA_HOST','OLLAMA_NO_CLOUD','CUDA_MODULE_LOADING',
                'OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS','OLLAMA_CONTEXT_LENGTH')
foreach ($sightName in $sightNames) { [Environment]::SetEnvironmentVariable($sightName, $null, 'Process') }
$env:OLLAMA_HOST = '127.0.0.1:9999'
$env:OLLAMA_NUM_PARALLEL = '3'
if ($global:sightScenario -in @('environment_store','explicit_store','missing_explicit_store')) {
    $env:OLLAMA_MODELS = $global:sightEnvironmentStore
}
$sightBefore = @{}
foreach ($sightName in $sightNames) { $sightBefore[$sightName] = [Environment]::GetEnvironmentVariable($sightName,'Process') }
function Test-Path {
    param([string]$LiteralPath, [string]$PathType)
    if ($global:sightScenario -in @('ready_without_install','initializing_without_install')) { return $false }
    if ($LiteralPath -eq $global:sightPerUserExe) { return ($global:sightScenario -ne 'path_executable') }
    if ($LiteralPath -eq $global:sightPathExe) { return $true }
    if ($global:sightScenario -eq 'missing_explicit_store') { return ($LiteralPath -eq $global:sightEnvironmentStore) }
    return ($LiteralPath -eq $global:sightExpectedStore)
}
function Resolve-Path { param([string]$LiteralPath) return [pscustomobject]@{Path=$LiteralPath} }
function Get-Command {
    param($Name,$CommandType,$ErrorAction)
    if ($global:sightScenario -eq 'path_executable') { return [pscustomobject]@{Source=$global:sightPathExe} }
}
function Get-NetTCPConnection {
    if ($global:sightScenario -eq 'initializing_without_install') { return [pscustomobject]@{LocalPort=11434} }
}
function Invoke-RestMethod {
    $global:sightCalls++
    if ($global:sightScenario -eq 'ready_without_install' -or $global:sightCalls -ge 3) {
        return [pscustomobject]@{version='synthetic'}
    }
    throw 'Synthetic startup in progress'
}
function Start-Sleep {}
function Start-Process {
    param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru)
    $global:sightSpawned++
    if ($WindowStyle -ne 'Hidden' -or $ArgumentList -ne 'serve') { throw 'Unsafe launch contract' }
    if ($env:OLLAMA_HOST -ne '127.0.0.1:11434' -or $env:OLLAMA_NO_CLOUD -ne 'true' -or
        $env:CUDA_MODULE_LOADING -ne 'EAGER' -or $env:OLLAMA_NUM_PARALLEL -ne '1' -or
        $env:OLLAMA_MAX_LOADED_MODELS -ne '1' -or $env:OLLAMA_CONTEXT_LENGTH -ne '4096') { throw 'Incorrect child configuration' }
    $global:sightSelectedStore = $env:OLLAMA_MODELS
    $global:sightSelectedExe = $FilePath
    if ($global:sightScenario -eq 'spawn_failure') { throw 'Synthetic process creation failure' }
    return [pscustomobject]@{HasExited=$false;ExitCode=$null}
}
$sightCaught = $null
try {
    if ($global:sightScenario -in @('explicit_store','missing_explicit_store')) {
        & 'LAUNCHER' -ModelsDirectory $global:sightExplicitStore
    } else { & 'LAUNCHER' }
} catch { $sightCaught = $_.Exception.Message }
foreach ($sightName in $sightNames) {
    if ([Environment]::GetEnvironmentVariable($sightName,'Process') -cne $sightBefore[$sightName]) {
        throw "Launcher changed caller environment: $sightName"
    }
}
if ($global:sightScenario -eq 'missing_explicit_store') {
    if ($global:sightSpawned -ne 0 -or $sightCaught -notlike '*model directory*') { throw 'Explicit invalid directory was silently replaced' }
} elseif ($global:sightScenario -eq 'spawn_failure') {
    if ($sightCaught -ne 'Synthetic process creation failure') { throw 'Expected spawn failure was not preserved' }
} else {
    if ($sightCaught) { throw $sightCaught }
    $sightExpectedSpawn = if ($global:sightScenario -in @('ready_without_install','initializing_without_install')) { 0 } else { 1 }
    if ($global:sightSpawned -ne $sightExpectedSpawn) { throw 'Unexpected spawn count' }
    if ($sightExpectedSpawn) {
        if ($global:sightSelectedStore -ne $global:sightExpectedStore) { throw 'Wrong existing model directory selected' }
        $sightExpectedExe = if ($global:sightScenario -eq 'path_executable') { $global:sightPathExe } else { $global:sightPerUserExe }
        if ($global:sightSelectedExe -ne $sightExpectedExe) { throw 'Wrong executable selected' }
    }
}
Write-Output 'PORTABILITY_CHECK_PASS'
'''.replace('SCENARIO', scenario).replace('LAUNCHER', launcher), encoding='utf-8')
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-File', str(wrapper)],
                            capture_output=True, text=True, timeout=15, creationflags=0x08000000)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PORTABILITY_CHECK_PASS' in result.stdout
