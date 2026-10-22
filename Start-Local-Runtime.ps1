param(
    [string]$ModelsDirectory,
    [ValidateRange(1, 300)][int]$ReadyTimeoutSeconds = 120,
    [string]$OllamaExecutable
)
$ErrorActionPreference = 'Stop'
function Test-SightRuntimeReady {
    try {
        $sightVersion = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
        return [bool]$sightVersion.version
    } catch { return $false }
}
if (Test-SightRuntimeReady) {
    Write-Output 'Ollama is responding. Systems will verify the selected model.'
    return
}
$sightProcess = $null
# A listening port is not proof that GPU discovery or HTTP startup has finished.
# Wait for an existing listener instead of creating a competing server.
$sightListener = Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction SilentlyContinue
if (-not $sightListener) {
    $sightOllama = & (Join-Path $PSScriptRoot 'sight\scripts\find_ollama.ps1') -ExecutablePath $OllamaExecutable
    if (-not $ModelsDirectory) {
        if ($env:OLLAMA_MODELS) { $ModelsDirectory = $env:OLLAMA_MODELS }
        elseif (Test-Path -LiteralPath 'D:\Ollama Models' -PathType Container) { $ModelsDirectory = 'D:\Ollama Models' }
        else { $ModelsDirectory = Join-Path $env:USERPROFILE '.ollama\models' }
    }
    if (-not (Test-Path -LiteralPath $ModelsDirectory -PathType Container)) {
        throw 'Select an existing model directory with -ModelsDirectory or OLLAMA_MODELS. This helper does not download weights.'
    }
    $sightChildEnvironment = @{
        OLLAMA_MODELS = (Resolve-Path -LiteralPath $ModelsDirectory).Path
        OLLAMA_HOST = '127.0.0.1:11434'
        OLLAMA_NO_CLOUD = 'true'
        # Workaround for the reproduced CUDA initialization failure.
        CUDA_MODULE_LOADING = 'EAGER'
        OLLAMA_NUM_PARALLEL = '1'
        OLLAMA_MAX_LOADED_MODELS = '1'
        OLLAMA_CONTEXT_LENGTH = '4096'
    }
    $sightPreviousEnvironment = @{}
    foreach ($sightName in $sightChildEnvironment.Keys) {
        $sightPreviousEnvironment[$sightName] = [Environment]::GetEnvironmentVariable($sightName, 'Process')
    }
    try {
        foreach ($sightName in $sightChildEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($sightName, $sightChildEnvironment[$sightName], 'Process')
        }
        $sightProcess = Start-Process -FilePath $sightOllama -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    } finally {
        # The child inherited its own copy; keep the invoking shell unchanged.
        foreach ($sightName in $sightPreviousEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($sightName, $sightPreviousEnvironment[$sightName], 'Process')
        }
    }
}
Write-Output 'Waiting for local Ollama to finish startup and respond...'
$sightTimer = [Diagnostics.Stopwatch]::StartNew()
while ($sightTimer.Elapsed.TotalSeconds -lt $ReadyTimeoutSeconds) {
    if ($sightProcess -and $sightProcess.HasExited) {
        throw "Ollama exited during startup (exit code $($sightProcess.ExitCode))."
    }
    if (Test-SightRuntimeReady) {
        Write-Output 'Local Ollama is responding on 127.0.0.1:11434. Systems will verify the selected model.'
        return
    }
    Start-Sleep -Milliseconds 500
}
throw "Ollama did not respond within $ReadyTimeoutSeconds seconds. Its process may still be initializing; no existing process was stopped. Inspect Ollama before opening SIGHT."
