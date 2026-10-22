"""Exercise the Windows launcher's readiness decisions without starting a GPU."""
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("scenario", ["delayed", "exited", "existing", "ready"])
def test_runtime_launcher_reports_readiness_not_process_creation(tmp_path, scenario):
    if os.name != "nt":
        pytest.skip("Windows PowerShell launcher")
    launcher = str(ROOT / "Start-Local-Runtime.ps1").replace("'", "''")
    wrapper = tmp_path / "exercise.ps1"
    wrapper.write_text(
        f"""
$ErrorActionPreference = 'Stop'
$global:sightTestAttempts = 0
$global:sightTestSpawned = 0
function Test-Path {{ return $true }}
function Resolve-Path {{ return [pscustomobject]@{{Path='D:\\Synthetic Models'}} }}
function Start-Sleep {{}}
function Get-NetTCPConnection {{
    if ('{scenario}' -eq 'existing') {{ return [pscustomobject]@{{LocalPort=11434}} }}
}}
function Invoke-RestMethod {{
    $global:sightTestAttempts++
    if ('{scenario}' -eq 'ready' -or ('{scenario}' -ne 'exited' -and $global:sightTestAttempts -ge 3)) {{
        return [pscustomobject]@{{version='synthetic'}}
    }}
    throw 'Synthetic runtime still discovering GPUs'
}}
function Start-Process {{
    $global:sightTestSpawned++
    return [pscustomobject]@{{Id=987654;HasExited=('{scenario}' -eq 'exited');ExitCode=23}}
}}
try {{
    & '{launcher}'
    if ('{scenario}' -eq 'exited') {{ throw 'Launcher claimed success after the child exited' }}
    if ($global:sightTestAttempts -lt 3 -and '{scenario}' -ne 'ready') {{ throw 'No readiness verification' }}
    $expected = if ('{scenario}' -eq 'delayed') {{ 1 }} else {{ 0 }}
    if ($global:sightTestSpawned -ne $expected) {{ throw 'Unexpected runtime spawned' }}
    Write-Output 'READINESS_CHECK_PASS'
}} catch {{
    if ('{scenario}' -eq 'exited' -and $_.Exception.Message -like '*exited*23*') {{
        Write-Output 'READINESS_CHECK_PASS'
    }} else {{
        Write-Error $_
        exit 1
    }}
}}
""", encoding="utf-8")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-File", str(wrapper)],
                            capture_output=True, text=True, timeout=20, creationflags=0x08000000)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "READINESS_CHECK_PASS" in result.stdout
