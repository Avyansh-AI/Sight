param([switch]$Thinking, [string]$Prompt, [string]$OllamaExecutable)
$ErrorActionPreference = 'Stop'
$sightOllama = & (Join-Path $PSScriptRoot 'sight\scripts\find_ollama.ps1') -ExecutablePath $OllamaExecutable
$sightModel = 'gemma4:e4b-it-qat'
try { $sightTags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 }
catch { throw 'Start the existing local runtime with Start-Local-Runtime.ps1 first.' }
if ($sightModel -notin $sightTags.models.name) {
    throw 'The official Gemma 4 E4B model is not installed. Run ollama pull gemma4:e4b-it-qat first. No download was attempted by this helper.'
}
$sightMode = if ($Thinking) { '--think=true' } else { '--think=false' }
$sightArgs = @('run', $sightModel, $sightMode)
if ($Prompt) { $sightArgs += $Prompt }
& $sightOllama @sightArgs
exit $LASTEXITCODE
