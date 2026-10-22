param([string]$ExecutablePath)
$ErrorActionPreference = 'Stop'
if (-not $ExecutablePath) {
    $sightPerUser = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $sightPerUser -PathType Leaf) {
        $ExecutablePath = $sightPerUser
    } else {
        $sightCommand = Get-Command ollama.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($sightCommand) { $ExecutablePath = $sightCommand.Source }
    }
}
if (-not $ExecutablePath -or -not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw 'Ollama executable not found. Install Ollama, add it to PATH, or pass -OllamaExecutable with its existing path.'
}
(Resolve-Path -LiteralPath $ExecutablePath).Path
